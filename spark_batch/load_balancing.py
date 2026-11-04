"""Punto 6 de la Entrega 1: balanceo de carga.

Mide la operación del punto 5 (repartir, emitir (clave, (cierre, días_negocio)) y sumar con
reduceByKey por categoría y por geohash) con 2, 8, 32 y 200 particiones, con repeticiones, y
cuenta filas por partición con spark_partition_id() para explicar el sesgo.

Se comparan tres repartos:
- sin_clave: repartition(n), reparto uniforme (round-robin).
- ciudad: repartition(n, "city"), todas las filas de una ciudad van a la misma partición.
- categoria: repartition(n, "primary_category"), igual pero por categoría principal.

Uso:
    spark-submit /app/load_balancing.py [--reps 3] [--partitions 2 8 32 200]
"""

import argparse
import csv
import os
import statistics
import time

from pyspark.sql import functions as F

from lifemap_common import (
    OUTPUT_DIR,
    build_spark,
    load_businesses,
    mapreduce_closures,
    save_documents,
)

ESTRATEGIAS = {"sin_clave": None, "ciudad": "city", "categoria": "primary_category"}
CLAVES_TASA = ("primary_category", "geohash")


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark de particiones de LifeMap")
    parser.add_argument("--reps", type=int, default=3, help="repeticiones medidas por configuración (mín. 3)")
    parser.add_argument("--partitions", type=int, nargs="+", default=[2, 8, 32, 200])
    args = parser.parse_args()
    if args.reps < 3:
        parser.error("la guía exige al menos 3 repeticiones por configuración")
    return args


def repartir(df, n, estrategia):
    """Reparte el DataFrame en n particiones, con o sin clave."""
    columna = ESTRATEGIAS[estrategia]
    return df.repartition(n) if columna is None else df.repartition(n, columna)


def operacion(df, n, estrategia):
    """La operación del punto 5 completa: repartir, emitir y sumar con reduceByKey por cada clave."""
    repartido = repartir(df, n, estrategia)
    for clave in CLAVES_TASA:
        mapreduce_closures(repartido, clave, n).collect()


def medir(df, n, estrategia, reps):
    """Una corrida de calentamiento (descartada) y `reps` corridas cronometradas, en segundos."""
    operacion(df, n, estrategia)
    tiempos = []
    for _ in range(reps):
        inicio = time.perf_counter()
        operacion(df, n, estrategia)
        tiempos.append(time.perf_counter() - inicio)
    return tiempos


def filas_por_particion(df, n, estrategia):
    """Filas en cada una de las n particiones (las vacías cuentan como 0)."""
    filas = (repartir(df, n, estrategia)
             .groupBy(F.spark_partition_id().alias("partition_id")).count().collect())
    conteos = {fila["partition_id"]: fila["count"] for fila in filas}
    return [conteos.get(i, 0) for i in range(n)]


def skew_stats(conteos):
    media = statistics.mean(conteos)
    return {
        "min_rows": min(conteos),
        "max_rows": max(conteos),
        "mean_rows": media,
        "std_rows": statistics.pstdev(conteos),
        "empty_partitions": sum(1 for c in conteos if c == 0),
        # Cuántas veces la partición más cargada excede a la media: 1,0 es un reparto perfecto.
        "max_over_mean": max(conteos) / media if media else 0.0,
    }


def write_csv(nombre, filas):
    os.makedirs(f"{OUTPUT_DIR}/benchmarks", exist_ok=True)
    with open(f"{OUTPUT_DIR}/benchmarks/{nombre}.csv", "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def run_load_balancing():
    args = parse_args()
    # AQE desactivado: si no, Spark fusionaría particiones y el conteo 2/8/32/200 no sería real.
    spark = build_spark("LifeMap-LoadBalancing", adaptive=False)

    df = load_businesses(spark).cache()
    total = df.count()  # materializa la caché: la lectura de MongoDB no entra en las mediciones
    print(f"Filas (negocios) a repartir: {total}")

    corridas, resumen, particiones = [], [], []
    for n in args.partitions:
        spark.conf.set("spark.sql.shuffle.partitions", str(n))
        for estrategia in ESTRATEGIAS:
            print(f"Midiendo n={n}, reparto={estrategia}...")
            tiempos = medir(df, n, estrategia, args.reps)
            conteos = filas_por_particion(df, n, estrategia)

            for rep, t in enumerate(tiempos, start=1):
                corridas.append({"partitions": n, "strategy": estrategia, "rep": rep, "seconds": t})
            particiones += [
                {"partitions": n, "strategy": estrategia, "partition_id": i, "rows": c}
                for i, c in enumerate(conteos)
            ]
            resumen.append({
                "partitions": n,
                "strategy": estrategia,
                "reps": len(tiempos),
                "mean_s": statistics.mean(tiempos),
                "std_s": statistics.stdev(tiempos),
                "min_s": min(tiempos),
                "max_s": max(tiempos),
                **skew_stats(conteos),
            })

    save_documents("benchmark_runs", corridas)
    save_documents("benchmark_summary", resumen)
    save_documents("partition_skew", particiones)
    write_csv("benchmark_runs", corridas)
    write_csv("benchmark_summary", resumen)
    write_csv("partition_skew", particiones)

    print("\n| particiones | reparto | media (s) | desv. (s) | mín (s) | máx (s) "
          "| filas mín | filas máx | vacías | máx/media |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in resumen:
        print(f"| {r['partitions']} | {r['strategy']} | {r['mean_s']:.2f} | {r['std_s']:.2f} "
              f"| {r['min_s']:.2f} | {r['max_s']:.2f} | {r['min_rows']} | {r['max_rows']} "
              f"| {r['empty_partitions']} | {r['max_over_mean']:.2f} |")

    print(f"\nCSV en {OUTPUT_DIR}/benchmarks/ y colecciones benchmark_runs, "
          "benchmark_summary y partition_skew en MongoDB.")
    spark.stop()


if __name__ == "__main__":
    run_load_balancing()
