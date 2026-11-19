"""Entrega 2, punto 9: verifica la prueba de humo del flujo de streaming.

Comprueba en MongoDB que las 100 reseñas sintéticas que publicó `kafka_streaming/smoke_publish.py` aparecen **clasificadas** por el job de
inferencia: exactamente las esperadas, cada una con una clase válida, probabilidades que suman 1 y coinciden con la clase elegida, su
fecha y su marca de procesamiento; y que el modelo acierta en su mayoría (las reseñas son claramente positivas o negativas), lo que
descarta que "clasifique" con cualquier cosa. Sale con código 1 si algo falla (el build de Jenkins se detiene).

Uso:
    docker compose --profile jobs run --rm spark-jobs python3 /app/verify_smoke.py --run-id build42
    docker compose --profile jobs run --rm spark-jobs python3 /app/verify_smoke.py --run-id build42 --cleanup
"""

import argparse
import sys

from lifemap_common import DB_NAME, MONGO_URI

CLASSES = ("negativo", "neutral", "positivo")
DEFAULT_COLLECTION = "review_predictions_smoke"


def check_smoke_documents(docs, run_id, expected, min_accuracy=0.8):
    """(problemas, estadísticas) de los documentos de la corrida `run_id`; sin problemas = la prueba pasa."""
    prefix = f"smoke-{run_id}-"
    mine = [d for d in docs if str(d.get("_id", "")).startswith(prefix)]
    problems = []
    if len(mine) != expected:
        problems.append(f"hay {len(mine)} reseñas clasificadas y se esperaban {expected}")
    missing = {f"{prefix}{i:03d}" for i in range(expected)} - {d["_id"] for d in mine}
    if missing:
        problems.append(f"faltan {len(missing)} reseñas (por ejemplo {min(missing)})")

    invalid = []
    for d in mine:
        probabilities = d.get("probabilities") or {}
        values = [probabilities.get(c) for c in CLASSES]
        reasons = []
        if d.get("sentiment") not in CLASSES:
            reasons.append(f"clase inválida {d.get('sentiment')!r}")
        if any(v is None for v in values) or abs(sum(v for v in values if v is not None) - 1.0) > 1e-6:
            reasons.append("las probabilidades no suman 1")
        elif d.get("sentiment") in CLASSES and CLASSES[values.index(max(values))] != d["sentiment"]:
            reasons.append("la clase no es la de mayor probabilidad")
        if d.get("date") is None:
            reasons.append("sin fecha")
        if d.get("processed_at") is None:
            reasons.append("sin marca de procesamiento")
        if reasons:
            invalid.append((d["_id"], "; ".join(reasons)))
    if invalid:
        problems.append(
            f"{len(invalid)} reseñas mal clasificadas o incompletas, por ejemplo {invalid[0][0]}: {invalid[0][1]}"
        )

    accuracy = sum(1 for d in mine if d.get("correct")) / len(mine) if mine else 0.0
    if mine and accuracy < min_accuracy:
        problems.append(f"el modelo solo coincide con las estrellas en {accuracy:.0%} (mínimo {min_accuracy:.0%})")
    return problems, {"classified": len(mine), "accuracy": accuracy}


def parse_args():
    parser = argparse.ArgumentParser(description="Verifica la prueba de humo del streaming")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected", type=int, default=100)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    parser.add_argument("--cleanup", action="store_true", help="borra los documentos de la corrida y termina")
    return parser.parse_args()


def main():
    from pymongo import MongoClient

    args = parse_args()
    collection = MongoClient(MONGO_URI)[DB_NAME][args.collection]
    prefix = f"smoke-{args.run_id}-"
    if args.cleanup:
        deleted = collection.delete_many({"_id": {"$regex": f"^{prefix}"}}).deleted_count
        print(f"Borrados {deleted} documentos de la prueba de humo en {args.collection}")
        return 0

    docs = list(collection.find({"_id": {"$regex": f"^{prefix}"}}))
    problems, stats = check_smoke_documents(docs, args.run_id, args.expected, args.min_accuracy)
    print(
        f"Prueba de humo (run {args.run_id}): {stats['classified']} reseñas clasificadas en {args.collection}; "
        f"el modelo coincide con las estrellas en {stats['accuracy']:.0%}"
    )
    for problem in problems:
        print(f"FAIL  {problem}")
    if problems:
        return 1
    print(f"PASS  las {args.expected} reseñas publicadas aparecen clasificadas en MongoDB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
