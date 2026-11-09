"""Punto 4 de la Entrega 1: modelo de sentimiento en Spark.

Reutiliza el pipeline de SentimentStream (limpieza, tokenización, stopwords, HashingTF/IDF),
entrena Naive Bayes y regresión logística, y guarda los modelos para la Entrega 2.

Decisiones clave:
- La partición entrenamiento/prueba es por negocio: todas las reseñas de un negocio caen en
  el mismo lado, así que el modelo nunca se evalúa con negocios que vio al entrenar.
- El pipeline completo (limpieza + TF-IDF + clasificador) se guarda como PipelineModel, de modo
  que la Entrega 2 lo carga y clasifica texto crudo sin reentrenar.
- La distribución de clases es desbalanceada: se entrena con pesos inversos a la frecuencia de
  cada clase y se reportan métricas por clase, no solo accuracy.

Uso:
    spark-submit /app/sentiment_model.py [--sample-fraction 0.1] [--cutoff 2020-01-01]
"""

import argparse
import json
import os
from datetime import datetime, timezone

from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression, NaiveBayes
from pyspark.ml.evaluation import MulticlassClassificationEvaluator
from pyspark.ml.feature import IDF, HashingTF, RegexTokenizer, SQLTransformer, StopWordsRemover
from pyspark.sql import functions as F

from lifemap_common import (
    DB_NAME,
    MODELS_DIR,
    MONGO_URI,
    OUTPUT_DIR,
    build_spark,
    read_collection,
    sentiment_label,
)

CLASES = {0.0: "negativo", 1.0: "neutral", 2.0: "positivo"}
NUM_FEATURES = 2**18
TRAIN_PERCENT = 80  # porcentaje de negocios (por hash de business_id) que va a entrenamiento


def parse_args():
    parser = argparse.ArgumentParser(description="Entrena los modelos de sentimiento de LifeMap")
    parser.add_argument("--sample-fraction", type=float, default=1.0,
                        help="fracción de reseñas a usar (1.0 = todas)")
    parser.add_argument("--cutoff", default=None,
                        help="fecha de corte T (YYYY-MM-DD): se descartan las reseñas posteriores, "
                             "que la Entrega 2 reserva para el streaming")
    return parser.parse_args()


def build_preprocessing_stages():
    """Etapas de SentimentStream: limpieza, tokenización, stopwords en inglés y TF-IDF."""
    # Limpieza: minúsculas, sin URLs y sin nada que no sea una letra.
    limpieza = SQLTransformer(statement=(
        "SELECT *, regexp_replace(regexp_replace(lower(text), 'https?://\\\\S+', ' '), "
        "'[^a-z\\\\s]', ' ') AS clean_text FROM __THIS__"
    ))
    tokenizer = RegexTokenizer(inputCol="clean_text", outputCol="words",
                               pattern="\\s+", minTokenLength=2)
    remover = StopWordsRemover(inputCol="words", outputCol="filtered_words",
                               stopWords=StopWordsRemover.loadDefaultStopWords("english"))
    hashing_tf = HashingTF(inputCol="filtered_words", outputCol="raw_features",
                           numFeatures=NUM_FEATURES)
    idf = IDF(inputCol="raw_features", outputCol="features", minDocFreq=5)
    return [limpieza, tokenizer, remover, hashing_tf, idf]


def add_class_weights(train_df):
    """Agrega `weight` = total / (n_clases * frecuencia de la clase) para compensar el desbalance."""
    conteos = {row["label"]: row["count"] for row in train_df.groupBy("label").count().collect()}
    total = sum(conteos.values())
    pesos = {clase: total / (len(conteos) * n) for clase, n in conteos.items()}
    expr = F.create_map(*[x for clase, p in pesos.items() for x in (F.lit(clase), F.lit(p))])
    return train_df.withColumn("weight", expr[F.col("label")]), pesos


def evaluate(predictions):
    """Accuracy, F1 macro/ponderado, precision/recall/F1 por clase y matriz de confusión."""
    # Se calculan ~12 métricas sobre las mismas predicciones: sin caché cada una
    # re-ejecutaría el pipeline completo (TF-IDF incluido) sobre el conjunto de prueba.
    predictions = predictions.cache()

    def metrica(nombre, label=None):
        evaluator = MulticlassClassificationEvaluator(
            labelCol="label", predictionCol="prediction", metricName=nombre)
        if label is not None:
            evaluator = evaluator.setMetricLabel(label)
        return evaluator.evaluate(predictions)

    por_clase = {}
    for etiqueta, nombre in CLASES.items():
        por_clase[nombre] = {
            "precision": metrica("precisionByLabel", etiqueta),
            "recall": metrica("recallByLabel", etiqueta),
            "f1": metrica("fMeasureByLabel", etiqueta),
        }

    filas = (predictions.groupBy("label")
             .pivot("prediction", list(CLASES))
             .count().na.fill(0).orderBy("label").collect())
    matriz = {CLASES[fila["label"]]: {CLASES[c]: int(fila[str(c)]) for c in CLASES} for fila in filas}

    resultado = {
        "accuracy": metrica("accuracy"),
        "f1_weighted": metrica("f1"),
        "f1_macro": sum(m["f1"] for m in por_clase.values()) / len(por_clase),
        "por_clase": por_clase,
        "matriz_confusion": matriz,  # filas = clase real, columnas = clase predicha
    }
    predictions.unpersist()
    return resultado


def print_report(nombre, metricas):
    print(f"\n=== {nombre} ===")
    print(f"accuracy={metricas['accuracy']:.4f}  F1 macro={metricas['f1_macro']:.4f}  "
          f"F1 ponderado={metricas['f1_weighted']:.4f}")
    print(f"{'clase':<10}{'precision':>10}{'recall':>10}{'f1':>10}")
    for clase, m in metricas["por_clase"].items():
        print(f"{clase:<10}{m['precision']:>10.4f}{m['recall']:>10.4f}{m['f1']:>10.4f}")
    print("matriz de confusión (filas = real, columnas = predicho):")
    nombres = list(CLASES.values())
    print(f"{'':<10}" + "".join(f"{n:>10}" for n in nombres))
    for real, fila in metricas["matriz_confusion"].items():
        print(f"{real:<10}" + "".join(f"{fila[n]:>10}" for n in nombres))


def run_sentiment_pipeline():
    args = parse_args()
    spark = build_spark("LifeMap-SentimentAnalysis")

    print("Cargando reseñas desde MongoDB...")
    df = read_collection(spark, "reviews").select("review_id", "business_id", "stars", "text", "date")
    df = df.where(F.col("text").isNotNull() & F.col("stars").isNotNull())
    if args.cutoff:
        # Las reseñas posteriores a T se reservan para el streaming de la Entrega 2.
        df = df.where(F.to_date("date") <= F.lit(args.cutoff).cast("date"))
    if args.sample_fraction < 1.0:
        df = df.sample(withReplacement=False, fraction=args.sample_fraction, seed=42)
    df = df.withColumn("label", sentiment_label(F.col("stars").cast("double"))).cache()

    total = df.count()
    distribucion = {CLASES[row["label"]]: row["count"] for row in df.groupBy("label").count().collect()}
    print(f"Reseñas: {total}")
    print("Distribución de clases (desbalanceada, se reporta como pide la guía):")
    for clase, n in sorted(distribucion.items()):
        print(f"  {clase:<9}{n:>10}  {100 * n / total:6.2f} %")

    # Partición por negocio: el hash de business_id decide el lado, sin fuga entre negocios.
    bucket = F.pmod(F.xxhash64("business_id"), F.lit(100))
    train_df = df.where(bucket < TRAIN_PERCENT)
    test_df = df.where(bucket >= TRAIN_PERCENT)
    negocios_train = train_df.select("business_id").distinct()
    negocios_test = test_df.select("business_id").distinct()
    interseccion = negocios_train.join(negocios_test, "business_id").count()
    print(f"\nNegocios en entrenamiento: {negocios_train.count()}, en prueba: {negocios_test.count()}")
    print(f"Negocios presentes en ambos lados: {interseccion}")
    if interseccion != 0:
        raise RuntimeError("Fuga de datos: hay negocios en entrenamiento y en prueba")

    train_df, pesos = add_class_weights(train_df)
    print("Pesos por clase:", {CLASES[c]: round(p, 3) for c, p in pesos.items()})

    clasificadores = {
        "naive_bayes": NaiveBayes(featuresCol="features", labelCol="label", weightCol="weight",
                                  modelType="multinomial"),
        "logistic_regression": LogisticRegression(featuresCol="features", labelCol="label",
                                                  weightCol="weight", family="multinomial",
                                                  maxIter=20),
    }

    resultados = {}
    modelos = {}
    for nombre, clasificador in clasificadores.items():
        print(f"\nEntrenando {nombre}...")
        modelo = Pipeline(stages=build_preprocessing_stages() + [clasificador]).fit(train_df)
        metricas = evaluate(modelo.transform(test_df))
        print_report(nombre, metricas)
        modelo.write().overwrite().save(f"{MODELS_DIR}/sentiment_{nombre}")
        resultados[nombre] = metricas
        modelos[nombre] = modelo

    mejor = max(resultados, key=lambda n: resultados[n]["f1_macro"])
    # El de mayor F1 macro es el que carga la Entrega 2 (F1 macro pesa igual a cada clase).
    modelos[mejor].write().overwrite().save(f"{MODELS_DIR}/sentiment_best")
    print(f"\nMejor modelo por F1 macro: {mejor} (guardado en {MODELS_DIR}/sentiment_best)")

    informe = {
        "fecha": datetime.now(timezone.utc).isoformat(),
        "reseñas": total,
        "distribucion_clases": distribucion,
        "cutoff": args.cutoff,
        "sample_fraction": args.sample_fraction,
        "mejor_modelo": mejor,
        "modelos": resultados,
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/sentiment_metrics.json", "w", encoding="utf-8") as archivo:
        json.dump(informe, archivo, ensure_ascii=False, indent=2)

    from pymongo import MongoClient
    MongoClient(MONGO_URI)[DB_NAME].model_metrics.replace_one(
        {"_id": "sentiment"}, {"_id": "sentiment", **informe}, upsert=True)

    print("¡Modelos de sentimiento entrenados, evaluados y guardados con éxito!")
    spark.stop()


if __name__ == "__main__":
    run_sentiment_pipeline()
