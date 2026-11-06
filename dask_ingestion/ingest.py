import os
import zipfile

import dask.dataframe as dd
from pymongo import MongoClient
from pymongo.errors import BulkWriteError

# Los archivos del dataset de Yelp en Kaggle (yelp-dataset/yelp-dataset). Si no están en DATA_DIR,
# se descargan con las credenciales KAGGLE_USERNAME y KAGGLE_KEY; las siguientes veces se reutilizan.
KAGGLE_DATASET = "yelp-dataset/yelp-dataset"
DATA_DIR = os.getenv("DATA_DIR", "/data")
BUSINESS_FILE = os.getenv("BUSINESS_FILE", os.path.join(DATA_DIR, "yelp_academic_dataset_business.json"))
REVIEW_FILE = os.getenv("REVIEW_FILE", os.path.join(DATA_DIR, "yelp_academic_dataset_review.json"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")


def download_if_missing(path):
    """Descarga un archivo del dataset de Kaggle si aún no está en DATA_DIR."""
    if os.path.exists(path):
        print(f"{path} ya está descargado")
        return
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    name = os.path.basename(path)
    print(f"Descargando {name} de Kaggle...")
    api.dataset_download_file(KAGGLE_DATASET, name, path=os.path.dirname(path))
    # Kaggle entrega los archivos grandes comprimidos
    zipped = path + ".zip"
    if os.path.exists(zipped):
        with zipfile.ZipFile(zipped) as z:
            z.extractall(os.path.dirname(path))
        os.remove(zipped)


def insert_partitions(df, collection):
    """Inserta un DataFrame de Dask partición por partición, para no tenerlo entero en memoria.

    El índice único de la colección descarta los documentos repetidos: si la ingesta se vuelve
    a ejecutar, no duplica datos.
    """
    inserted = 0
    for partition in df.to_delayed():
        records = partition.compute().to_dict("records")
        if not records:
            continue
        try:
            inserted += len(collection.insert_many(records, ordered=False).inserted_ids)
        except BulkWriteError as e:
            if any(error["code"] != 11000 for error in e.details["writeErrors"]):
                raise  # algo distinto de un duplicado
            inserted += e.details["nInserted"]
    return inserted


def run_ingestion():
    download_if_missing(BUSINESS_FILE)
    download_if_missing(REVIEW_FILE)

    print("Iniciando lectura particionada con Dask...")

    # Lectura particionada de JSON con Dask
    df_business = dd.read_json(BUSINESS_FILE, blocksize="16MB")
    df_review = dd.read_json(REVIEW_FILE, blocksize="16MB")

    # 1. Limpieza de negocios: coordenadas válidas y eliminación de nulos
    df_business = df_business.dropna(subset=['business_id', 'latitude', 'longitude'])
    df_business = df_business[
        (df_business['latitude'] >= -90) & (df_business['latitude'] <= 90) &
        (df_business['longitude'] >= -180) & (df_business['longitude'] <= 180)
    ]

    # 2. Limpieza de reseñas: descartar reseñas sin texto. Las duplicadas las descarta el
    #    índice único de review_id al insertar
    df_review = df_review.dropna(subset=['review_id', 'business_id', 'text'])
    df_review = df_review[df_review['text'].str.strip() != '']

    # Conexión a MongoDB
    client = MongoClient(MONGO_URI)
    db = client["lifemap_db"]
    db.businesses.create_index("business_id", unique=True)
    db.reviews.create_index("review_id", unique=True)
    db.reviews.create_index("business_id")  # el punto 3 busca las reseñas de cada negocio

    print("Insertando negocios en MongoDB...")
    print(f"{insert_partitions(df_business, db.businesses)} negocios nuevos")

    print("Insertando reseñas en MongoDB...")
    print(f"{insert_partitions(df_review, db.reviews)} reseñas nuevas")

    print("¡Ingesta y limpieza completadas con éxito!")


if __name__ == "__main__":
    run_ingestion()
