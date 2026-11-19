"""Entrega 2, punto 5: curvas de supervivencia de Kaplan-Meier por categoría principal y por zona.

1. Spark agrega, para cada negocio, la fecha de su primera y su última reseña (una pasada sobre `reviews`).
2. Con ellas se arma el registro de supervivencia de cada negocio (survival.business_record): tiempo = días
   entre la primera y la última reseña, evento = cierre observado (`is_open = 0`), abierto = censurado y
   **entrada tardía** para los negocios que ya existían cuando empieza la ventana de observación
   (--window-start): se guardan en `business_survival`, con su ubicación GeoJSON y un índice 2dsphere.
3. Curvas de Kaplan-Meier por **categoría principal** -> `survival_by_category`.
4. Curvas por **zona** -> `survival_by_zone`: cada zona es un polígono (`zones`) y los negocios que caen dentro se
   consultan en MongoDB con **$geoWithin**. Por defecto las zonas son las áreas de las ciudades con más
   negocios (rectángulo p1-p99 de sus coordenadas); --zones-file admite otras zonas en GeoJSON.

Cada curva guarda, por instante con cierres: tiempo (días), número en riesgo, cierres, censurados, S(t) y su
intervalo de confianza del 95 %; además la mediana de vida cuando existe (`null` si la curva no baja de 0,5),
S a 1, 3, 5 y 10 años y `meets_min` (grupos con pocos negocios o cierres no permiten conclusiones).

Uso:
    docker compose --profile jobs run --rm spark-jobs spark-submit /app/survival_km.py \\
        [--window-start 2010-01-01] [--top-zones 10] [--zones-file zonas.geojson]
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone

from pyspark.sql import functions as F

from geo_windows import from_epoch_seconds
from lifemap_common import DB_NAME, MONGO_URI, build_spark, read_collection
from survival import (
    DAYS_PER_YEAR,
    MIN_BUSINESSES,
    MIN_EVENTS,
    bounding_polygon,
    business_record,
    kaplan_meier,
    meets_min,
    primary_category,
    survival_at,
    window_start_datetime,
    years,
)

CURVE_FIELDS = ["t", "n_risk", "n_events", "n_censored", "survival", "ci_low", "ci_high"]
HORIZONS_YEARS = (1, 3, 5, 10)


def parse_args():
    parser = argparse.ArgumentParser(description="Curvas de Kaplan-Meier por categoría y por zona")
    parser.add_argument(
        "--window-start",
        default="2010-01-01",
        help="inicio de la ventana de observación: los negocios que ya existían entran con su edad",
    )
    parser.add_argument("--top-zones", type=int, default=10, help="ciudades con más negocios que forman las zonas")
    parser.add_argument(
        "--zones-file",
        default=None,
        help="GeoJSON (FeatureCollection de polígonos, con properties.name) en lugar de las ciudades",
    )
    parser.add_argument("--min-businesses", type=int, default=MIN_BUSINESSES)
    parser.add_argument("--min-events", type=int, default=MIN_EVENTS)
    return parser.parse_args()


def load_lifetimes(spark):
    """Negocios con la fecha de su primera y su última reseña, en segundos desde 1970 (sin zonas horarias)."""
    vida = (
        read_collection(spark, "reviews")
        .groupBy("business_id")
        .agg(
            F.unix_timestamp(F.min(F.col("date").cast("timestamp"))).alias("first_s"),
            F.unix_timestamp(F.max(F.col("date").cast("timestamp"))).alias("last_s"),
            F.count("*").alias("n_reviews"),
        )
    )
    negocios = read_collection(spark, "businesses").select(
        "business_id",
        "city",
        "state",
        "categories",
        F.col("is_open").cast("int").alias("is_open"),
        F.col("location.coordinates")[0].alias("lon"),
        F.col("location.coordinates")[1].alias("lat"),
    )
    return negocios.join(vida, "business_id").where(F.col("lon").isNotNull() & F.col("is_open").isNotNull())


def survival_docs(rows, window_start):
    """Documentos de `business_survival` a partir de las filas de Spark; los no observados se descartan."""
    docs, discarded = [], 0
    for r in rows:
        registro = business_record(
            from_epoch_seconds(r["first_s"]), from_epoch_seconds(r["last_s"]), r["is_open"], window_start
        )
        if registro is None:
            discarded += 1
            continue
        entry, duration, event = registro
        docs.append(
            {
                "_id": r["business_id"],
                "business_id": r["business_id"],
                "city": r["city"],
                "state": r["state"],
                "primary_category": primary_category(r["categories"]),
                "location": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "first_review": from_epoch_seconds(r["first_s"]),
                "last_review": from_epoch_seconds(r["last_s"]),
                "is_open": r["is_open"],
                "entry_days": entry,
                "duration_days": duration,
                "event": event,
            }
        )
    return docs, discarded


def group_document(name, kind, records, args, window_start, extra=None):
    """Documento de una curva: resumen del grupo + curva comprimida como lista de filas."""
    km = kaplan_meier(records)
    doc = {
        "_id": name,
        "group": name,
        "kind": kind,
        "n_businesses": km["n"],
        "n_events": km["n_events"],
        "n_censored": km["n_censored"],
        "n_late_entry": km["n_late_entry"],
        "median_days": km["median"],
        "median_years": years(km["median"]),
        "meets_min": meets_min(km["n"], km["n_events"], args.min_businesses, args.min_events),
        "window_start": window_start,
        "curve_fields": CURVE_FIELDS,
        "curve": [[p[f] for f in CURVE_FIELDS] for p in km["curve"]],
        "computed_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    for horizon in HORIZONS_YEARS:
        doc[f"survival_{horizon}y"] = survival_at(km["curve"], horizon * DAYS_PER_YEAR) if km["n"] else None
    if extra:
        doc.update(extra)
    return doc


def build_zones(docs, args):
    """Zonas (nombre, polígono) de las ciudades con más negocios, o las de --zones-file."""
    if args.zones_file:
        with open(args.zones_file, encoding="utf-8") as archivo:
            colección = json.load(archivo)
        return [
            {
                "_id": f["properties"]["name"],
                "name": f["properties"]["name"],
                "geometry": f["geometry"],
                "source": "file",
            }
            for f in colección["features"]
        ]

    por_ciudad = defaultdict(list)
    for d in docs:
        por_ciudad[(d["city"], d["state"])].append(tuple(d["location"]["coordinates"]))
    mayores = sorted(por_ciudad.items(), key=lambda kv: len(kv[1]), reverse=True)[: args.top_zones]
    return [
        {
            "_id": f"{city}, {state}",
            "name": f"{city}, {state}",
            "geometry": bounding_polygon(coords),
            "source": "city",
            "city_businesses": len(coords),
        }
        for (city, state), coords in mayores
    ]


def run():
    args = parse_args()
    window_start = window_start_datetime(args.window_start)
    spark = build_spark("LifeMap-SurvivalKM")
    spark.sparkContext.setLogLevel("WARN")

    print(f"Primera y última reseña de cada negocio (ventana de observación desde {args.window_start})...")
    filas = [fila.asDict() for fila in load_lifetimes(spark).collect()]
    spark.stop()

    docs, discarded = survival_docs(filas, window_start)
    tardias = sum(1 for d in docs if d["entry_days"] > 0)
    cierres = sum(d["event"] for d in docs)
    print(
        f"Negocios con reseñas: {len(filas)}; observados en la ventana: {len(docs)} "
        f"({discarded} terminan antes de {args.window_start} y se excluyen)"
    )
    print(
        f"  cierres observados: {cierres}; censurados (abiertos): {len(docs) - cierres}; "
        f"entrada tardía (ya existían al empezar la ventana): {tardias}"
    )

    from pymongo import ASCENDING, GEOSPHERE, MongoClient

    db = MongoClient(MONGO_URI)[DB_NAME]
    db.business_survival.delete_many({})
    for inicio in range(0, len(docs), 10000):
        db.business_survival.insert_many(docs[inicio : inicio + 10000], ordered=False)
    db.business_survival.create_index([("location", GEOSPHERE)])
    db.business_survival.create_index([("primary_category", ASCENDING)])

    # --- por categoría principal (y el total) ---
    registros = defaultdict(list)
    for d in docs:
        registros[d["primary_category"]].append((d["entry_days"], d["duration_days"], d["event"]))
    por_categoria = [group_document("(todas)", "all", [r for v in registros.values() for r in v], args, window_start)]
    por_categoria += [group_document(c, "category", r, args, window_start) for c, r in registros.items()]
    db.survival_by_category.delete_many({})
    db.survival_by_category.insert_many(por_categoria)
    db.survival_by_category.create_index([("n_businesses", -1)])

    # --- por zona, con $geoWithin ---
    zonas = build_zones(docs, args)
    db.zones.delete_many({})
    db.zones.insert_many(zonas)
    db.zones.create_index([("geometry", GEOSPHERE)])
    por_zona = []
    for zona in zonas:
        en_zona = db.business_survival.find(
            {"location": {"$geoWithin": {"$geometry": zona["geometry"]}}},
            {"entry_days": 1, "duration_days": 1, "event": 1},
        )
        r = [(d["entry_days"], d["duration_days"], d["event"]) for d in en_zona]
        por_zona.append(group_document(zona["name"], "zone", r, args, window_start, {"geometry": zona["geometry"]}))
    db.survival_by_zone.delete_many({})
    db.survival_by_zone.insert_many(por_zona)

    # --- resumen en consola ---
    def fila(doc):
        mediana = f"{doc['median_years']:.1f} años" if doc["median_years"] else "no baja de 0,5"
        s5 = f"{doc['survival_5y']:.3f}" if doc["survival_5y"] is not None else "—"
        return f"{doc['group'][:34]:<35}{doc['n_businesses']:>8}{doc['n_events']:>8}{s5:>8}   {mediana}"

    cabecera = f"{'grupo':<35}{'negocios':>8}{'cierres':>8}{'S(5a)':>8}   mediana"
    print(
        f"\nCategorías con más negocios (meets_min: >= {args.min_businesses} negocios y >= {args.min_events} cierres):"
    )
    print(cabecera)
    grandes = sorted((d for d in por_categoria if d["meets_min"]), key=lambda d: d["n_businesses"], reverse=True)[:12]
    for d in grandes:
        print(fila(d))
    print("\nZonas (polígonos consultados con $geoWithin):")
    print(cabecera)
    for d in sorted(por_zona, key=lambda d: d["n_businesses"], reverse=True):
        print(fila(d))
    print(
        f"\n¡Listo! business_survival ({len(docs)}), survival_by_category ({len(por_categoria)}), "
        f"zones ({len(zonas)}) y survival_by_zone ({len(por_zona)}) guardadas"
    )


if __name__ == "__main__":
    run()
