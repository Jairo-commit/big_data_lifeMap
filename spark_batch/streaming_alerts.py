"""Entrega 2, punto 7: alertas de riesgo de cierre en streaming (Kafka -> Spark Structured Streaming -> MongoDB).

Lee las reseñas del topic `reviews` y, con `foreachBatch`, en cada micro-lote:

1. **Actualiza las variables** de riesgo de los negocios que recibieron reseñas (alerts_logic.features_at): las seis
   variables del modelo (sentimiento medio, tendencia del % negativo en 6 meses, estrellas medias, número de reseñas,
   edad y competidores a 500 m) al instante de su última reseña, solo con reseñas de fecha <= t. La parte anterior a T
   sale de `risk_features`; la posterior, de las reseñas que llegan por Kafka y se guardan por negocio en `alert_state`
   (por `review_id`: repetir un lote no las cuenta dos veces).
2. **Los puntúa** con el modelo de riesgo (`risk_best`, el PipelineModel de risk_model.py, sin reentrenar).
3. **Guarda en `alerts`**, con su geometría (el Point del negocio), la probabilidad y la fecha del evento, los que
   superan el umbral (el que eligió el entrenamiento, en `model_metrics`; --threshold lo anula). Un negocio es un
   documento: si ya estaba en alerta se actualiza y si baja del umbral se marca `active = false`.
4. Guarda el avance (offsets procesados por partición) en `stream_progress`: de ahí sale el retraso del consumidor que
   informa /health de la API.

Solo se evalúan los negocios de la población del modelo (existían en T); los demás se cuentan y se ignoran.

Uso:
    docker compose --profile jobs run --rm spark-jobs spark-submit /app/streaming_alerts.py \\
        [--reset] [--timeout 600] [--threshold 0.65]
"""

import argparse
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone

from pyspark.ml import PipelineModel
from pyspark.ml.functions import vector_to_array
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, LongType, StructField, StructType

from alerts_logic import (
    alert_action,
    build_alert,
    features_at,
    latest_date,
    merge_reviews,
    next_offsets,
)
from geo_windows import parse_day
from lifemap_common import (
    CHECKPOINTS_DIR,
    CUTOFF_DATE,
    DB_NAME,
    KAFKA_BOOTSTRAP,
    KAFKA_TOPIC,
    MODELS_DIR,
    MONGO_URI,
    build_spark,
)
from risk_logic import FEATURES, add_months
from streaming_inference import read_reviews

PROGRESS_ID = "streaming_alerts"
CHUNK = 5000  # ids por consulta $in


def parse_args():
    parser = argparse.ArgumentParser(description="Alertas de riesgo de cierre sobre el topic de Kafka")
    parser.add_argument("--model", default=f"{MODELS_DIR}/risk_best", help="ruta del PipelineModel de riesgo")
    parser.add_argument(
        "--threshold", type=float, default=None, help="umbral de probabilidad (por defecto, el del modelo)"
    )
    parser.add_argument("--topic", default=KAFKA_TOPIC)
    parser.add_argument("--bootstrap", default=KAFKA_BOOTSTRAP)
    parser.add_argument(
        "--starting-offsets",
        default="earliest",
        help="earliest o latest; solo cuenta la primera vez (luego manda el checkpoint)",
    )
    parser.add_argument("--trigger-seconds", type=int, default=10, help="segundos entre micro-lotes")
    parser.add_argument("--max-offsets", type=int, default=20000, help="máximo de mensajes por micro-lote")
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="segundos que corre antes de detenerse (por defecto, hasta que se detenga)",
    )
    parser.add_argument("--checkpoint", default=f"{CHECKPOINTS_DIR}/streaming_alerts")
    parser.add_argument(
        "--reset", action="store_true", help="borra el checkpoint, las alertas y el estado y vuelve a leer el topic"
    )
    return parser.parse_args()


def get_db():
    from pymongo import MongoClient

    return MongoClient(MONGO_URI)[DB_NAME]


def chunked(items, size=CHUNK):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def load_threshold(db, args):
    """Umbral de alerta: el argumento o el que eligió el entrenamiento (máx. F1 en validación)."""
    if args.threshold is not None:
        return args.threshold, "argumento"
    risk = db.model_metrics.find_one({"_id": "risk"}, {"umbral": 1})
    if not risk or risk.get("umbral") is None:
        raise SystemExit("No hay umbral: falta model_metrics (_id risk); ejecuta risk_model.py o usa --threshold")
    return risk["umbral"], "model_metrics"


def ensure_indexes(db):
    from pymongo import ASCENDING, DESCENDING, GEOSPHERE

    db.alerts.create_index([("geometry", GEOSPHERE)])
    db.alerts.create_index([("active", ASCENDING), ("probability", DESCENDING)])
    db.alerts.create_index([("alert_date", ASCENDING)])


def score_features(spark, model, feature_rows):
    """Probabilidad de cierre de cada fila de variables (lista de dicts con las seis variables), en el mismo orden."""
    if not feature_rows:
        return []
    schema = StructType([StructField("i", LongType())] + [StructField(name, DoubleType()) for name in FEATURES])
    filas = [(i,) + tuple(float(row[name]) for name in FEATURES) for i, row in enumerate(feature_rows)]
    df = spark.createDataFrame(filas, schema)
    puntuado = model.transform(df).select("i", vector_to_array("probability")[1].alias("p")).orderBy("i")
    return [fila["p"] for fila in puntuado.collect()]


def make_batch_writer(spark, db, model, threshold):
    from pymongo import ReplaceOne

    cutoff = parse_day(CUTOFF_DATE)
    window_start = add_months(cutoff, -6)  # las reseñas < T que pueden caer en la tendencia de 6 meses

    def write_batch(batch_df, batch_id):
        rows = [
            fila.asDict()
            for fila in batch_df.select(
                "review_id",
                "business_id",
                "stars",
                F.to_timestamp("date").alias("date"),
                "kafka_partition",
                "kafka_offset",
            ).collect()
        ]
        if not rows:
            return

        nuevas = defaultdict(list)
        for r in rows:
            nuevas[r["business_id"]].append([r["review_id"], r["date"], float(r["stars"])])
        ids = list(nuevas)

        # 1) variables a T (risk_features) y estado acumulado de los negocios del lote
        base = {}
        for grupo in chunked(ids):
            for doc in db.risk_features.find({"_id": {"$in": grupo}}):
                base[doc["_id"]] = doc
        evaluados = [i for i in ids if i in base]
        estado, alertas = {}, {}
        for grupo in chunked(evaluados):
            for doc in db.alert_state.find({"_id": {"$in": grupo}}):
                estado[doc["_id"]] = doc.get("reviews", [])
            for doc in db.alerts.find({"_id": {"$in": grupo}}):
                alertas[doc["_id"]] = doc
        previas = defaultdict(list)
        for grupo in chunked(evaluados):
            consulta = {"business_id": {"$in": grupo}, "date": {"$gte": window_start, "$lt": cutoff}}
            for doc in db.reviews.find(consulta, {"business_id": 1, "date": 1, "stars": 1}):
                previas[doc["business_id"]].append((doc["date"], doc["stars"]))
        riesgo_a_t = {}
        for grupo in chunked(evaluados):
            for doc in db.risk_scores.find({"_id": {"$in": grupo}}, {"risk_probability": 1}):
                riesgo_a_t[doc["_id"]] = doc["risk_probability"]

        # 2) variables al instante t de cada negocio (su reseña más reciente)
        fusionadas, instantes, variables = {}, {}, {}
        for bid in evaluados:
            fusionadas[bid] = merge_reviews(estado.get(bid, []), nuevas[bid])
            instantes[bid] = latest_date(fusionadas[bid])
            variables[bid] = features_at(base[bid], fusionadas[bid], previas.get(bid, []), instantes[bid])

        # 3) puntuación con el modelo de riesgo y decisión de alerta
        probabilidades = dict(zip(evaluados, score_features(spark, model, [variables[b] for b in evaluados])))
        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        cuentas = {"raise": 0, "keep": 0, "clear": 0}
        escrituras_alertas, escrituras_estado = [], []
        for bid in evaluados:
            p, t = probabilidades[bid], instantes[bid]
            accion = alert_action(p, threshold, alertas.get(bid))
            escrituras_estado.append(
                ReplaceOne(
                    {"_id": bid}, {"_id": bid, "reviews": fusionadas[bid], "t": t, "updated_at": ahora}, upsert=True
                )
            )
            if accion is None:
                continue
            cuentas[accion] += 1
            pre = dict(base[bid], risk_at_cutoff=riesgo_a_t.get(bid))
            doc = build_alert(accion, pre, variables[bid], p, threshold, t, alertas.get(bid), ahora)
            escrituras_alertas.append(ReplaceOne({"_id": bid}, doc, upsert=True))

        if escrituras_estado:
            db.alert_state.bulk_write(escrituras_estado, ordered=False)
        if escrituras_alertas:
            db.alerts.bulk_write(escrituras_alertas, ordered=False)

        # 4) avance del consumidor, de todas las reseñas del lote (también las de negocios que no se evalúan)
        progreso = db.stream_progress.find_one({"_id": PROGRESS_ID}) or {}
        db.stream_progress.replace_one(
            {"_id": PROGRESS_ID},
            {
                "_id": PROGRESS_ID,
                "topic": KAFKA_TOPIC,
                "partitions": next_offsets(
                    [(r["kafka_partition"], r["kafka_offset"]) for r in rows], progreso.get("partitions")
                ),
                "batch_id": batch_id,
                "reviews_processed": len(rows) + progreso.get("reviews_processed", 0),
                "updated_at": ahora,
            },
            upsert=True,
        )
        print(
            f"[lote {batch_id}] {len(rows)} reseñas de {len(ids)} negocios: {len(evaluados)} evaluados "
            f"({len(ids) - len(evaluados)} fuera de la población); alertas nuevas {cuentas['raise']}, "
            f"siguen {cuentas['keep']}, desactivadas {cuentas['clear']}",
            flush=True,
        )

    return write_batch


def run():
    args = parse_args()
    db = get_db()
    if args.reset:
        if os.path.exists(args.checkpoint):
            print(f"Borrando el checkpoint {args.checkpoint}")
            shutil.rmtree(args.checkpoint)
        print("Borrando alerts, alert_state y el avance (stream_progress)")
        db.alerts.delete_many({})
        db.alert_state.delete_many({})
        db.stream_progress.delete_one({"_id": PROGRESS_ID})

    threshold, origen = load_threshold(db, args)
    spark = build_spark("LifeMap-StreamingAlerts", shuffle_partitions=3)
    spark.sparkContext.setLogLevel("WARN")
    if not os.path.exists(os.path.join(args.model, "metadata")):
        raise SystemExit(f"No existe el modelo de riesgo en {args.model}: primero hay que ejecutar risk_model.py")
    print(f"Cargando el modelo de riesgo desde {args.model} (sin reentrenar)...")
    model = PipelineModel.load(args.model)
    ensure_indexes(db)

    consulta = (
        read_reviews(spark, args)
        .writeStream.foreachBatch(make_batch_writer(spark, db, model, threshold))
        .option("checkpointLocation", args.checkpoint)
        .trigger(processingTime=f"{args.trigger_seconds} seconds")
        .queryName("lifemap_streaming_alerts")
        .start()
    )
    print(
        f"Alertas de riesgo: probabilidad >= {threshold:.4f} (umbral: {origen}) sobre las reseñas desde T = {CUTOFF_DATE}; "
        f"resultados en {DB_NAME}.alerts"
    )
    consulta.awaitTermination(args.timeout)
    if consulta.isActive:
        print(f"Tiempo agotado ({args.timeout} s): deteniendo el streaming")
        consulta.stop()
    spark.stop()


if __name__ == "__main__":
    run()
