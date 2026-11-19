"""Modelo de sentimiento para /predict.

Carga el PipelineModel que guarda spark_batch/sentiment_model.py (limpieza + TF-IDF +
clasificador) en MODEL_PATH, con una sesión de Spark local dentro de la API, y clasifica texto
crudo sin reentrenar. Si el modelo aún no se ha entrenado, /predict responde 503. Si se vuelve a
entrenar, se recarga en la siguiente predicción.
"""

import json
import logging
import os
import threading

MODEL_PATH = os.getenv("MODEL_PATH", "/app/models/sentiment_best")

# Mismas clases que spark_batch/sentiment_model.py (etiqueta numérica -> nombre)
CLASSES = {0: "negativo", 1: "neutral", 2: "positivo"}

log = logging.getLogger(__name__)


def read_model_version(path):
    """`uid@timestamp` del metadata de un PipelineModel guardado, o None si no hay modelo.

    Es la misma función de spark_batch/model_version.py (la API se construye aparte y no ve ese módulo);
    tests/test_model_version.py comprueba que dan el mismo resultado.
    """
    metadata_dir = os.path.join(path, "metadata")
    if not os.path.isdir(metadata_dir):
        return None
    parts = sorted(name for name in os.listdir(metadata_dir) if name.startswith("part-"))
    if not parts:
        return None
    with open(os.path.join(metadata_dir, parts[0]), encoding="utf-8") as archivo:
        metadata = json.loads(archivo.readline())
    return f"{metadata['uid']}@{metadata['timestamp']}"


def overall_status(mongo_status, model_status, kafka_status="not_configured"):
    """Estado general de /health: "ok" o "degraded".

    MongoDB caído => degraded (y la API responde 503). Un modelo entrenado que no se puede cargar
    ("error: ...") también es degraded, pero la API sigue sirviendo el resto de endpoints. Que el
    modelo aún no esté entrenado ("not_trained") o no se haya cargado todavía ("not_loaded") es
    normal (staging no tiene modelo) y no degrada.

    Kafka: si está configurado y no responde ("unreachable") o su estado no se actualiza ("stale"), también es
    degraded (con HTTP 200: el resto de endpoints funciona). "not_configured" (staging) y "unknown" (todavía no se
    ha sondeado, justo al arrancar) no degradan.
    """
    if mongo_status != "healthy" or model_status.startswith("error"):
        return "degraded"
    if kafka_status.startswith(("unreachable", "stale", "error")):
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
        self._loaded_version = None
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
                    version = read_model_version(self.path)  # antes de cargar: es la versión de lo que se carga
                    log.info("Cargando el modelo de sentimiento %s desde %s", version, self.path)
                    self._model = PipelineModel.load(self.path)
                    self._loaded_mtime = mtime
                    self._loaded_version = version
                    self._error = None
                except Exception as e:  # el error se reporta en /health y /predict
                    self._error = str(e)
                    raise ModelNotAvailable(f"no se pudo cargar el modelo: {e}") from e
        return self._model

    def version(self):
        """Versión (`uid@timestamp`) del modelo que esta API tiene cargado en memoria; None si todavía no cargó ninguno."""
        return self._loaded_version if self._model is not None else None

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
            results.append(
                {
                    "text": row["text"],
                    "sentiment": CLASSES.get(int(row["prediction"]), str(row["prediction"])),
                    "probabilities": {CLASSES.get(i, str(i)): round(p, 4) for i, p in enumerate(probabilities)},
                }
            )
        return results
