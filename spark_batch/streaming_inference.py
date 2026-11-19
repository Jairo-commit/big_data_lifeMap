"""Entrega 2: inferencia de sentimiento en streaming (Kafka -> Spark Structured Streaming -> MongoDB).

Lee las reseñas que publica kafka_streaming/producer.py en el topic `reviews`, carga el
PipelineModel guardado en la Entrega 1 (`sentiment_best`: limpieza + TF-IDF + clasificador) sin
reentrenarlo, clasifica cada reseña y la escribe en la colección `review_predictions`.

Decisiones clave:
- El modelo se carga una vez y solo se usa `transform`: todas sus etapas son sin estado, así que
  funcionan igual sobre un DataFrame en streaming.
- Cada micro-lote se escribe con foreachBatch como upsert por `_id = review_id`: si el job se
  reinicia y repite un lote (garantía at-least-once de Kafka + checkpoint), no hay duplicados.
- El checkpoint guarda los offsets de Kafka ya procesados: al reiniciar continúa donde iba.
- Usa la misma fecha de corte T (CUTOFF_DATE de lifemap_common) que el entrenamiento y el
  productor: descarta cualquier mensaje anterior a T, que el modelo ya vio al entrenar.

Uso:
    docker compose --profile jobs run --rm spark-jobs spark-submit /app/streaming_inference.py \\
        [--trigger-seconds 10] [--max-offsets 50000] [--timeout 600] [--reset] [--output-collection review_predictions]
"""

import argparse
import os
import shutil

from pyspark.ml import PipelineModel
from pyspark.ml.functions import vector_to_array
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

from lifemap_common import (
    CHECKPOINTS_DIR,
    CUTOFF_DATE,
    DB_NAME,
    KAFKA_BOOTSTRAP,
    KAFKA_TOPIC,
    MODELS_DIR,
    MONGO_URI,
    build_spark,
    sentiment_label,
    write_collection,
)

# Mismas clases que sentiment_model.py (etiqueta numérica -> nombre)
CLASES = {0: "negativo", 1: "neutral", 2: "positivo"}
OUTPUT_COLLECTION = "review_predictions"

# Esquema del JSON que publica el productor
REVIEW_SCHEMA = StructType([
    StructField("review_id", StringType()),
    StructField("business_id", StringType()),
    StructField("user_id", StringType()),
    StructField("stars", DoubleType()),
    StructField("text", StringType()),
    StructField("date", StringType()),
])


def parse_args():
    parser = argparse.ArgumentParser(description="Clasifica en streaming las reseñas del topic de Kafka")
    parser.add_argument("--model", default=f"{MODELS_DIR}/sentiment_best", help="ruta del PipelineModel")
    parser.add_argument("--topic", default=KAFKA_TOPIC)
    parser.add_argument("--bootstrap", default=KAFKA_BOOTSTRAP)
    parser.add_argument("--starting-offsets", default="earliest",
                        help="earliest o latest; solo cuenta la primera vez (luego manda el checkpoint)")
    parser.add_argument("--trigger-seconds", type=int, default=10, help="segundos entre micro-lotes")
    parser.add_argument("--max-offsets", type=int, default=50000, help="máximo de mensajes por micro-lote")
    parser.add_argument("--timeout", type=int, default=None,
                        help="segundos que corre antes de detenerse (por defecto, hasta que se detenga)")
    parser.add_argument("--output-collection", default=OUTPUT_COLLECTION,
                        help="colección donde se escriben las predicciones (la prueba de humo usa otra para no tocar las reales)")
    parser.add_argument("--checkpoint", default=f"{CHECKPOINTS_DIR}/streaming_inference")
    parser.add_argument("--reset", action="store_true",
                        help="borra el checkpoint y vuelve a leer el topic desde --starting-offsets")
    return parser.parse_args()


def load_model(path):
    """Carga el modelo de la Entrega 1; no se reentrena."""
    if not os.path.exists(os.path.join(path, "metadata")):
        raise SystemExit(f"No existe el modelo en {path}: primero hay que ejecutar sentiment_model.py")
    print(f"Cargando el modelo de sentimiento desde {path} (sin reentrenar)...")
    return PipelineModel.load(path)


def ensure_indexes(collection=OUTPUT_COLLECTION):
    from pymongo import ASCENDING, MongoClient

    coleccion = MongoClient(MONGO_URI)[DB_NAME][collection]
    for campo in ("business_id", "date", "sentiment"):
        coleccion.create_index([(campo, ASCENDING)])


def read_reviews(spark, args):
    """Stream de reseñas: JSON del valor de Kafka + metadatos (partición, offset, timestamp)."""
    crudo = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", args.bootstrap)
        .option("subscribe", args.topic)
        .option("startingOffsets", args.starting_offsets)
        .option("maxOffsetsPerTrigger", args.max_offsets)
        .option("failOnDataLoss", "false")
        .load()
    )
    return crudo.select(
        F.from_json(F.col("value").cast("string"), REVIEW_SCHEMA).alias("r"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        F.col("timestamp").alias("kafka_ts"),
    ).select("r.*", "kafka_partition", "kafka_offset", "kafka_ts").where(
        F.col("review_id").isNotNull() & F.col("text").isNotNull()
        # Solo reseñas desde T: las anteriores son datos de entrenamiento
        & (F.to_timestamp("date") >= F.lit(CUTOFF_DATE).cast("timestamp"))
    )


def classify(model, reviews):
    """Aplica el modelo y deja solo las columnas que se guardan en MongoDB."""
    nombres = F.create_map(*[x for etiqueta, nombre in CLASES.items() for x in (F.lit(float(etiqueta)), F.lit(nombre))])
    probabilidades = vector_to_array(F.col("probability"))
    etiqueta_real = sentiment_label(F.col("stars"))
    return model.transform(reviews).select(
        F.col("review_id").alias("_id"),
        "review_id",
        "business_id",
        "user_id",
        "stars",
        F.to_timestamp("date").alias("date"),
        nombres[F.col("prediction")].alias("sentiment"),
        F.col("prediction").cast("int").alias("prediction"),
        F.struct(*[probabilidades[i].alias(nombre) for i, nombre in CLASES.items()]).alias("probabilities"),
        nombres[etiqueta_real].alias("true_sentiment"),
        (F.col("prediction") == etiqueta_real).alias("correct"),
        "kafka_partition",
        "kafka_offset",
        "kafka_ts",
        F.current_timestamp().alias("processed_at"),
    )


def write_batch(batch_df, batch_id, collection=OUTPUT_COLLECTION):
    """Upsert del micro-lote en MongoDB (por _id = review_id) y resumen por consola."""
    batch_df = batch_df.persist()
    total = batch_df.count()
    if total:
        write_collection(batch_df, collection, mode="append", operationType="replace", upsertDocument="true")
        resumen = batch_df.groupBy("sentiment").count().collect()
        aciertos = batch_df.where("correct").count()
        fechas = batch_df.agg(F.min("date").alias("desde"), F.max("date").alias("hasta")).first()
        por_clase = ", ".join(f"{r['sentiment']}={r['count']}" for r in sorted(resumen, key=lambda r: r["sentiment"]))
        print(f"[lote {batch_id}] {total} reseñas ({fechas['desde']} -> {fechas['hasta']}): {por_clase}; "
              f"coinciden con las estrellas {100 * aciertos / total:.1f} %", flush=True)
    batch_df.unpersist()


def run():
    args = parse_args()
    if args.reset and os.path.exists(args.checkpoint):
        print(f"Borrando el checkpoint {args.checkpoint}")
        shutil.rmtree(args.checkpoint)

    spark = build_spark("LifeMap-StreamingInference", shuffle_partitions=3)
    spark.sparkContext.setLogLevel("WARN")
    model = load_model(args.model)
    ensure_indexes(args.output_collection)

    predicciones = classify(model, read_reviews(spark, args))
    consulta = (
        predicciones.writeStream.foreachBatch(lambda df, batch_id: write_batch(df, batch_id, args.output_collection))
        .option("checkpointLocation", args.checkpoint)
        .trigger(processingTime=f"{args.trigger_seconds} seconds")
        .queryName("lifemap_streaming_inference")
        .start()
    )
    print(f"Escuchando el topic '{args.topic}' en {args.bootstrap} (reseñas desde T = {CUTOFF_DATE}); "
          f"resultados en {DB_NAME}.{args.output_collection}")
    consulta.awaitTermination(args.timeout)
    if consulta.isActive:
        print(f"Tiempo agotado ({args.timeout} s): deteniendo el streaming")
        consulta.stop()
    spark.stop()


if __name__ == "__main__":
    run()
