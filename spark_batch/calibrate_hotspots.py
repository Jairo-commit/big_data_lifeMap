"""Entrega 2, punto 4: calibra con datos el umbral de hotspot de las ventanas geoespaciales.

La guía pide que una celda sea hotspot "cuando su porcentaje negativo sube frente a la ventana anterior
por encima de un umbral que el equipo justifica". En vez de elegirlo a ojo, se mide qué tanto cambia
normalmente el porcentaje de reseñas negativas de una celda de un mes al siguiente en el histórico y se
toma como umbral el percentil 95 de esas variaciones: un hotspot es una subida que solo ocurre 1 de cada
20 veces en condiciones normales.

- Usa solo las reseñas anteriores a T (CUTOFF_DATE): las posteriores son el flujo que se evaluará.
- Ventanas de 30 días alineadas con T hacia atrás ([T-30d, T), [T-60d, T-30d)...) y por celda de geohash,
  las mismas que arma el streaming.
- Negativa = 1 o 2 estrellas (la regla de las etiquetas del modelo). El histórico no tiene predicciones
  del modelo, así que la calibración usa las estrellas; el streaming usa las predicciones, que coinciden
  con ellas en ~83 % de los casos, y guarda también las negativas por estrellas para poder compararlas.
- Solo cuentan los pares de ventanas consecutivas donde ambas tienen al menos --min-reviews reseñas.
- Guarda el resultado en `hotspot_config`, que lee streaming_windows.py.

Uso:
    docker compose --profile jobs run --rm spark-jobs spark-submit /app/calibrate_hotspots.py \\
        [--window-days 30] [--min-reviews 20] [--quantile 0.95]
"""

import argparse
from datetime import datetime, timezone

from pyspark.sql import functions as F

from geo_windows import (
    DEFAULT_MIN_REVIEWS,
    DEFAULT_QUANTILE,
    DEFAULT_WINDOW_DAYS,
    calibrate_threshold,
    standard_error_pp,
    summarize_deltas,
)
from lifemap_common import CUTOFF_DATE, DB_NAME, MONGO_URI, build_spark, load_businesses, read_collection


def parse_args():
    parser = argparse.ArgumentParser(description="Calibra el umbral de hotspot con el histórico anterior a T")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--min-reviews",
        type=int,
        default=DEFAULT_MIN_REVIEWS,
        help="reseñas mínimas en cada una de las dos ventanas que se comparan",
    )
    parser.add_argument(
        "--quantile",
        type=float,
        default=DEFAULT_QUANTILE,
        help="cuantil de las variaciones que se usa como umbral (0,95 = percentil 95)",
    )
    return parser.parse_args()


def window_deltas(spark, window_days, min_reviews):
    """Variaciones (en puntos) del % negativo de una celda entre dos ventanas consecutivas anteriores a T."""
    negocios = load_businesses(spark).select("business_id", "geohash")
    cutoff = F.lit(CUTOFF_DATE).cast("timestamp")
    fecha = F.col("date").cast("timestamp")

    resenas = (
        read_collection(spark, "reviews")
        .select("business_id", "stars", fecha.alias("date"))
        .where(F.col("stars").isNotNull() & (fecha < cutoff))
    )
    # k = -1 es [T - 30 días, T), k = -2 la anterior...: las ventanas quedan alineadas con T
    k = F.floor((F.unix_timestamp("date") - F.unix_timestamp(cutoff)) / (window_days * 86400)).cast("int")
    celdas = (
        resenas.join(F.broadcast(negocios), "business_id")
        .groupBy("geohash", k.alias("k"))
        .agg(F.count("*").alias("n"), F.sum((F.col("stars") <= 2).cast("int")).alias("negativas"))
        .where(F.col("n") >= min_reviews)
        .withColumn("pct", F.col("negativas") / F.col("n") * 100)
        .cache()
    )
    anterior = celdas.select("geohash", (F.col("k") + 1).alias("k"), F.col("pct").alias("prev_pct"))
    pares = celdas.join(anterior, ["geohash", "k"]).select((F.col("pct") - F.col("prev_pct")).alias("delta"))

    deltas = [fila["delta"] for fila in pares.collect()]
    resumen_celdas = celdas.agg(
        F.countDistinct("geohash").alias("celdas"), F.count("*").alias("ventanas_con_minimo")
    ).first()
    celdas.unpersist()
    return deltas, resumen_celdas


def run():
    args = parse_args()
    spark = build_spark("LifeMap-CalibrateHotspots")
    spark.sparkContext.setLogLevel("WARN")

    print(
        f"Reseñas anteriores a T = {CUTOFF_DATE}; ventanas de {args.window_days} días; "
        f"mínimo {args.min_reviews} reseñas por ventana"
    )
    deltas, celdas = window_deltas(spark, args.window_days, args.min_reviews)
    if not deltas:
        raise SystemExit("No hay pares de ventanas consecutivas con reseñas suficientes: no se puede calibrar")

    resumen = summarize_deltas(deltas)
    umbral = calibrate_threshold(deltas, args.quantile)
    por_encima = sum(1 for d in deltas if d >= umbral) / len(deltas) * 100

    print(
        f"Celdas con al menos una ventana válida: {celdas['celdas']}; ventanas válidas: {celdas['ventanas_con_minimo']}"
    )
    print(f"Pares de ventanas consecutivas comparados: {resumen['n_pairs']}")
    print(
        f"Variación mes a mes del % negativo (puntos): media {resumen['mean']:+.2f}, desviación {resumen['std']:.2f}, "
        f"p50 {resumen['p50']:+.2f}, p90 {resumen['p90']:+.2f}, p95 {resumen['p95']:+.2f}, p99 {resumen['p99']:+.2f}"
    )
    print(
        f"=> Umbral de hotspot (percentil {args.quantile * 100:g}): {umbral:.2f} puntos "
        f"({por_encima:.2f} % de los pares históricos lo igualan o superan)"
    )
    print(
        f"   Con {args.min_reviews} reseñas el error estándar de un porcentaje llega a ±"
        f"{standard_error_pp(50, args.min_reviews):.1f} puntos: por debajo de ese volumen no se evalúa"
    )

    from pymongo import MongoClient

    config = {
        "_id": "hotspot",
        "threshold_pp": umbral,
        "quantile": args.quantile,
        "min_reviews": args.min_reviews,
        "window_days": args.window_days,
        "cutoff": CUTOFF_DATE,
        "calibrated_on": "reseñas con fecha < T; negativa = 1 o 2 estrellas",
        "distribution": resumen,
        "cells": celdas["celdas"],
        "windows_with_min_reviews": celdas["ventanas_con_minimo"],
        "calibrated_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    MongoClient(MONGO_URI)[DB_NAME].hotspot_config.replace_one({"_id": "hotspot"}, config, upsert=True)
    print("¡Umbral guardado en hotspot_config!")
    spark.stop()


if __name__ == "__main__":
    run()
