"""Entrega 2, punto 9: confirma que el modelo cargado es el versionado.

Para cada modelo (sentiment_best y risk_best, los que cargan la API y los jobs de streaming) compara tres cosas:

1. la versión (`uid@timestamp`) y la suma de verificación registradas en `model_registry` (register_models.py),
2. lo que hay en disco en /app/models, que es lo que cargan los jobs de streaming (streaming_inference.py, streaming_alerts.py),
3. para el modelo de sentimiento, la versión que informa la **API**: la de su respuesta a `/predict` (el modelo que realmente usó) y la de
   `/health`.

Falla (código 1) si el modelo no está registrado, si el de disco no es el registrado (se reentrenó sin registrar, o se alteró) o si la API
cargó otra versión (se quedó con un modelo anterior). Así un build no despliega un modelo que no está versionado.

Uso:
    docker compose --profile jobs run --rm spark-jobs python3 /app/verify_model_version.py --api http://api:5000
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from lifemap_common import DB_NAME, MODELS_DIR, MONGO_URI
from model_version import MODELS, REGISTRY_COLLECTION, model_checksum, read_model_version, verify_registered

DEFAULT_MODELS = ("sentiment_best", "risk_best")
SAMPLE_TEXT = "The food was great and the staff were friendly"


def compare_api_version(registered_version, api_predict_version, api_health_version):
    """Problemas entre la versión registrada y las que informa la API (lista vacía = coinciden)."""
    problems = []
    if not api_predict_version:
        problems.append("/predict no informó la versión del modelo que respondió")
    elif api_predict_version != registered_version:
        problems.append(
            f"/predict respondió con el modelo {api_predict_version}, y el registrado es {registered_version}"
        )
    if api_health_version != registered_version:
        problems.append(f"/health informa el modelo {api_health_version}, y el registrado es {registered_version}")
    return problems


def request_json(url, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def parse_args():
    parser = argparse.ArgumentParser(description="Comprueba que el modelo cargado es el versionado")
    parser.add_argument("--api", default="http://api:5000")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS), choices=sorted(MODELS))
    return parser.parse_args()


def main():
    from pymongo import MongoClient

    args = parse_args()
    db = MongoClient(MONGO_URI)[DB_NAME]
    failures = 0

    def report(ok, text):
        nonlocal failures
        failures += 0 if ok else 1
        print(("PASS  " if ok else "FAIL  ") + text)

    registered = {}
    for name in args.models:
        entry = db[REGISTRY_COLLECTION].find_one({"_id": name})
        path = os.path.join(MODELS_DIR, MODELS[name][0])
        problems = verify_registered(
            entry, read_model_version(path), model_checksum(path) if os.path.isdir(path) else None
        )
        registered[name] = entry["version"] if entry else None
        if problems:
            for problem in problems:
                report(False, f"{name}: {problem}")
        else:
            report(
                True,
                f"{name}: el modelo en disco es el registrado ({entry['version']}, sha256 {entry['checksum'][:12]})",
            )

    if "sentiment_best" in args.models and registered.get("sentiment_best"):
        status, prediction = request_json(f"{args.api}/predict", {"text": SAMPLE_TEXT})
        if status != 200:
            report(False, f"POST /predict respondió {status}: {prediction}")
        else:
            _, health = request_json(f"{args.api}/health")
            problems = compare_api_version(
                registered["sentiment_best"],
                prediction.get("model_version"),
                (health.get("model_versions") or {}).get("sentiment_best"),
            )
            if problems:
                for problem in problems:
                    report(False, f"API: {problem}")
            else:
                report(
                    True,
                    f"la API respondió con el modelo registrado {registered['sentiment_best']} (/predict y /health)",
                )

    print(
        "\nRESULTADO:",
        "el modelo cargado es el versionado" if failures == 0 else f"{failures} comprobación(es) fallaron",
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
