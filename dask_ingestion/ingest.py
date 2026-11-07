import os

import dask
import dask.dataframe as dd
from pymongo import ASCENDING, MongoClient
from pymongo.errors import BulkWriteError

DATA_DIR = os.getenv("DATA_DIR", "/data/raw")
BUSINESS_FILE = os.getenv("BUSINESS_FILE", f"{DATA_DIR}/yelp_academic_dataset_business.json")
REVIEW_FILE = os.getenv("REVIEW_FILE", f"{DATA_DIR}/yelp_academic_dataset_review.json")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
FORCE_INGEST = os.getenv("FORCE_INGEST", "0") == "1"
BATCH_SIZE = 10_000


def insert_partition(pdf, mongo_uri, collection):
    """Insert one cleaned partition; duplicate keys (unique index) are ignored."""
    if pdf.empty:
        return 0
    coll = MongoClient(mongo_uri)["lifemap_db"][collection]
    records = pdf.to_dict("records")
    inserted = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        try:
            inserted += len(coll.insert_many(batch, ordered=False).inserted_ids)
        except BulkWriteError as e:
            inserted += e.details["nInserted"]
    return inserted


def run_ingestion():
    db = MongoClient(MONGO_URI)["lifemap_db"]

    if FORCE_INGEST:
        print("FORCE_INGEST=1: dropping existing collections...")
        db.businesses.drop()
        db.reviews.drop()
    elif db.businesses.estimated_document_count() and db.reviews.estimated_document_count():
        print("Data already ingested in MongoDB, skipping (FORCE_INGEST=1 to reload).")
        return

    # Unique keys replace a global drop_duplicates: no shuffle, bounded memory.
    db.businesses.create_index([("business_id", ASCENDING)], unique=True)
    db.reviews.create_index([("review_id", ASCENDING)], unique=True)

    print("Iniciando lectura particionada con Dask...")
    df_business = dd.read_json(BUSINESS_FILE, lines=True, blocksize="16MB")
    df_review = dd.read_json(REVIEW_FILE, lines=True, blocksize="16MB")

    # 1. Limpieza de negocios: coordenadas válidas y eliminación de nulos
    df_business = df_business.dropna(subset=["business_id", "latitude", "longitude"])
    df_business = df_business[
        (df_business["latitude"] >= -90)
        & (df_business["latitude"] <= 90)
        & (df_business["longitude"] >= -180)
        & (df_business["longitude"] <= 180)
    ]

    # 2. Limpieza de reseñas: descartar reseñas sin texto (duplicadas: índice único)
    df_review = df_review.dropna(subset=["review_id", "business_id", "text"])
    df_review = df_review[df_review["text"].str.strip() != ""]

    # Cada partición se inserta en MongoDB al terminar de limpiarse: no se carga todo en memoria.
    for name, df in (("businesses", df_business), ("reviews", df_review)):
        parts = [dask.delayed(insert_partition)(p, MONGO_URI, name) for p in df.to_delayed()]
        total = sum(dask.compute(*parts))
        print(f"Insertados {total} documentos en {name}")

    print("¡Ingesta y limpieza completadas con éxito!")


if __name__ == "__main__":
    run_ingestion()
