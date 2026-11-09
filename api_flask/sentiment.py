"""Modelo de sentimiento para /predict.

Carga el PipelineModel que guarda spark_batch/sentiment_model.py (limpieza + TF-IDF +
clasificador) en MODEL_PATH, con una sesión de Spark local dentro de la API, y clasifica texto
crudo sin reentrenar. Si el modelo aún no se ha entrenado, /predict responde 503. Si se vuelve a
entrenar, se recarga en la siguiente predicción.
"""

import logging
import os
import threading

MODEL_PATH = os.getenv("MODEL_PATH", "/app/models/sentiment_best")

# Mismas clases que spark_batch/sentiment_model.py (etiqueta numérica -> nombre)
CLASSES = {0: "negativo", 1: "neutral", 2: "positivo"}

log = logging.getLogger(__name__)


def overall_status(mongo_status, model_status):
    """Estado general de /health: "ok" o "degraded".

    MongoDB caído => degraded (y la API responde 503). Un modelo entrenado que no se puede cargar
    ("error: ...") también es degraded, pero la API sigue sirviendo el resto de endpoints. Que el
    modelo aún no esté entrenado ("not_trained") o no se haya cargado todavía ("not_loaded") es
    normal (staging no tiene modelo) y no degrada.
    """
    if mongo_status != "healthy" or model_status.startswith("error"):
        return "degraded"
    return "ok"


class ModelNotAvailable(RuntimeError):
    """El modelo no está entrenado o no se pudo cargar."""


class SentimentModel:
    def __init__(self, path=MODEL_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._spark = None
        self._model = None
        self._loaded_mtime = None
        self._error = None

    def _metadata_mtime(self):
        try:
            return os.path.getmtime(os.path.join(self.path, "metadata"))
        except OSError:
            return None

    def _session(self):
        if self._spark is None:
            from pyspark.sql import SparkSession

            self._spark = (
                SparkSession.builder.appName("LifeMap-API-predict")
                .master("local[1]")
                .config("spark.ui.enabled", "false")
                .config("spark.sql.shuffle.partitions", "1")
                .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "1g"))
                .getOrCreate()
            )
            self._spark.sparkContext.setLogLevel("WARN")
        return self._spark

    def _ensure_loaded(self):
        """Carga el modelo si existe y no está cargado, o si cambió desde la última carga."""
        mtime = self._metadata_mtime()
        if mtime is None:
            raise ModelNotAvailable(f"el modelo no está entrenado ({self.path} no existe)")
        if self._model is not None and mtime == self._loaded_mtime:
            return self._model
        with self._lock:
            if self._model is None or mtime != self._loaded_mtime:
                try:
                    from pyspark.ml import PipelineModel

                    self._session()
                    log.info("Cargando el modelo de sentimiento desde %s", self.path)
                    self._model = PipelineModel.load(self.path)
                    self._loaded_mtime = mtime
                    self._error = None
                except Exception as e:  # el error se reporta en /health y /predict
                    self._error = str(e)
                    raise ModelNotAvailable(f"no se pudo cargar el modelo: {e}") from e
        return self._model

    def status(self):
        if self._model is not None:
            return "loaded"
        if self._metadata_mtime() is None:
            return "not_trained"
        if self._error:
            return f"error: {self._error}"
        return "not_loaded"

    def warm_up(self):
        """Carga el modelo al arrancar (en segundo plano) para que la primera predicción sea rápida."""
        try:
            self._ensure_loaded()
        except ModelNotAvailable as e:
            log.warning("%s", e)

    def predict(self, texts):
        """Clase y probabilidades de cada texto."""
        model = self._ensure_loaded()
        spark = self._session()
        df = spark.createDataFrame([(t,) for t in texts], "text string")
        rows = model.transform(df).select("text", "prediction", "probability").collect()
        results = []
        for row in rows:
            probabilities = row["probability"].toArray().tolist()
            results.append({
                "text": row["text"],
                "sentiment": CLASSES.get(int(row["prediction"]), str(row["prediction"])),
                "probabilities": {CLASSES.get(i, str(i)): round(p, 4) for i, p in enumerate(probabilities)},
            })
        return results
