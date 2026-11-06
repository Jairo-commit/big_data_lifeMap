FROM python:3.10-slim
WORKDIR /app
# kaggle: descarga el dataset de Yelp si aún no está en /data
RUN pip install --no-cache-dir dask[complete] pymongo pandas kaggle==1.6.17
COPY ingest.py .
CMD ["python", "ingest.py"]
