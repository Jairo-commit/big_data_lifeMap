# big_data_lifeMap

## Jobs de Spark (Entrega 1, puntos 4 a 6)

Requieren que la ingesta y la vida de los negocios (puntos 2 y 3) ya estén en MongoDB.

```bash
docker compose build
docker compose up -d mongodb spark-master spark-worker

# Punto 4: sentimiento (Naive Bayes y regresión logística, partición por negocio)
docker compose --profile jobs run --rm spark-jobs spark-submit /app/sentiment_model.py

# Punto 5: MapReduce y tasas de cierre por categoría y por celda de geohash
docker compose --profile jobs run --rm spark-jobs spark-submit /app/closure_rates.py

# Punto 6: balanceo de carga (2, 8, 32 y 200 particiones, 3 repeticiones)
docker compose --profile jobs run --rm spark-jobs spark-submit /app/load_balancing.py --reps 3
```

La UI del maestro de Spark queda en http://localhost:8081.

- Modelos: volumen `spark_models` (`/app/models`); `sentiment_best` es el que carga la Entrega 2.
- Resultados: colecciones `closure_by_category`, `closure_by_geohash`, `model_metrics`,
  `benchmark_runs`, `benchmark_summary` y `partition_skew`; CSV y JSON en el volumen `spark_output`.
- Celdas de geohash de precisión 6 (`GEOHASH_PRECISION`, ~1,2 km x 0,6 km).
- Mínimo de días-negocio para comparar tasas: 3650 (`MIN_BUSINESS_DAYS`). Con 10 años-negocio un
  solo cierre equivale a una tasa de 10 %; con menos exposición la tasa sería ruido de grupos pequeños.
  Los grupos bajo el mínimo se guardan con `meets_min_days = false` en vez de eliminarse.
