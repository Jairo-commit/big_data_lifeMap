import os
import dask.dataframe as dd
from pymongo import MongoClient

# Configuración de rutas (ajusta según la ubicación de tus archivos descargados)
BUSINESS_FILE = os.getenv("BUSINESS_FILE", "business.json")
REVIEW_FILE = os.getenv("REVIEW_FILE", "review.json")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

def run_ingestion():
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

    # 2. Limpieza de reseñas: descartar reseñas sin texto o duplicadas
    df_review = df_review.dropna(subset=['review_id', 'business_id', 'text'])
    df_review = df_review[df_review['text'].str.strip() != '']
    df_review = df_review.drop_duplicates(subset=['review_id'])

    # Convertir a Pandas para inserción por lotes en MongoDB (o computar particiones)
    print("Calculando y limpiando datos con Dask...")
    pdf_business = df_business.compute()
    pdf_review = df_review.compute()

    # Conexión a MongoDB
    client = MongoClient(MONGO_URI)
    db = client["lifemap_db"]

    print(f"Insertando {len(pdf_business)} negocios en MongoDB...")
    if not pdf_business.empty:
        db.businesses.insert_many(pdf_business.to_dict('records'))

    print(f"Insertando {len(pdf_review)} reseñas en MongoDB...")
    if not pdf_review.empty:
        db.reviews.insert_many(pdf_review.to_dict('records'))

    print("¡Ingesta y limpieza completadas con éxito!")

if __name__ == "__main__":
    run_ingestion()
