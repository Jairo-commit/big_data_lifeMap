"""Entrega 2, punto 4: ventanas geoespaciales en streaming (Kafka -> Spark Structured Streaming -> MongoDB).

Lee las reseñas del topic `reviews`, las clasifica con el modelo `sentiment_best` (sin reentrenar), las
asigna a la celda de geohash de su negocio y las agrega en ventanas de 30 días:

- **Tiempo del evento**: las ventanas y el watermark usan el campo `date` de la reseña (cuándo se escribió),
  no el momento en que llega a Kafka o a Spark.
- **Watermark de 7 días**: Spark espera hasta 7 días de retraso sobre la fecha más reciente vista; una ventana
  se cierra (y se emite) cuando el watermark pasa de su fin, y lo que llegue más tarde se descarta. El
  estado en memoria queda acotado.
- **Alineación con T**: las ventanas empiezan en T (`geo_windows.window_offset_days`), el mismo reloj del
  productor: con "un mes cada 10 segundos" cada 10 s se cierra aproximadamente una ventana (más los 7 días).
- **Sin duplicados**: `dropDuplicates(review_id)` dentro del watermark; si el productor se ejecuta otra vez,
  las reseñas repetidas no se cuentan dos veces.
- Modo `append`: solo se emiten ventanas cerradas, con su valor definitivo. Las últimas ventanas de la
  transmisión no se cierran hasta que llegue una reseña posterior que adelante el watermark.

Cada ventana cerrada se guarda en `geohash_windows` con el conteo y el porcentaje de reseñas negativas, la
geometría de su celda y la decisión de hotspot (ver geo_windows.hotspot_decision). El umbral sale de
`hotspot_config` (lo calcula calibrate_hotspots.py con el histórico) o de --threshold.

Uso:
    docker compose --profile jobs run --rm spark-jobs spark-submit /app/streaming_windows.py \\
        [--timeout 600] [--reset] [--threshold 20] [--min-reviews 20]
"""

import argparse
import os
import shutil

from pyspark.sql import functions as F

from geo_windows import (
    DEFAULT_MIN_REVIEWS,
    DEFAULT_WATERMARK_DAYS,
    DEFAULT_WINDOW_DAYS,
    FALLBACK_THRESHOLD_PP,
    build_window_docs,
    missing_previous_ids,
    window_offset_days,
)
from lifemap_common import (
    CHECKPOINTS_DIR,
    CUTOFF_DATE,
    DB_NAME,
    KAFKA_BOOTSTRAP,
    KAFKA_TOPIC,
    MODELS_DIR,
    MONGO_URI,
    build_spark,
    load_businesses,
)
from streaming_inference import classify, load_model, read_reviews

OUTPUT_COLLECTION = "geohash_windows"


def parse_args():
    parser = argparse.ArgumentParser(description="Ventanas de 30 días por celda de geohash sobre el topic de Kafka")
    parser.add_argument("--model", default=f"{MODELS_DIR}/sentiment_best", help="ruta del PipelineModel")
    parser.add_argument("--topic", default=KAFKA_TOPIC)
    parser.add_argument("--bootstrap", default=KAFKA_BOOTSTRAP)
    parser.add_argument(
        "--starting-offsets",
        default="earliest",
        help="earliest o latest; solo cuenta la primera vez (luego manda el checkpoint)",
    )
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--watermark-days", type=int, default=DEFAULT_WATERMARK_DAYS)
    parser.add_argument(
        "--min-reviews",
        type=int,
        default=None,
        help="reseñas mínimas por ventana para evaluar hotspot (por defecto, el de hotspot_config)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="umbral de hotspot en puntos porcentuales (por defecto, el de hotspot_config)",
    )
    parser.add_argument("--trigger-seconds", type=int, default=10, help="segundos entre micro-lotes")
    parser.add_argument("--max-offsets", type=int, default=50000, help="máximo de mensajes por micro-lote")
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="segundos que corre antes de detenerse (por defecto, hasta que se detenga)",
    )
    parser.add_argument("--checkpoint", default=f"{CHECKPOINTS_DIR}/streaming_windows")
    parser.add_argument(
        "--reset", action="store_true", help="borra el checkpoint y las ventanas guardadas y vuelve a leer el topic"
    )
    return parser.parse_args()


def get_collection():
    from pymongo import MongoClient

    return MongoClient(MONGO_URI)[DB_NAME][OUTPUT_COLLECTION]


def hotspot_settings(args):
    """Umbral y mínimo de reseñas: los argumentos mandan; si no, hotspot_config; si no, los valores por defecto."""
    from pymongo import MongoClient

    config = MongoClient(MONGO_URI)[DB_NAME].hotspot_config.find_one({"_id": "hotspot"}) or {}
    threshold = args.threshold if args.threshold is not None else config.get("threshold_pp")
    origen = "argumento" if args.threshold is not None else "hotspot_config"
    if threshold is None:
        threshold, origen = FALLBACK_THRESHOLD_PP, "valor por defecto (falta calibrate_hotspots.py)"
    min_reviews = args.min_reviews if args.min_reviews is not None else config.get("min_reviews", DEFAULT_MIN_REVIEWS)
    return threshold, min_reviews, origen


def ensure_indexes(collection):
    from pymongo import ASCENDING, GEOSPHERE

    collection.create_index([("geometry", GEOSPHERE)])
    collection.create_index([("geohash", ASCENDING), ("window_start", ASCENDING)])
    collection.create_index([("is_hotspot", ASCENDING), ("window_start", ASCENDING)])


def build_windows(model, spark, args):
    """Stream de ventanas cerradas por celda: clasifica, asigna celda, watermark y agregación."""
    reseñas = classify(model, read_reviews(spark, args))
    celdas = F.broadcast(load_businesses(spark).select("business_id", "geohash").cache())
    offset = window_offset_days(CUTOFF_DATE, args.window_days)
    ventana = F.window("date", f"{args.window_days} days", f"{args.window_days} days", f"{offset} days")

    agregado = (
        reseñas.join(celdas, "business_id")
        .withWatermark("date", f"{args.watermark_days} days")
        .dropDuplicates(["review_id", "date"])
        .groupBy(ventana.alias("window"), "geohash")
        .agg(
            F.count("*").alias("n_reviews"),
            F.sum((F.col("sentiment") == "negativo").cast("int")).alias("n_negative"),
            F.sum((F.col("sentiment") == "neutral").cast("int")).alias("n_neutral"),
            F.sum((F.col("sentiment") == "positivo").cast("int")).alias("n_positive"),
            F.sum((F.col("stars") <= 2).cast("int")).alias("n_negative_stars"),
        )
    )
    return agregado.select(
        "geohash",
        F.unix_timestamp(F.col("window.start")).alias("window_start"),
        F.unix_timestamp(F.col("window.end")).alias("window_end"),
        "n_reviews",
        "n_negative",
        "n_neutral",
        "n_positive",
        "n_negative_stars",
    )


def make_batch_writer(collection, threshold, min_reviews, window_days):
    from pymongo import ReplaceOne

    def write_batch(batch_df, batch_id):
        filas = [fila.asDict() for fila in batch_df.collect()]
        if not filas:
            return
        faltan = missing_previous_ids(filas, window_days)
        guardadas = {}
        if faltan:
            proyeccion = {"n_reviews": 1, "pct_negative": 1}
            guardadas = {d["_id"]: d for d in collection.find({"_id": {"$in": list(faltan)}}, proyeccion)}
        docs = build_window_docs(filas, guardadas, threshold, min_reviews, window_days)
        collection.bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs], ordered=False)

        hotspots = sum(1 for d in docs if d["is_hotspot"])
        print(
            f"[lote {batch_id}] {len(docs)} ventanas cerradas ({docs[0]['window_start']:%Y-%m-%d} -> "
            f"{docs[-1]['window_start']:%Y-%m-%d}), {sum(d['n_reviews'] for d in docs)} reseñas, "
            f"{hotspots} hotspots",
            flush=True,
        )

    return write_batch


def run():
    args = parse_args()
    collection = get_collection()
    if args.reset:
        if os.path.exists(args.checkpoint):
            print(f"Borrando el checkpoint {args.checkpoint}")
            shutil.rmtree(args.checkpoint)
        print(f"Borrando las ventanas guardadas en {OUTPUT_COLLECTION}")
        collection.delete_many({})

    threshold, min_reviews, origen = hotspot_settings(args)
    spark = build_spark("LifeMap-StreamingWindows", shuffle_partitions=3)
    spark.sparkContext.setLogLevel("WARN")
    model = load_model(args.model)
    ensure_indexes(collection)

    consulta = (
        build_windows(model, spark, args)
        .writeStream.outputMode("append")
        .foreachBatch(make_batch_writer(collection, threshold, min_reviews, args.window_days))
        .option("checkpointLocation", args.checkpoint)
        .trigger(processingTime=f"{args.trigger_seconds} seconds")
        .queryName("lifemap_streaming_windows")
        .start()
    )
    print(
        f"Ventanas de {args.window_days} días por celda de geohash, watermark de {args.watermark_days} días sobre "
        f"`date` (tiempo del evento), desde T = {CUTOFF_DATE}"
    )
    print(
        f"Hotspot: sube >= {threshold:.2f} puntos frente a la ventana anterior, con >= {min_reviews} reseñas "
        f"en ambas (umbral: {origen}); resultados en {DB_NAME}.{OUTPUT_COLLECTION}"
    )
    consulta.awaitTermination(args.timeout)
    if consulta.isActive:
        print(f"Tiempo agotado ({args.timeout} s): deteniendo el streaming")
        consulta.stop()
    spark.stop()


if __name__ == "__main__":
    run()
