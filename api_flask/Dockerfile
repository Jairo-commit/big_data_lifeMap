# API de LifeMap. Parte de la imagen de Spark (la misma base que spark_batch/Dockerfile) porque
# /predict carga el PipelineModel de sentimiento, que solo se puede leer con Spark y Java.
# Spark corre en modo local dentro de la API: no usa el maestro del Compose.
FROM apache/spark:3.5.5-python3

USER root

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

# pyspark viene en la imagen como zip, sin instalar
ENV PYTHONPATH=/opt/spark/python/lib/pyspark.zip:/opt/spark/python/lib/py4j-0.10.9.7-src.zip \
    PYTHONUNBUFFERED=1

# Usuario sin privilegios de la imagen de Spark
USER spark
EXPOSE 5000
CMD ["python3", "app.py"]
