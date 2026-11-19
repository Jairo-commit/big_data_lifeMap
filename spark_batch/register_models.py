"""Entrega 2, punto 9: registra en MongoDB la versión de los modelos guardados (`model_registry`).

Se ejecuta tras los jobs de entrenamiento (sentiment_model.py, risk_model.py): lee el modelo en disco, calcula su versión
(`uid@timestamp` del metadata) y su suma de verificación, y los guarda. Después, `verify_model_version.py` comprueba que el
modelo que cargan la API y los jobs de streaming es el registrado. Si se reentrena un modelo y no se vuelve a registrar, esa
prueba falla.

Uso:
    docker compose --profile jobs run --rm spark-jobs spark-submit /app/register_models.py
"""

import os

from lifemap_common import DB_NAME, MODELS_DIR, MONGO_URI
from model_version import MODELS, REGISTRY_COLLECTION, registry_entry


def main():
    from pymongo import MongoClient

    db = MongoClient(MONGO_URI)[DB_NAME]
    registered = 0
    print(f"Modelos en {MODELS_DIR}:")
    for name, (folder, metrics_id) in MODELS.items():
        path = os.path.join(MODELS_DIR, folder)
        metrics = db.model_metrics.find_one({"_id": metrics_id}, {"fecha": 1}) or {}
        entry = registry_entry(name, path, metrics_id=metrics_id, trained_at=metrics.get("fecha"))
        if entry is None:
            print(f"  {name:<32} sin modelo en {path}: no se registra")
            continue
        db[REGISTRY_COLLECTION].replace_one({"_id": name}, entry, upsert=True)
        registered += 1
        print(f"  {name:<32} {entry['version']}  sha256 {entry['checksum'][:16]}")
    if registered == 0:
        raise SystemExit(
            "No hay ningún modelo que registrar: primero hay que entrenar (sentiment_model.py, risk_model.py)"
        )
    print(f"¡{registered} modelos registrados en {DB_NAME}.{REGISTRY_COLLECTION}!")


if __name__ == "__main__":
    main()
