# syntax=docker/dockerfile:1
# Imagen única para descargar (download.py) e ingerir (ingest.py) el dataset de Yelp.
# Dependencias instaladas con uv en el Python del sistema (la imagen no tiene proyecto).
#
# `docker compose build` descarga el dataset a /data/raw dentro de la imagen si hay credenciales de
# Kaggle (secrets de BuildKit: no quedan en la imagen ni en su historial). Sin credenciales el
# build sigue y `dataset` lo descarga al arrancar. Un volumen con nombre vacío en /data/raw se
# rellena con estos archivos la primera vez, así que `up` no vuelve a descargar nada.
FROM python:3.10-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache "dask[complete]" pymongo pandas kagglehub
COPY download.py ./
RUN --mount=type=secret,id=kaggle_api_token,required=false \
    --mount=type=secret,id=kaggle_username,required=false \
    --mount=type=secret,id=kaggle_key,required=false \
    sh -c 'for s in kaggle_api_token kaggle_username kaggle_key; do \
        if [ -s /run/secrets/$s ]; then export "$(echo $s | tr a-z A-Z)=$(cat /run/secrets/$s)"; fi; \
    done; python download.py --if-credentials'
COPY ingest.py ./
CMD ["sh", "-c", "python download.py && python ingest.py"]
