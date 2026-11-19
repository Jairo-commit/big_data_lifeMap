"""Entrega 2, punto 9: publica los mensajes de la prueba de humo del flujo de streaming.

Publica `--count` (100) reseñas sintéticas, con ids `smoke-<run-id>-NNN`, en un topic aparte (`reviews-smoke`) para no mezclarlas con
las reseñas reales del topic `reviews`. Son claramente positivas (40 %), negativas (40 %) y neutrales (20 %), con las estrellas que
les corresponden, y llevan fecha posterior a T para que el job de inferencia no las descarte. `--cleanup` borra el topic al terminar.

Uso (desde la imagen del productor):
    docker compose --profile streaming run --rm --entrypoint python producer smoke_publish.py --run-id build42
    docker compose --profile streaming run --rm --entrypoint python producer smoke_publish.py --run-id build42 --cleanup
"""

import argparse
import json
from datetime import datetime, timedelta

# lifemap_common.py se copia en la imagen desde spark_batch/ (ver kafka_streaming/Dockerfile)
from lifemap_common import KAFKA_BOOTSTRAP

SMOKE_TOPIC = "reviews-smoke"
FIRST_DATE = datetime(2021, 2, 1, 12, 0, 0)  # posterior a T (2021-01-01): la inferencia descarta lo anterior

POSITIVE = [
    "The food was absolutely delicious and the staff were wonderful. We will definitely come back!",
    "Great service, friendly people and an amazing atmosphere. Highly recommended to everyone.",
    "Fantastic place, everything was fresh and perfectly cooked. The best meal I have had in a long time.",
    "Excellent experience from start to finish. The owner was kind and the prices are very fair.",
]
NEGATIVE = [
    "Terrible service and cold food. We waited an hour and nobody apologized. Never coming back.",
    "The worst experience ever. Dirty tables, rude staff and a disgusting smell. Total waste of money.",
    "Awful food, overpriced and completely tasteless. I was very disappointed and left angry.",
    "Horrible place, the staff ignored us and the order was wrong twice. Do not go here.",
]
NEUTRAL = [
    "It was okay. Nothing special, but not bad either. An average place with average food.",
    "Decent enough, the food was fine and the service was acceptable. Maybe I will return.",
]


def smoke_messages(run_id, count=100, first_date=FIRST_DATE):
    """Lista de (clave, valor) en bytes con `count` reseñas sintéticas únicas; la clave es el business_id.

    El tipo de cada reseña sale de su posición (2 positivas, 2 negativas y 1 neutral de cada 5), así que con 100 son 40/40/20.
    """
    messages = []
    for i in range(count):
        kind = i % 5
        if kind in (0, 1):
            text, stars = POSITIVE[i % len(POSITIVE)], (5.0 if kind == 0 else 4.0)
        elif kind in (2, 3):
            text, stars = NEGATIVE[i % len(NEGATIVE)], (1.0 if kind == 2 else 2.0)
        else:
            text, stars = NEUTRAL[i % len(NEUTRAL)], 3.0
        business_id = f"smoke-business-{i % 10}"
        value = {
            "review_id": f"smoke-{run_id}-{i:03d}",
            "business_id": business_id,
            "user_id": f"smoke-user-{i % 7}",
            "stars": stars,
            "text": f"{text} (smoke test {i})",
            "date": (first_date + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        messages.append((business_id.encode("utf-8"), json.dumps(value, ensure_ascii=False).encode("utf-8")))
    return messages


def parse_args():
    parser = argparse.ArgumentParser(description="Publica reseñas sintéticas para la prueba de humo del streaming")
    parser.add_argument("--run-id", required=True, help="identificador de esta corrida (entra en los review_id)")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--topic", default=SMOKE_TOPIC)
    parser.add_argument("--bootstrap", default=KAFKA_BOOTSTRAP)
    parser.add_argument("--cleanup", action="store_true", help="borra el topic y termina, sin publicar")
    return parser.parse_args()


def create_topic(admin, topic):
    from confluent_kafka.admin import NewTopic

    for name, future in admin.create_topics([NewTopic(topic, num_partitions=3, replication_factor=1)]).items():
        try:
            future.result(30)
            print(f"Topic '{name}' creado (3 particiones)")
        except Exception as error:
            if "already exists" not in str(error).lower() and "TOPIC_ALREADY_EXISTS" not in str(error):
                raise


def delete_topic(admin, topic):
    for name, future in admin.delete_topics([topic], operation_timeout=30).items():
        try:
            future.result(30)
            print(f"Topic '{name}' borrado")
        except Exception as error:
            print(f"No se pudo borrar el topic '{name}' (puede que no exista): {error}")


def run():
    from confluent_kafka import Producer
    from confluent_kafka.admin import AdminClient

    args = parse_args()
    admin = AdminClient({"bootstrap.servers": args.bootstrap})
    if args.cleanup:
        delete_topic(admin, args.topic)
        return

    create_topic(admin, args.topic)
    failures = []
    producer = Producer({"bootstrap.servers": args.bootstrap, "client.id": "lifemap-smoke", "enable.idempotence": True})
    for key, value in smoke_messages(args.run_id, args.count):
        producer.produce(
            args.topic, key=key, value=value, on_delivery=lambda err, _msg: failures.append(err) if err else None
        )
        producer.poll(0)
    producer.flush(60)
    if failures:
        raise SystemExit(f"{len(failures)} mensajes fallaron; el primero: {failures[0]}")
    print(f"¡Listo! {args.count} reseñas sintéticas publicadas en '{args.topic}' (run {args.run_id})")


if __name__ == "__main__":
    run()
