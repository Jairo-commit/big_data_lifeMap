"""Entrega 2, punto 6: modelo de riesgo de cierre de negocios (el patrón de KafkaMed aplicado a negocios).

Con los datos **anteriores a T** (CUTOFF_DATE) se construyen variables por negocio y se entrena un clasificador
que estima la probabilidad de que el negocio cierre en los 12 meses siguientes a T.

Población y etiqueta (risk_logic): negocios que existían en T y tuvieron actividad desde T; etiqueta 1 si el
negocio está cerrado y su última reseña cae entre T y T + 12 meses, 0 si sigue con actividad después de ese
plazo o sigue abierto. Los negocios sin actividad después de T se excluyen.

Variables (solo con reseñas < T; no se usan `stars` ni `review_count` del negocio porque son los del corte del
dataset e incluirían el futuro): sentimiento medio, tendencia del % negativo en los últimos 6 meses, estrellas
medias, número de reseñas, edad en T y densidad de competidores de la misma categoría a 500 m (con $geoNear).

Modelo: partición 60/20/20 **por negocio**; regresión logística y GBT con pesos de clase (el cierre es la clase
rara); se elige por AUC-PR en validación; el umbral maximiza el F1 en validación. En prueba se reportan AUC-ROC,
AUC-PR (frente a la prevalencia, que es lo que lograría un modelo sin información) y recall, precision y matriz de
confusión en ese umbral. Como control anti-fuga, un modelo entrenado con las etiquetas barajadas debe dar un
AUC-ROC cercano a 0,5.

Resultados: `risk_features` (variables por negocio), `risk_scores` (probabilidad de cierre y alerta, con la
ubicación), `model_metrics` (_id "risk") y los modelos en /app/models (risk_best, risk_logistic_regression,
risk_gbt).

Uso:
    docker compose --profile jobs run --rm spark-jobs spark-submit /app/risk_model.py [--threads 16] [--no-sanity] [--shuffles 10] [--from-features]
"""

import argparse
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from pyspark.ml import Pipeline
from pyspark.ml.classification import GBTClassifier, LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StandardScaler, VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

from geo_windows import from_epoch_seconds, parse_day
from lifemap_common import (
    CUTOFF_DATE,
    DB_NAME,
    MODELS_DIR,
    MONGO_URI,
    OUTPUT_DIR,
    build_spark,
    read_collection,
)
from risk_logic import (
    COMPETITOR_RADIUS_M,
    FEATURES,
    HORIZON_MONTHS,
    TREND_HALF_MONTHS,
    add_months,
    choose_threshold,
    competitors_pipeline,
    in_population,
    mean_sentiment,
    metrics_at_threshold,
    negative_trend,
    prevalence,
    risk_label,
)
from survival import primary_category

TRAIN_PERCENT, VALID_PERCENT = 60, 20  # el resto (20 %) es prueba; el reparto sale del hash del business_id


def parse_args():
    parser = argparse.ArgumentParser(description="Modelo de riesgo de cierre de negocios")
    parser.add_argument("--threads", type=int, default=16, help="consultas $geoNear en paralelo")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-sanity", action="store_true", help="omite el control con etiquetas barajadas")
    parser.add_argument("--shuffles", type=int, default=10, help="barajaduras de etiquetas del control (se promedian)")
    parser.add_argument(
        "--from-features",
        action="store_true",
        help="reutiliza `risk_features` de una corrida anterior: salta la agregación de reseñas y los competidores",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 1. Variables por negocio (solo reseñas anteriores a T)
# ---------------------------------------------------------------------------


def aggregate_reviews(spark):
    """Por negocio: primera y última reseña (todas) y conteos con las reseñas < T, en una sola pasada."""
    cutoff = parse_day(CUTOFF_DATE)
    stamp = lambda dt: F.lit(dt.strftime("%Y-%m-%d")).cast("timestamp")
    fecha = F.col("date").cast("timestamp")
    t_end = stamp(cutoff)
    recent_start = stamp(add_months(cutoff, -TREND_HALF_MONTHS))
    prev_start = stamp(add_months(cutoff, -2 * TREND_HALF_MONTHS))

    before = fecha < t_end
    recent = before & (fecha >= recent_start)
    previous = (fecha >= prev_start) & (fecha < recent_start)
    negative, positive = F.col("stars") <= 2, F.col("stars") >= 4
    flag = lambda cond: F.sum(cond.cast("int"))

    resenas = (
        read_collection(spark, "reviews")
        .where(F.col("stars").isNotNull() & fecha.isNotNull())
        .groupBy("business_id")
        .agg(
            F.unix_timestamp(F.min(fecha)).alias("first_s"),
            F.unix_timestamp(F.max(fecha)).alias("last_s"),
            flag(before).alias("n_pre"),
            F.sum(F.when(before, F.col("stars")).otherwise(0.0)).alias("stars_sum"),
            flag(before & positive).alias("pos_pre"),
            flag(before & negative).alias("neg_pre"),
            flag(recent).alias("n_recent"),
            flag(recent & negative).alias("neg_recent"),
            flag(previous).alias("n_prev"),
            flag(previous & negative).alias("neg_prev"),
        )
        # Existía en T (hay reseñas < T) y tuvo actividad desde T: la población, filtrada ya en Spark
        .where((F.col("n_pre") > 0) & (F.col("last_s") >= F.unix_timestamp(t_end)))
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
    return negocios.join(resenas, "business_id").where(F.col("lon").isNotNull() & F.col("is_open").isNotNull())


def build_features(rows):
    """Documentos de `risk_features` con la etiqueta y las variables (sin los competidores todavía)."""
    cutoff = parse_day(CUTOFF_DATE)
    docs = []
    for r in rows:
        first, last = from_epoch_seconds(r["first_s"]), from_epoch_seconds(r["last_s"])
        if not in_population(first, last, cutoff):
            continue
        docs.append(
            {
                "_id": r["business_id"],
                "business_id": r["business_id"],
                "city": r["city"],
                "state": r["state"],
                "primary_category": primary_category(r["categories"]),
                "location": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "is_open": r["is_open"],
                "first_review": first,
                "last_review": last,
                "label": risk_label(r["is_open"], last, cutoff, HORIZON_MONTHS),
                "mean_sentiment": mean_sentiment(r["pos_pre"], r["neg_pre"], r["n_pre"]),
                "neg_trend_6m": negative_trend(r["neg_recent"], r["n_recent"], r["neg_prev"], r["n_prev"]),
                "stars_mean": r["stars_sum"] / r["n_pre"],
                "n_reviews": r["n_pre"],
                "age_days": (cutoff - first).days,
            }
        )
    return docs


def add_competitors(db, threads):
    """Competidores a 500 m de la misma categoría, con $geoNear sobre `risk_features` (la población activa en T)."""
    from pymongo import UpdateOne

    coleccion = db.risk_features

    def contar(doc):
        lon, lat = doc["location"]["coordinates"]
        resultado = list(coleccion.aggregate(competitors_pipeline(lon, lat, doc["primary_category"], doc["_id"])))
        return doc["_id"], resultado[0]["competitors"] if resultado else 0

    pendientes = list(coleccion.find({}, {"location": 1, "primary_category": 1}))
    with ThreadPoolExecutor(max_workers=threads) as pool:
        conteos = list(pool.map(contar, pendientes))
    for inicio in range(0, len(conteos), 5000):
        lote = [UpdateOne({"_id": i}, {"$set": {"competitors_500m": n}}) for i, n in conteos[inicio : inicio + 5000]]
        coleccion.bulk_write(lote, ordered=False)
    return conteos


# ---------------------------------------------------------------------------
# 2. Entrenamiento y evaluación
# ---------------------------------------------------------------------------


def to_dataframe(spark, docs):
    schema = StructType(
        [StructField("business_id", StringType()), StructField("label", DoubleType())]
        + [StructField(name, DoubleType()) for name in FEATURES]
    )
    filas = [(d["business_id"], float(d["label"])) + tuple(float(d[name]) for name in FEATURES) for d in docs]
    df = spark.createDataFrame(filas, schema)
    bucket = F.pmod(F.xxhash64("business_id"), F.lit(100))
    return df.withColumn(
        "split",
        F.when(bucket < TRAIN_PERCENT, "train").when(bucket < TRAIN_PERCENT + VALID_PERCENT, "valid").otherwise("test"),
    )


def with_class_weights(train):
    """Pesos inversos a la frecuencia de cada clase (el cierre es la clase rara)."""
    conteos = {row["label"]: row["count"] for row in train.groupBy("label").count().collect()}
    total = sum(conteos.values())
    peso = {clase: total / (2 * n) for clase, n in conteos.items()}
    return F.when(F.col("label") == 1.0, peso.get(1.0, 1.0)).otherwise(peso.get(0.0, 1.0)), peso


def candidates():
    assembler = VectorAssembler(inputCols=FEATURES, outputCol="raw_features")
    return {
        "logistic_regression": Pipeline(
            stages=[
                assembler,
                StandardScaler(inputCol="raw_features", outputCol="features", withMean=True, withStd=True),
                LogisticRegression(
                    featuresCol="features", labelCol="label", weightCol="weight", maxIter=100, regParam=0.01
                ),
            ]
        ),
        "gbt": Pipeline(
            stages=[
                VectorAssembler(inputCols=FEATURES, outputCol="features"),
                GBTClassifier(
                    featuresCol="features", labelCol="label", weightCol="weight", maxIter=60, maxDepth=4, seed=42
                ),
            ]
        ),
    }


def auc(predictions, metric):
    return BinaryClassificationEvaluator(
        labelCol="label", rawPredictionCol="rawPrediction", metricName=metric
    ).evaluate(predictions)


def scores_and_labels(predictions):
    filas = predictions.select(vector_to_array("probability")[1].alias("score"), "label").collect()
    return [f["score"] for f in filas], [int(f["label"]) for f in filas]


def importances(model):
    clasificador = model.stages[-1]
    if hasattr(clasificador, "featureImportances"):
        return dict(zip(FEATURES, [float(x) for x in clasificador.featureImportances.toArray()]))
    return dict(
        zip(FEATURES, [float(x) for x in clasificador.coefficients.toArray()])
    )  # sobre variables estandarizadas


def shuffled_control(spark, train, test, seed, shuffles):
    """Control con etiquetas barajadas: un modelo entrenado con ruido no debe aprender nada (AUC medio ~ 0,5).

    Un solo modelo entrenado con ruido tiene coeficientes aleatorios y su AUC sobre datos reales cae en cualquier
    punto alrededor de 0,5, según hacia dónde apunte esa dirección aleatoria; por eso se repite con varias
    barajaduras y se mira la media (que debe ser ~0,5) y la dispersión. Devuelve la lista de AUC-ROC.
    """
    ids_labels = [(r["business_id"], r["label"]) for r in train.select("business_id", "label").collect()]
    valores = []
    for k in range(shuffles):
        labels = [label for _, label in ids_labels]
        random.Random(seed + k).shuffle(labels)
        barajadas = spark.createDataFrame(
            [(i, l) for (i, _), l in zip(ids_labels, labels)],
            StructType([StructField("business_id", StringType()), StructField("shuffled", DoubleType())]),
        )
        train_shuffled = train.join(barajadas, "business_id").withColumn("label", F.col("shuffled")).drop("shuffled")
        peso, _ = with_class_weights(train_shuffled)
        modelo = candidates()["logistic_regression"].fit(train_shuffled.withColumn("weight", peso))
        valores.append(auc(modelo.transform(test), "areaUnderROC"))
    return valores


def run():
    args = parse_args()
    spark = build_spark("LifeMap-RiskModel", shuffle_partitions=8)
    spark.sparkContext.setLogLevel("WARN")
    print(
        f"T = {CUTOFF_DATE}: variables con reseñas anteriores a T; etiqueta = cierra en los {HORIZON_MONTHS} meses siguientes"
    )

    from pymongo import GEOSPHERE, MongoClient

    db = MongoClient(MONGO_URI)[DB_NAME]
    if args.from_features:
        print("Reutilizando risk_features de la corrida anterior (sin agregar reseñas ni calcular competidores)...")
        docs = list(db.risk_features.find({"label": {"$ne": None}}))
        if not docs:
            raise SystemExit("risk_features está vacía: hay que ejecutar risk_model.py una vez sin --from-features")
    else:
        print("Agregando las reseñas anteriores a T por negocio...")
        filas = [fila.asDict() for fila in aggregate_reviews(spark).collect()]
        docs = [d for d in build_features(filas) if d["label"] is not None]
    positivos = sum(d["label"] for d in docs)
    print(f"Población: {len(docs)} negocios (existían en T y tuvieron actividad desde T)")
    print(
        f"Cierres en {HORIZON_MONTHS} meses (etiqueta 1): {positivos} = {positivos / len(docs) * 100:.2f} % (prevalencia)"
    )

    if not args.from_features:
        db.risk_features.delete_many({})
        for inicio in range(0, len(docs), 10000):
            db.risk_features.insert_many(docs[inicio : inicio + 10000], ordered=False)
        db.risk_features.create_index([("location", GEOSPHERE)])
        db.risk_features.create_index("primary_category")

        print(f"Competidores a {COMPETITOR_RADIUS_M} m de la misma categoría ($geoNear, {args.threads} hilos)...")
        conteos = add_competitors(db, args.threads)
        por_id = dict(conteos)
        for d in docs:
            d["competitors_500m"] = por_id[d["_id"]]
        print(f"  competidores: media {sum(por_id.values()) / len(por_id):.1f}, máximo {max(por_id.values())}")

    df = to_dataframe(spark, docs).cache()
    partes = {
        fila["split"]: fila
        for fila in df.groupBy("split").agg(F.count("*").alias("n"), F.sum("label").alias("pos")).collect()
    }
    train, valid, test = (df.where(F.col("split") == s) for s in ("train", "valid", "test"))
    print(
        "Partición por negocio (hash de business_id): "
        + ", ".join(f"{s} {int(partes[s]['n'])} ({int(partes[s]['pos'])} cierres)" for s in ("train", "valid", "test"))
    )

    peso, pesos = with_class_weights(train)
    print(f"Pesos de clase: no cierra {pesos.get(0.0, 0):.2f}, cierra {pesos.get(1.0, 0):.2f}")
    train = train.withColumn("weight", peso)

    resultados, modelos = {}, {}
    for nombre, pipeline in candidates().items():
        modelo = pipeline.fit(train)
        pred = modelo.transform(valid)
        resultados[nombre] = {"auc_roc_valid": auc(pred, "areaUnderROC"), "auc_pr_valid": auc(pred, "areaUnderPR")}
        modelos[nombre] = modelo
        print(
            f"  {nombre:<20} validación: AUC-ROC {resultados[nombre]['auc_roc_valid']:.4f}, AUC-PR {resultados[nombre]['auc_pr_valid']:.4f}"
        )

    mejor = max(resultados, key=lambda n: resultados[n]["auc_pr_valid"])
    modelo = modelos[mejor]
    scores_valid, labels_valid = scores_and_labels(modelo.transform(valid))
    umbral = choose_threshold(scores_valid, labels_valid)

    pred_test = modelo.transform(test)
    scores_test, labels_test = scores_and_labels(pred_test)
    base = prevalence(labels_test)
    en_umbral = metrics_at_threshold(scores_test, labels_test, umbral)
    prueba = {
        "auc_roc": auc(pred_test, "areaUnderROC"),
        "auc_pr": auc(pred_test, "areaUnderPR"),
        "auc_pr_baseline": base,
        **en_umbral,
    }

    print(f"\nMejor modelo por AUC-PR en validación: {mejor}; umbral (máx. F1 en validación) = {umbral:.4f}")
    print(f"=== Prueba ({len(labels_test)} negocios, {sum(labels_test)} cierres) ===")
    print(
        f"AUC-ROC {prueba['auc_roc']:.4f}   AUC-PR {prueba['auc_pr']:.4f}  (base sin información = prevalencia {base:.4f}; "
        f"mejora x{prueba['auc_pr'] / base:.1f})"
    )
    print(
        f"En el umbral {umbral:.4f}: recall {en_umbral['recall']:.4f}, precision {en_umbral['precision']:.4f}, "
        f"F1 {en_umbral['f1']:.4f}, alertas {en_umbral['alert_rate'] * 100:.1f} % de los negocios"
    )
    print(
        f"Matriz de confusión (real x predicho): tn={en_umbral['tn']} fp={en_umbral['fp']} fn={en_umbral['fn']} tp={en_umbral['tp']}"
    )
    pesos_variables = importances(modelo)
    print("Importancia de las variables: " + ", ".join(f"{k} {v:+.3f}" for k, v in pesos_variables.items()))

    barajado = None
    if not args.no_sanity:
        valores = shuffled_control(spark, train.drop("weight"), test, args.seed, args.shuffles)
        media = sum(valores) / len(valores)
        desv = (sum((v - media) ** 2 for v in valores) / max(len(valores) - 1, 1)) ** 0.5
        barajado = {"shuffles": len(valores), "mean": media, "std": desv, "min": min(valores), "max": max(valores)}
        print(
            f"Control con etiquetas barajadas ({len(valores)} barajaduras): AUC-ROC medio {media:.4f} ± {desv:.4f} "
            f"(rango {min(valores):.3f}-{max(valores):.3f}; esperado ~0,5)"
        )

    for nombre, m in modelos.items():
        m.write().overwrite().save(f"{MODELS_DIR}/risk_{nombre}")
    modelo.write().overwrite().save(f"{MODELS_DIR}/risk_best")

    # Probabilidad de cierre de toda la población (para alertas y mapas): con la ubicación del negocio
    todos = modelo.transform(df)
    probabilidades = {
        r["business_id"]: (r["score"], r["split"])
        for r in todos.select("business_id", vector_to_array("probability")[1].alias("score"), "split").collect()
    }
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    db.risk_scores.delete_many({})
    db.risk_scores.insert_many(
        [
            {
                "_id": d["_id"],
                "business_id": d["_id"],
                "city": d["city"],
                "primary_category": d["primary_category"],
                "location": d["location"],
                "risk_probability": probabilidades[d["_id"]][0],
                "risk_flag": probabilidades[d["_id"]][0] >= umbral,
                "label": d["label"],
                "split": probabilidades[d["_id"]][1],
                "model": mejor,
                "threshold": umbral,
                "features": {name: d[name] for name in FEATURES},
                "computed_at": ahora,
            }
            for d in docs
        ]
    )
    db.risk_scores.create_index([("location", GEOSPHERE)])
    db.risk_scores.create_index("risk_probability")

    informe = {
        "_id": "risk",
        "fecha": ahora.isoformat(),
        "cutoff": CUTOFF_DATE,
        "horizon_months": HORIZON_MONTHS,
        "features": FEATURES,
        "poblacion": len(docs),
        "cierres": int(positivos),
        "prevalencia": positivos / len(docs),
        "particion": {s: {"negocios": int(partes[s]["n"]), "cierres": int(partes[s]["pos"])} for s in partes},
        "pesos_clase": {str(k): v for k, v in pesos.items()},
        "candidatos": resultados,
        "mejor_modelo": mejor,
        "umbral": umbral,
        "prueba": prueba,
        "importancia_variables": pesos_variables,
        "control_etiquetas_barajadas": barajado,
    }
    db.model_metrics.replace_one({"_id": "risk"}, informe, upsert=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/risk_metrics.json", "w", encoding="utf-8") as archivo:
        json.dump(informe, archivo, ensure_ascii=False, indent=2, default=str)
    print(
        f"\n¡Modelo de riesgo guardado ({MODELS_DIR}/risk_best), risk_scores ({len(docs)}) y model_metrics (_id risk)!"
    )
    spark.stop()


if __name__ == "__main__":
    run()
