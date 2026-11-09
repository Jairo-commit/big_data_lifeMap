import os

import pandas as pd
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

def process_business_lifecycle():
    print("Conectando a MongoDB para estructurar GeoJSON y calcular la vida de los negocios...")
    client = MongoClient(MONGO_URI)
    db = client["lifemap_db"]

    # 1. Crear el índice geoespacial 2dsphere requerido por la rúbrica
    db.businesses.create_index([("location", "2dsphere")])
    print("Índice 2dsphere creado exitosamente en la colección businesses.")

    # 2. Transformar negocios a formato GeoJSON y calcular días de vida y censura
    businesses = list(db.businesses.find({}))
    print(f"Procesando {len(businesses)} negocios...")

    for biz in businesses:
        biz_id = biz.get("business_id")
        lat = biz.get("latitude")
        lon = biz.get("longitude")

        # Transformar a estructura GeoJSON estándar de MongoDB. Es idempotente: tras la primera
        # corrida el negocio ya no tiene latitude/longitude, así que se conserva su `location`
        # en lugar de reemplazarla por [0, 0].
        if lat and lon:
            geo_location = {"type": "Point", "coordinates": [float(lon), float(lat)]}
        else:
            geo_location = biz.get("location") or {"type": "Point", "coordinates": [0.0, 0.0]}

        # Buscar las reseñas de este negocio para calcular la vida
        reviews = list(db.reviews.find({"business_id": biz_id}, {"date": 1}))

        if reviews:
            dates = pd.to_datetime([r["date"] for r in reviews])
            first_review = dates.min()
            last_review = dates.max()
            days_business = (last_review - first_review).days
        else:
            days_business = 0

        # Determinar evento y censura según la rúbrica (is_open = 0 es cierre observado, 1 es censurado)
        is_open = biz.get("is_open", 1)
        event = 0 if is_open == 1 else 1  # 1 = cerrado (evento), 0 = abierto (censurado)

        # Actualizar el documento en MongoDB con el GeoJSON y las métricas de vida
        db.businesses.update_one(
            {"_id": biz["_id"]},
            {
                "$set": {
                    "location": geo_location,
                    "days_business": max(days_business, 1),
                    "event": event,
                    "censored": 1 if is_open == 1 else 0
                },
                "$unset": {"latitude": "", "longitude": ""}
            }
        )

    print("¡Modelo de datos, índices geoespaciales y cálculo de vida de los negocios finalizados!")

if __name__ == "__main__":
    process_business_lifecycle()
