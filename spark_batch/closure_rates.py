"""Punto 5 de la Entrega 1: MapReduce y tasas de cierre.

Con RDD se emite (clave, (cierre, días_negocio)) y se suma con reduceByKey, por categoría
principal y por celda de geohash. El resultado se valida contra un groupBy de DataFrames y se
guarda en las colecciones closure_by_category y closure_by_geohash; esta última incluye el
porcentaje de reseñas negativas por celda y la geometría de la celda (índice 2dsphere).

Uso:
    spark-submit /app/closure_rates.py
"""

from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from lifemap_common import (
    DB_NAME,
    GEOHASH_PRECISION,
    MIN_BUSINESS_DAYS,
    MONGO_URI,
    annualized_closure_rate,
    build_spark,
    geohash_centroid,
    geohash_polygon,
    groupby_closures,
    load_businesses,
    mapreduce_closures,
    read_collection,
    write_collection,
)

POINT_SCHEMA = StructType([
    StructField("type", StringType()),
    StructField("coordinates", ArrayType(DoubleType())),
])
POLYGON_SCHEMA = StructType([
    StructField("type", StringType()),
    StructField("coordinates", ArrayType(ArrayType(ArrayType(DoubleType())))),
])


def validate(rdd_result, df_result, clave):
    """Compara reduceByKey contra groupBy y falla si difieren en cierres o días-negocio."""
    desde_rdd = dict(rdd_result.collect())
    desde_df = {
        fila[clave]: (int(fila["closures"]), int(fila["business_days"]))
        for fila in df_result.collect()
    }
    diferencias = [
        k for k in desde_rdd.keys() | desde_df.keys() if desde_rdd.get(k) != desde_df.get(k)
    ]
    print(f"[{clave}] {len(desde_rdd)} claves en RDD, {len(desde_df)} en groupBy, "
          f"{len(diferencias)} discrepancias RDD vs groupBy")
    if diferencias:
        raise RuntimeError(f"reduceByKey no coincide con groupBy en {clave}: {diferencias[:5]}")
    return desde_rdd


def build_rates(spark, df, clave, df_result, desde_rdd):
    """Tasa anualizada por clave a partir de las sumas del RDD y el conteo del groupBy."""
    n_negocios = {fila[clave]: int(fila["n_businesses"]) for fila in df_result.collect()}
    filas = []
    for k, (cierres, dias) in desde_rdd.items():
        filas.append((
            k, n_negocios[k], int(cierres), int(dias),
            annualized_closure_rate(cierres, dias),
            dias >= MIN_BUSINESS_DAYS, MIN_BUSINESS_DAYS,
        ))
    esquema = StructType([
        StructField(clave, StringType()),
        StructField("n_businesses", LongType()),
        StructField("closures", LongType()),
        StructField("business_days", LongType()),
        StructField("closure_rate", DoubleType()),
        StructField("meets_min_days", StringType()),
        StructField("min_business_days", LongType()),
    ])
    # meets_min_days se crea como texto para evitar inferencia y se castea a booleano.
    resultado = spark.createDataFrame(
        [(*f[:5], str(f[5]), f[6]) for f in filas], esquema
    )
    return resultado.withColumn("meets_min_days", F.col("meets_min_days") == "True")


def negative_pct_by_cell(spark, negocios):
    """Reseñas totales, negativas (1-2 estrellas) y porcentaje negativo por celda de geohash."""
    resenas = read_collection(spark, "reviews").select("business_id", "stars")
    celdas = negocios.select("business_id", "geohash")
    return (
        resenas.join(celdas, "business_id")
        .groupBy("geohash")
        .agg(
            F.count("*").alias("n_reviews"),
            F.sum(F.when(F.col("stars") <= 2, 1).otherwise(0)).alias("n_negative"),
        )
        .withColumn("pct_negative", F.col("n_negative") / F.col("n_reviews") * 100)
    )


def run_closure_rates():
    spark = build_spark("LifeMap-ClosureRates")

    negocios = load_businesses(spark).cache()
    print(f"Negocios con vida y coordenadas válidas: {negocios.count()}")
    print(f"Mínimo de días-negocio para comparar tasas: {MIN_BUSINESS_DAYS}")

    # --- Por categoría principal ---
    rdd_cat = mapreduce_closures(negocios, "primary_category")
    df_cat = groupby_closures(negocios, "primary_category")
    sumas_cat = validate(rdd_cat, df_cat, "primary_category")
    por_categoria = (
        build_rates(spark, negocios, "primary_category", df_cat, sumas_cat)
        .withColumnRenamed("primary_category", "category")
    )
    write_collection(por_categoria, "closure_by_category")

    # --- Por celda de geohash ---
    rdd_geo = mapreduce_closures(negocios, "geohash")
    df_geo = groupby_closures(negocios, "geohash")
    sumas_geo = validate(rdd_geo, df_geo, "geohash")
    por_celda = build_rates(spark, negocios, "geohash", df_geo, sumas_geo)

    poligono = F.udf(geohash_polygon, POLYGON_SCHEMA)
    centroide = F.udf(geohash_centroid, POINT_SCHEMA)
    por_celda = (
        por_celda
        .join(negative_pct_by_cell(spark, negocios), "geohash", "left")
        .withColumn("geohash_precision", F.lit(GEOHASH_PRECISION))
        .withColumn("geometry", poligono("geohash"))
        .withColumn("centroid", centroide("geohash"))
    )
    write_collection(por_celda, "closure_by_geohash")

    # El modo overwrite recrea la colección, así que los índices se crean después de escribir.
    from pymongo import GEOSPHERE, MongoClient
    db = MongoClient(MONGO_URI)[DB_NAME]
    db.closure_by_geohash.create_index([("geometry", GEOSPHERE)])
    db.closure_by_geohash.create_index([("centroid", GEOSPHERE)])
    db.closure_by_geohash.create_index("geohash")
    db.closure_by_category.create_index("category")

    print("\nTop 10 categorías con mayor tasa de cierre (cumpliendo el mínimo de días-negocio):")
    (por_categoria.where("meets_min_days").orderBy(F.desc("closure_rate"))
     .select("category", "n_businesses", "closures", "business_days", "closure_rate")
     .show(10, truncate=False))

    print("¡Tasas de cierre por categoría y por celda guardadas con éxito!")
    spark.stop()


if __name__ == "__main__":
    run_closure_rates()
