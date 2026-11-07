# Imagen única para descargar (download.py) e ingerir (ingest.py) el dataset de Yelp.
# Dependencias instaladas con uv en el Python del sistema (la imagen no tiene proyecto).
FROM python:3.10-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache "dask[complete]" pymongo pandas kagglehub
COPY download.py ingest.py ./
CMD ["sh", "-c", "python download.py && python ingest.py"]
