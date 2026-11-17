"""Entrega 2: productor de Kafka con reloj acelerado.

Publica en el topic `reviews` las reseñas con fecha >= T (CUTOFF_DATE, la constante de
spark_batch/lifemap_common.py que también usa el entrenamiento), que el modelo nunca ve al entrenar, en orden de fecha y a velocidad configurable: SPEED_DAYS días simulados cada
SPEED_SECONDS segundos reales (por defecto un mes cada 10 segundos). La clave de cada mensaje es
el business_id, así todas las reseñas de un negocio caen en la misma partición y en orden.

El reloj: la reseña con fecha d se publica en el instante real
    inicio + (d - T) / (SPEED_DAYS días) * SPEED_SECONDS
de modo que los huecos entre reseñas se respetan, comprimidos por el mismo factor.

Uso:
    docker compose --profile streaming run --rm producer [--speed-days 30 --speed-seconds 10]
                                                         [--end 2021-07-01] [--limit N]
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta

# lifemap_common.py se copia en la imagen desde spark_batch/ (ver kafka_streaming/Dockerfile):
# la fecha de corte es la misma constante para el entrenamiento, el productor y el streaming.
from lifemap_common import CUTOFF_DATE, DB_NAME, KAFKA_BOOTSTRAP, KAFKA_TOPIC, MONGO_URI

SPEED_DAYS = float(os.getenv("SPEED_DAYS", "30"))
SPEED_SECONDS = float(os.getenv("SPEED_SECONDS", "10"))

# Campos de la reseña que viajan en el mensaje (el texto es lo que clasifica el modelo)
FIELDS = ("review_id", "business_id", "user_id", "stars", "text")
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


# ---------------------------------------------------------------------------
# Funciones puras (probadas con pytest, sin Kafka ni MongoDB)
# ---------------------------------------------------------------------------

def parse_date(value):
    """Fecha de una reseña como datetime: Yelp la trae como texto y la ingesta puede guardarla como Date."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    texto = str(value).strip().replace("Z", "")[:19]   # sin fracciones de segundo ni zona
    for formato in DATE_FORMATS:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise ValueError(f"fecha no reconocida: {value!r}")


def wall_offset(review_dt, cutoff_dt, speed_days, speed_seconds):
    """Segundos reales desde el arranque en que se publica una reseña con fecha review_dt."""
    if speed_days <= 0 or speed_seconds < 0:
        raise ValueError("speed_days debe ser > 0 y speed_seconds >= 0")
    simulados = (review_dt - cutoff_dt).total_seconds()
    return max(simulados, 0.0) / (speed_days * 86400) * speed_seconds


def build_message(doc):
    """(clave, valor) del mensaje: clave = business_id, valor = JSON con la reseña y su fecha ISO."""
    valor = {campo: doc.get(campo) for campo in FIELDS}
    if valor["stars"] is not None:
        valor["stars"] = float(valor["stars"])
    valor["date"] = parse_date(doc["date"]).isoformat(sep=" ")
    clave = str(doc["business_id"]).encode("utf-8")
    return clave, json.dumps(valor, ensure_ascii=False).encode("utf-8")


def date_query(cutoff_dt, end_dt=None, as_string=False):
    """Filtro de MongoDB para date >= T (y < fin), según si `date` está guardada como texto o como Date."""
    def formato(dt):
        return dt.strftime("%Y-%m-%d %H:%M:%S") if as_string else dt

    rango = {"$gte": formato(cutoff_dt)}
    if end_dt is not None:
        rango["$lt"] = formato(end_dt)
    return {"date": rango}


# ---------------------------------------------------------------------------
# Productor
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Productor de reseñas con reloj acelerado")
    parser.add_argument("--end", default=None, help="fecha final, excluida (YYYY-MM-DD); por defecto todas")
    parser.add_argument("--speed-days", type=float, default=SPEED_DAYS, help="días simulados por ventana")
    parser.add_argument("--speed-seconds", type=float, default=SPEED_SECONDS,
                        help="segundos reales por ventana (0 = sin pausas, lo más rápido posible)")
    parser.add_argument("--limit", type=int, default=0, help="máximo de reseñas a publicar (0 = todas)")
    parser.add_argument("--bootstrap", default=KAFKA_BOOTSTRAP)
    parser.add_argument("--topic", default=KAFKA_TOPIC)
    return parser.parse_args()


def produce(producer, topic, key, value):
    """Encola un mensaje; si la cola local está llena espera a que se vacíe y reintenta."""
    while True:
        try:
            producer.produce(topic, key=key, value=value, on_delivery=_on_delivery)
            producer.poll(0)
            return
        except BufferError:
            producer.poll(1)


_errores = []


def _on_delivery(err, _msg):
    if err is not None:
        _errores.append(err)


def run():
    from confluent_kafka import Producer
    from pymongo import ASCENDING, MongoClient

    args = parse_args()
    cutoff_dt = parse_date(CUTOFF_DATE)
    end_dt = parse_date(args.end) if args.end else None

    reviews = MongoClient(MONGO_URI)[DB_NAME].reviews
    print("Asegurando el índice por fecha de reviews (la primera vez tarda un poco)...")
    reviews.create_index([("date", ASCENDING)])

    muestra = reviews.find_one({"date": {"$exists": True}}, {"date": 1})
    if muestra is None:
        raise SystemExit("No hay reseñas en MongoDB: primero hay que ejecutar la ingesta")
    como_texto = isinstance(muestra["date"], str)
    query = date_query(cutoff_dt, end_dt, as_string=como_texto)
    total = reviews.count_documents(query)
    print(f"Reseñas reservadas desde T = {cutoff_dt:%Y-%m-%d}: {total}")
    print(f"Velocidad: {args.speed_days:g} días simulados cada {args.speed_seconds:g} s -> topic "
          f"'{args.topic}' en {args.bootstrap}")

    producer = Producer({
        "bootstrap.servers": args.bootstrap,
        "client.id": "lifemap-producer",
        "enable.idempotence": True,          # sin duplicados si el broker pide reintentos
        "linger.ms": 50,                     # agrupa mensajes en lotes
        "compression.type": "lz4",
        "partitioner": "murmur2_random",     # mismo hash que el cliente Java: business_id -> partición
        "queue.buffering.max.messages": 200000,
    })

    proyeccion = {campo: 1 for campo in (*FIELDS, "date")}
    cursor = reviews.find(query, proyeccion).sort("date", ASCENDING).batch_size(2000)
    if args.limit:
        cursor = cursor.limit(args.limit)

    inicio = time.monotonic()
    enviados = 0
    siguiente_reporte = cutoff_dt + timedelta(days=args.speed_days)
    for doc in cursor:
        if not doc.get("business_id") or not doc.get("text"):
            continue
        fecha = parse_date(doc["date"])
        while fecha >= siguiente_reporte:
            print(f"[reloj {siguiente_reporte:%Y-%m-%d}] {enviados} reseñas publicadas, "
                  f"{time.monotonic() - inicio:.1f} s reales", flush=True)
            siguiente_reporte += timedelta(days=args.speed_days)

        espera = inicio + wall_offset(fecha, cutoff_dt, args.speed_days, args.speed_seconds) - time.monotonic()
        if espera > 0:
            producer.poll(0)
            time.sleep(espera)
        clave, valor = build_message(doc)
        produce(producer, args.topic, clave, valor)
        enviados += 1

    print("Esperando la confirmación de los últimos mensajes...")
    producer.flush(60)
    if _errores:
        raise SystemExit(f"{len(_errores)} mensajes fallaron; el primero: {_errores[0]}")
    print(f"¡Listo! {enviados} reseñas publicadas en '{args.topic}' en {time.monotonic() - inicio:.1f} s")


if __name__ == "__main__":
    run()
