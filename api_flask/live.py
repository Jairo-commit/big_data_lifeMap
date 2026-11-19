"""Entrega 2, punto 8: consultas y formato de los endpoints nuevos de la API (hotspots, alertas, supervivencia, riesgo).

Solo usa la biblioteca estándar: se prueba con pytest sin MongoDB, Flask ni Kafka (tests/test_api_live.py).
Compatible con Python 3.8 (el de la imagen de Spark).

Los endpoints devuelven JSON con listas de filas planas y, con `?format=csv`, esas mismas filas en CSV: es lo que
consume Power BI (powerbi/). Las fechas salen siempre en ISO 8601.
"""

import csv
import io
from datetime import date, datetime

from queries import EARTH_RADIUS_M, BadRequest, geojson_point, parse_float

FORMATS = ("json", "csv")
STATES = ("active", "cleared", "all")
SURVIVAL_KINDS = {"category": "survival_by_category", "zone": "survival_by_zone"}


# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------


def parse_format(args):
    value = (args.get("format") or "json").strip().lower()
    if value not in FORMATS:
        raise BadRequest(f"'format' debe ser uno de: {', '.join(FORMATS)}")
    return value


def parse_window(args):
    """`window`: 'latest' (la ventana cerrada más reciente) o la fecha de inicio YYYY-MM-DD. Devuelve None o un datetime."""
    raw = (args.get("window") or "latest").strip()
    if raw.lower() == "latest":
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise BadRequest("'window' debe ser 'latest' o una fecha YYYY-MM-DD (inicio de la ventana)") from None


def parse_optional_circle(args, default_radius=5000.0, max_radius=50_000):
    """(lon, lat, radio en m) si se dan lat y lon; None si no se da ninguno. Dar solo uno de los dos es un error."""
    has_lat, has_lon = bool(args.get("lat")), bool(args.get("lon"))
    if not has_lat and not has_lon:
        return None
    if has_lat != has_lon:
        raise BadRequest("'lat' y 'lon' van juntos: falta uno de los dos")
    lat = parse_float(args, "lat", minimum=-90, maximum=90)
    lon = parse_float(args, "lon", minimum=-180, maximum=180)
    radius = parse_float(args, "radius", default=default_radius, minimum=1, maximum=max_radius)
    return lon, lat, radius


def parse_state(args):
    value = (args.get("state") or "active").strip().lower()
    if value not in STATES:
        raise BadRequest(f"'state' debe ser uno de: {', '.join(STATES)}")
    return value


def parse_survival_kind(args):
    value = (args.get("by") or "category").strip().lower()
    if value not in SURVIVAL_KINDS:
        raise BadRequest(f"'by' debe ser uno de: {', '.join(SURVIVAL_KINDS)}")
    return value


# ---------------------------------------------------------------------------
# Filtros geoespaciales
# ---------------------------------------------------------------------------


def circle_filter(field, circle):
    """$geoWithin con $centerSphere (radio en radianes = metros / radio de la Tierra) sobre un campo GeoJSON."""
    lon, lat, radius = circle
    return {field: {"$geoWithin": {"$centerSphere": [[lon, lat], radius / EARTH_RADIUS_M]}}}


def hotspots_query(window_start, circle=None):
    """Ventanas de `geohash_windows` que son hotspot, en una ventana y (opcional) dentro de un radio."""
    query = {"is_hotspot": True, "window_start": window_start}
    if circle:
        query.update(circle_filter("centroid", circle))
    return query


def windows_in_circle_query(circle=None):
    return circle_filter("centroid", circle) if circle else {}


def alerts_query(state="active", min_probability=0.0, circle=None, geometry=None):
    """Alertas de `alerts` por estado, probabilidad mínima y zona (un radio o un polígono GeoJSON)."""
    query = {}
    if state == "active":
        query["active"] = True
    elif state == "cleared":
        query["active"] = False
    if min_probability:
        query["probability"] = {"$gte": min_probability}
    if circle:
        query.update(circle_filter("geometry", circle))
    elif geometry:
        query["geometry"] = {"$geoWithin": {"$geometry": geometry}}
    return query


def risk_near_query(lon, lat, radius_m, min_probability=0.0):
    """Negocios de `risk_scores` a menos de radius_m metros del punto, del más cercano al más lejano ($near)."""
    query = {"location": {"$near": {"$geometry": geojson_point(lon, lat), "$maxDistance": radius_m}}}
    if min_probability:
        query["risk_probability"] = {"$gte": min_probability}
    return query


def evolution_pipeline(circle=None):
    """% negativo por ventana, sumando las celdas (dentro de un radio, si se da)."""
    pipeline = []
    match = windows_in_circle_query(circle)
    if match:
        pipeline.append({"$match": match})
    pipeline += [
        {
            "$group": {
                "_id": "$window_start",
                "window_end": {"$first": "$window_end"},
                "n_cells": {"$sum": 1},
                "n_reviews": {"$sum": "$n_reviews"},
                "n_negative": {"$sum": "$n_negative"},
                "n_negative_stars": {"$sum": "$n_negative_stars"},
                "n_hotspots": {"$sum": {"$cond": ["$is_hotspot", 1, 0]}},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    return pipeline


# ---------------------------------------------------------------------------
# Filas planas (las que consume Power BI)
# ---------------------------------------------------------------------------


def iso(value):
    """datetime/date -> ISO 8601; el resto, igual."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _coords(point):
    coordinates = (point or {}).get("coordinates") or [None, None]
    return coordinates[1], coordinates[0]  # lat, lon


def hotspot_row(doc):
    lat, lon = _coords(doc.get("centroid"))
    return {
        "geohash": doc.get("geohash"),
        "window_start": iso(doc.get("window_start")),
        "window_end": iso(doc.get("window_end")),
        "n_reviews": doc.get("n_reviews"),
        "n_negative": doc.get("n_negative"),
        "pct_negative": doc.get("pct_negative"),
        "prev_pct_negative": doc.get("prev_pct_negative"),
        "delta_pp": doc.get("delta_pp"),
        "threshold_pp": doc.get("threshold_pp"),
        "is_hotspot": doc.get("is_hotspot"),
        "lat": lat,
        "lon": lon,
    }


def evolution_row(group):
    n = group.get("n_reviews") or 0
    return {
        "window_start": iso(group["_id"]),
        "window_end": iso(group.get("window_end")),
        "n_cells": group.get("n_cells"),
        "n_reviews": n,
        "n_negative": group.get("n_negative"),
        "pct_negative": group["n_negative"] / n * 100 if n else None,
        "pct_negative_stars": group["n_negative_stars"] / n * 100 if n else None,
        "n_hotspots": group.get("n_hotspots"),
    }


def alert_row(doc):
    lat, lon = _coords(doc.get("geometry"))
    features = doc.get("features") or {}
    return {
        "business_id": doc.get("business_id"),
        "city": doc.get("city"),
        "primary_category": doc.get("primary_category"),
        "probability": doc.get("probability"),
        "threshold": doc.get("threshold"),
        "active": doc.get("active"),
        "alert_date": iso(doc.get("alert_date")),
        "first_alert_date": iso(doc.get("first_alert_date")),
        "cleared_date": iso(doc.get("cleared_date")),
        "risk_at_cutoff": doc.get("risk_at_cutoff"),
        "n_updates": doc.get("n_updates"),
        "lat": lat,
        "lon": lon,
        "mean_sentiment": features.get("mean_sentiment"),
        "neg_trend_6m": features.get("neg_trend_6m"),
        "stars_mean": features.get("stars_mean"),
        "n_reviews": features.get("n_reviews"),
        "age_days": features.get("age_days"),
        "competitors_500m": features.get("competitors_500m"),
    }


def risk_row(doc):
    lat, lon = _coords(doc.get("location"))
    features = doc.get("features") or {}
    return {
        "business_id": doc.get("business_id"),
        "city": doc.get("city"),
        "primary_category": doc.get("primary_category"),
        "risk_probability": doc.get("risk_probability"),
        "risk_flag": doc.get("risk_flag"),
        "threshold": doc.get("threshold"),
        "model": doc.get("model"),
        "lat": lat,
        "lon": lon,
        "mean_sentiment": features.get("mean_sentiment"),
        "neg_trend_6m": features.get("neg_trend_6m"),
        "stars_mean": features.get("stars_mean"),
        "n_reviews": features.get("n_reviews"),
        "age_days": features.get("age_days"),
        "competitors_500m": features.get("competitors_500m"),
    }


SURVIVAL_SUMMARY_FIELDS = (
    "group",
    "kind",
    "n_businesses",
    "n_events",
    "n_censored",
    "n_late_entry",
    "median_days",
    "median_years",
    "meets_min",
    "survival_1y",
    "survival_3y",
    "survival_5y",
    "survival_10y",
)


def survival_summary(doc):
    summary = {name: doc.get(name) for name in SURVIVAL_SUMMARY_FIELDS}
    summary["window_start"] = iso(doc.get("window_start"))
    return summary


def survival_curve_rows(doc):
    """Una fila por instante con cierres: tiempo en días y en años, en riesgo, cierres, censurados, S(t) y su IC 95 %."""
    names = doc.get("curve_fields") or []
    rows = []
    for point in doc.get("curve") or []:
        row = dict(zip(names, point))
        row["t_years"] = row["t"] / 365.25 if row.get("t") is not None else None
        rows.append({"group": doc.get("group"), "kind": doc.get("kind"), **row})
    return rows


# ---------------------------------------------------------------------------
# Columnas de cada tabla (el CSV lleva siempre su encabezado, aunque no haya filas: Power BI lo necesita)
# ---------------------------------------------------------------------------

HOTSPOT_COLUMNS = list(hotspot_row({}))
EVOLUTION_COLUMNS = [
    "window_start",
    "window_end",
    "n_cells",
    "n_reviews",
    "n_negative",
    "pct_negative",
    "pct_negative_stars",
    "n_hotspots",
]
ALERT_COLUMNS = list(alert_row({}))
RISK_COLUMNS = list(risk_row({})) + ["distance_m"]
SURVIVAL_GROUP_COLUMNS = list(SURVIVAL_SUMMARY_FIELDS) + ["window_start"]
CURVE_COLUMNS = ["group", "kind", "t", "t_years", "n_risk", "n_events", "n_censored", "survival", "ci_low", "ci_high"]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def to_csv(rows, fields=None):
    """Filas (dicts) a texto CSV con encabezado; None sale vacío y las fechas en ISO. Sin filas, solo el encabezado."""
    fields = list(fields or (rows[0].keys() if rows else []))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else iso(row.get(k))) for k in fields})
    return out.getvalue()


# ---------------------------------------------------------------------------
# Retraso del consumidor
# ---------------------------------------------------------------------------


def lag_by_partition(end_offsets, next_offsets):
    """Retraso por partición = offset final del topic - siguiente offset a procesar (nunca negativo).

    `end_offsets` y `next_offsets` son {partición: offset}. Devuelve {"partitions": {...}, "total": n} o None si el
    consumidor no ha dejado ningún avance (no se sabe cuánto lleva).
    """
    if not next_offsets:
        return None
    lags = {}
    for partition, end in end_offsets.items():
        lags[str(partition)] = max(end - next_offsets.get(str(partition), 0), 0)
    return {"partitions": lags, "total": sum(lags.values())}
