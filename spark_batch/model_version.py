"""Entrega 2, punto 9: versión de los modelos guardados y su registro en MongoDB (`model_registry`).

Lógica sin Spark: solo lee los archivos del modelo en disco, así que se prueba con pytest (tests/test_model_version.py) y
la usan `register_models.py` y `verify_model_version.py`.

Un `PipelineModel` guardado por Spark tiene un `metadata` con su `uid` y la hora de entrenamiento: `uid@timestamp` es único por
entrenamiento y es la **versión**. Además se guarda la **suma de verificación** (SHA-256) de todos sus archivos, para detectar un
modelo alterado o corrupto aunque conserve la misma versión. La API informa la versión del modelo que cargó (api_flask/sentiment.py
tiene la misma función, y un test comprueba que ambas dan lo mismo).
"""

import hashlib
import json
import os
from datetime import datetime, timezone

REGISTRY_COLLECTION = "model_registry"

# Modelos que guardan los jobs: nombre del registro -> (carpeta dentro de MODELS_DIR, documento de model_metrics)
MODELS = {
    "sentiment_best": ("sentiment_best", "sentiment"),
    "sentiment_naive_bayes": ("sentiment_naive_bayes", "sentiment"),
    "sentiment_logistic_regression": ("sentiment_logistic_regression", "sentiment"),
    "risk_best": ("risk_best", "risk"),
    "risk_gbt": ("risk_gbt", "risk"),
    "risk_logistic_regression": ("risk_logistic_regression", "risk"),
}


def read_model_version(path):
    """`uid@timestamp` del metadata de un PipelineModel guardado, o None si la carpeta no tiene un modelo."""
    metadata_dir = os.path.join(path, "metadata")
    if not os.path.isdir(metadata_dir):
        return None
    parts = sorted(name for name in os.listdir(metadata_dir) if name.startswith("part-"))
    if not parts:
        return None
    with open(os.path.join(metadata_dir, parts[0]), encoding="utf-8") as archivo:
        metadata = json.loads(archivo.readline())
    return f"{metadata['uid']}@{metadata['timestamp']}"


def model_checksum(path):
    """SHA-256 de todos los archivos del modelo (rutas relativas ordenadas + contenido).

    Se ignoran `_SUCCESS` y los `.crc` de Hadoop: no son parte del modelo y pueden variar sin que el modelo cambie.
    """
    digest = hashlib.sha256()
    for folder, subfolders, files in os.walk(path):
        subfolders.sort()
        for name in sorted(files):
            if name == "_SUCCESS" or name.endswith(".crc"):
                continue
            full = os.path.join(folder, name)
            digest.update(os.path.relpath(full, path).encode("utf-8") + b"\0")
            with open(full, "rb") as archivo:
                for bloque in iter(lambda: archivo.read(1 << 20), b""):
                    digest.update(bloque)
    return digest.hexdigest()


def registry_entry(name, path, metrics_id=None, trained_at=None, registered_at=None):
    """Documento de `model_registry` para un modelo guardado en `path`; None si no hay modelo."""
    version = read_model_version(path)
    if version is None:
        return None
    return {
        "_id": name,
        "name": name,
        "path": path,
        "version": version,
        "checksum": model_checksum(path),
        "metrics_id": metrics_id,
        "trained_at": trained_at,
        "registered_at": registered_at or datetime.now(timezone.utc).replace(tzinfo=None),
    }


def verify_registered(entry, disk_version, disk_checksum):
    """Problemas entre lo registrado y lo que hay en disco (lista vacía = el modelo en disco es el versionado)."""
    if entry is None:
        return ["el modelo no está registrado en model_registry"]
    problems = []
    if disk_version is None:
        problems.append("no hay modelo en disco")
        return problems
    if entry.get("version") != disk_version:
        problems.append(f"la versión registrada ({entry.get('version')}) no es la del disco ({disk_version})")
    if entry.get("checksum") != disk_checksum:
        problems.append(
            "la suma de verificación del disco no coincide con la registrada: el modelo cambió o está alterado"
        )
    return problems
