FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir dask[complete] pymongo pandas
COPY ingest.py .
CMD ["python", "ingest.py"]
