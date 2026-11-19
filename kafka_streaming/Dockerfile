# Entrega 2: imagen del productor de Kafka (lee las reseñas reservadas de MongoDB y las publica).
# Dependencias instaladas con uv en el Python del sistema (la imagen no tiene proyecto).
FROM python:3.10-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache confluent-kafka pymongo
# Se construye desde la raíz del repo (docker-compose.yml) para copiar las constantes compartidas
# (fecha de corte T, MongoDB, Kafka) de spark_batch/ sin duplicarlas. Dockerfile.dockerignore limita
# el contexto a los archivos que copia (el dataset en data/ no se envía al build).
COPY spark_batch/lifemap_common.py kafka_streaming/producer.py kafka_streaming/smoke_publish.py ./
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "producer.py"]
