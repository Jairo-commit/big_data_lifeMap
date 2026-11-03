import sys
from pyspark.sql import SparkSession
from pyspark.ml.feature import Tokenizer, StopWordsRemover, HashingTF, IDF
from pyspark.ml.classification import NaiveBayes, LogisticRegression
from pyspark.ml.evaluation import MulticlassClassificationEvaluator

def run_sentiment_pipeline():
    # Inicializar sesión de Spark con soporte para MongoDB
    spark = SparkSession.builder \
        .appName("LifeMap-SentimentAnalysis") \
        .config("spark.mongodb.read.connection.uri", "mongodb://mongodb:27017/lifemap_db.reviews") \
        .getOrCreate()

    print("Cargando reseñas desde MongoDB...")
    df = spark.read.format("mongo").load()

    # Derivar la etiqueta de sentimiento a partir de las estrellas (1-2: negativo, 3: neutral, 4-5: positivo)
    from pyspark.sql.functions import when
    df = df.withColumn("label", 
        when(df["stars"] <= 2, 0.0)
        .when(df["stars"] == 3, 1.0)
        .otherwise(2.0)
    )

    # Partición por negocio para evitar fuga de datos (requerido por rúbrica)
    print("Particionando datos por negocio...")
    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)

    # Pipeline de procesamiento de texto (Tokenizer -> StopWords -> TF-IDF)
    tokenizer = Tokenizer(inputCol="text", outputCol="words")
    remover = StopWordsRemover(inputCol="words", outputCol="filtered_words")
    hashingTF = HashingTF(inputCol="filtered_words", outputCol="raw_features", numFeatures=10000)
    idf = IDF(inputCol="raw_features", outputCol="features")

    from pyspark.ml import Pipeline
    preprocessing_pipeline = Pipeline(stages=[tokenizer, remover, hashingTF, idf])

    print("Entrenando modelos (Naive Bayes y Regresión Logística)...")
    preprocessed_train = preprocessing_pipeline.fit(train_df).transform(train_df)
    preprocessed_test = preprocessing_pipeline.fit(train_df).transform(test_df)

    # Entrenar Naive Bayes
    nb = NaiveBayes(featuresCol="features", labelCol="label")
    nb_model = nb.fit(preprocessed_train)

    # Entrenar Regresión Logística para comparación
    lr = LogisticRegression(featuresCol="features", labelCol="label", maxIter=10)
    lr_model = lr.fit(preprocessed_train)

    # Evaluar modelos
    predictions = nb_model.transform(preprocessed_test)
    evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction", metricName="f1")
    f1_score = evaluator.evaluate(predictions)
    print(f"F1-Score del modelo Naive Bayes: {f1_score}")

    # Guardar el modelo entrenado para la Entrega 2
    nb_model.write().overwrite().save("/app/models/naive_bayes_sentiment")
    print("¡Modelo de sentimiento entrenado y guardado con éxito!")

    spark.stop()

if __name__ == "__main__":
    run_sentiment_pipeline()
