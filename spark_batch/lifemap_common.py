"""Utilidades compartidas por los jobs de Spark de LifeMap.

Los imports de pyspark son perezosos (dentro de cada función) para que las funciones puras
(geohash, tasa de cierre) se puedan probar con pytest sin Spark ni Java.
"""

import os
import socket

DB_NAME = "lifemap_db"
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/")
SPARK_MASTER_URL = os.getenv("SPARK_MASTER_URL")
MODELS_DIR = os.getenv("MODELS_DIR", "/app/models")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")

# Precisión del geohash: 6 caracteres son celdas de ~1,2 km x 0,6 km (nivel de barrio).
GEOHASH_PRECISION = int(os.getenv("GEOHASH_PRECISION", "6"))

# Mínimo de días-negocio para comparar tasas entre grupos. 3650 días = 10 años-negocio:
# con menos exposición, un solo cierre mueve la tasa más de 10 puntos porcentuales
# (1 / 10 años = 10 %), y la comparación sería ruido de grupos pequeños.
MIN_BUSINESS_DAYS = int(os.getenv("MIN_BUSINESS_DAYS", "3650"))

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


# ---------------------------------------------------------------------------
# Funciones puras: geohash y tasa de cierre
# ---------------------------------------------------------------------------

def geohash_encode(lat, lon, precision=GEOHASH_PRECISION):
    """Codifica una coordenada como geohash de `precision` caracteres."""
    lat_min, lat_max = -90.0, 90.0
    lon_min, lon_max = -180.0, 180.0
    resultado = []
    bits = 0
    valor = 0
    par = True  # los bits pares codifican la longitud y los impares la latitud
    while len(resultado) < precision:
        if par:
            medio = (lon_min + lon_max) / 2
            if lon >= medio:
                valor = (valor << 1) | 1
                lon_min = medio
            else:
                valor <<= 1
                lon_max = medio
        else:
            medio = (lat_min + lat_max) / 2
            if lat >= medio:
                valor = (valor << 1) | 1
                lat_min = medio
            else:
                valor <<= 1
                lat_max = medio
        par = not par
        bits += 1
        if bits == 5:
            resultado.append(_BASE32[valor])
            bits = 0
            valor = 0
    return "".join(resultado)


def geohash_bbox(geohash):
    """Devuelve (lat_min, lat_max, lon_min, lon_max) de la celda de un geohash."""
    lat_min, lat_max = -90.0, 90.0
    lon_min, lon_max = -180.0, 180.0
    par = True
    for caracter in geohash:
        valor = _BASE32.index(caracter)
        for desplazamiento in (4, 3, 2, 1, 0):
            bit = (valor >> desplazamiento) & 1
            if par:
                medio = (lon_min + lon_max) / 2
                if bit:
                    lon_min = medio
                else:
                    lon_max = medio
            else:
                medio = (lat_min + lat_max) / 2
                if bit:
                    lat_min = medio
                else:
                    lat_max = medio
            par = not par
    return lat_min, lat_max, lon_min, lon_max


def geohash_polygon(geohash):
    """Polígono GeoJSON (anillo cerrado, orden antihorario) de la celda de un geohash."""
    lat_min, lat_max, lon_min, lon_max = geohash_bbox(geohash)
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon_min, lat_min],
            [lon_max, lat_min],
            [lon_max, lat_max],
            [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
    }


def geohash_centroid(geohash):
    """Punto GeoJSON con el centro de la celda de un geohash."""
    lat_min, lat_max, lon_min, lon_max = geohash_bbox(geohash)
    return {"type": "Point", "coordinates": [(lon_min + lon_max) / 2, (lat_min + lat_max) / 2]}


def annualized_closure_rate(closures, business_days):
    """Tasa de cierre anualizada (%) = cierres / (días-negocio / 365) * 100.

    Devuelve None cuando no hay días-negocio, porque la tasa no está definida.
    """
    if not business_days:
        return None
    return closures / (business_days / 365) * 100


def sumar_pares(a, b):
    """Función de reducción: suma componente a componente (cierres, días_negocio)."""
    return (a[0] + b[0], a[1] + b[1])


# ---------------------------------------------------------------------------
# Spark y MongoDB
# ---------------------------------------------------------------------------

def build_spark(app_name, shuffle_partitions=None, adaptive=True):
    """Crea la sesión de Spark conectada al maestro del Compose y al conector de MongoDB."""
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.adaptive.enabled", str(adaptive).lower())
        .config("spark.ui.showConsoleProgress", "false")
    )
    if SPARK_MASTER_URL:
        # En modo cliente los ejecutores deben alcanzar al driver por IP dentro de la red de Compose.
        builder = (
            builder.master(SPARK_MASTER_URL)
            .config("spark.driver.host", socket.gethostbyname(socket.gethostname()))
            .config("spark.driver.bindAddress", "0.0.0.0")
        )
    if shuffle_partitions:
        builder = builder.config("spark.sql.shuffle.partitions", str(shuffle_partitions))

    spark = builder.getOrCreate()
    # Los UDF y las funciones de reducción viven en este módulo: se envían a los ejecutores.
    spark.sparkContext.addPyFile(__file__)
    return spark


def read_collection(spark, name):
    """Lee una colección de lifemap_db con el MongoDB Spark Connector 10.x."""
    return (
        spark.read.format("mongodb")
        .option("connection.uri", MONGO_URI)
        .option("database", DB_NAME)
        .option("collection", name)
        .load()
    )


def write_collection(df, name, mode="overwrite"):
    """Escribe un DataFrame en una colección de lifemap_db."""
    (
        df.write.format("mongodb")
        .mode(mode)
        .option("connection.uri", MONGO_URI)
        .option("database", DB_NAME)
        .option("collection", name)
        .save()
    )


def save_documents(name, documents):
    """Reemplaza el contenido de una colección pequeña con pymongo (resultados de benchmarks)."""
    from pymongo import MongoClient

    coleccion = MongoClient(MONGO_URI)[DB_NAME][name]
    coleccion.delete_many({})
    if documents:
        coleccion.insert_many(documents)


def sentiment_label(stars_col):
    """Etiqueta de sentimiento según las estrellas: 1-2 negativo (0), 3 neutral (1), 4-5 positivo (2)."""
    from pyspark.sql import functions as F

    return (
        F.when(stars_col <= 2, 0.0)
        .when(stars_col == 3, 1.0)
        .otherwise(2.0)
    )


def with_geohash(df, lat_col, lon_col, precision=GEOHASH_PRECISION):
    """Agrega la columna `geohash` calculada con un UDF de Python."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType

    codificar = F.udf(lambda lat, lon: geohash_encode(lat, lon, precision), StringType())
    return df.withColumn("geohash", codificar(F.col(lat_col), F.col(lon_col)))


def load_businesses(spark):
    """Negocios con las columnas que usan las tasas de cierre y el balanceo de carga.

    Devuelve: business_id, city, primary_category, geohash, event, days_business.
    Las coordenadas salen de `location.coordinates` ([lon, lat]) y, si el documento aún
    conserva `latitude`/`longitude`, se usan como respaldo. La categoría principal es la
    primera de la lista `categories` (cadena separada por comas de Yelp).
    """
    from pyspark.sql import functions as F

    negocios = read_collection(spark, "businesses")
    columnas = negocios.columns

    lat = F.col("location.coordinates")[1] if "location" in columnas else F.lit(None)
    lon = F.col("location.coordinates")[0] if "location" in columnas else F.lit(None)
    if "latitude" in columnas and "longitude" in columnas:
        lat = F.coalesce(lat, F.col("latitude").cast("double"))
        lon = F.coalesce(lon, F.col("longitude").cast("double"))

    categoria = F.trim(F.split(F.col("categories"), ",").getItem(0))
    negocios = negocios.select(
        "business_id",
        "city",
        F.coalesce(F.when(categoria != "", categoria), F.lit("Sin categoría")).alias("primary_category"),
        lat.alias("lat"),
        lon.alias("lon"),
        F.col("event").cast("int").alias("event"),
        F.col("days_business").cast("long").alias("days_business"),
    )
    negocios = negocios.where(
        F.col("lat").isNotNull() & F.col("lon").isNotNull()
        & F.col("event").isNotNull() & F.col("days_business").isNotNull()
    )
    negocios = with_geohash(negocios, "lat", "lon")
    return negocios.select(
        "business_id", "city", "primary_category", "geohash", "event", "days_business"
    )


def mapreduce_closures(df, key_col, num_partitions=None):
    """MapReduce con RDD: emite (clave, (cierre, días_negocio)) y suma con reduceByKey."""
    pares = df.rdd.map(lambda r: (r[key_col], (int(r["event"]), int(r["days_business"]))))
    return pares.reduceByKey(sumar_pares, num_partitions)


def groupby_closures(df, key_col):
    """Mismo cálculo con DataFrames (groupBy), para validar el resultado del RDD."""
    from pyspark.sql import functions as F

    return df.groupBy(key_col).agg(
        F.count("*").alias("n_businesses"),
        F.sum("event").alias("closures"),
        F.sum("days_business").alias("business_days"),
    )
