# big_data_lifeMap

## Dataset de Yelp e ingesta (puntos 2 y 3)

El dataset completo es [yelp-dataset/yelp-dataset](https://www.kaggle.com/datasets/yelp-dataset/yelp-dataset)
(~7 M de reseñas; solo se bajan `business` y `review`, ~5,5 GB).

- **`docker compose build`** descarga los archivos `yelp_academic_dataset_business.json` y
  `yelp_academic_dataset_review.json` dentro de la imagen `lifemap-ingest` (secrets de BuildKit: el
  token no queda en la imagen). Sin credenciales el build sigue y se descarga al arrancar.
- **`docker compose up`** ejecuta `dataset`, que valida los archivos (existen, no están vacíos, JSON
  válido y la descarga terminó) y solo los descarga si faltan o están incompletos, y después `ingest`,
  que carga todo en MongoDB con Dask por particiones (memoria acotada). `ingest` se omite si ya hay
  datos cargados.

```bash
# Credenciales de Kaggle (https://www.kaggle.com/settings): en el shell o en un .env local (no se sube a git)
export KAGGLE_API_TOKEN=...            # o KAGGLE_USERNAME y KAGGLE_KEY

docker compose build      # descarga el dataset a la imagen
docker compose up -d      # valida, ingiere en MongoDB y arranca el resto
```

- El volumen `yelp_data` (`/data/raw`) se rellena con los archivos de la imagen la primera vez.
  Para usar una carpeta local con los archivos ya descargados: `YELP_DATA_DIR=./data/raw`.
- `FORCE_INGEST=1` borra `businesses` y `reviews` y vuelve a cargarlos.
- Sin credenciales y sin datos, `dataset` falla con un mensaje claro. En Jenkins se usa la
  credencial `kaggle` (stages *Build images*, *Deploy* e *Ingest*).

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

# Al terminar, apagar Spark (y Dask) para liberar memoria: `docker compose up` solo deja mongodb y api
# (con los nombres: un `stop` sin nombres apaga también mongodb y la API)
docker compose stop spark-master spark-worker dask-scheduler dask-worker-1 dask-worker-2
```

Spark tiene poca memoria por defecto (worker 1 GB, driver y ejecutor 768 MB). Para un job pesado se
sube por variables, p. ej. `SPARK_WORKER_MEMORY=2g SPARK_EXECUTOR_MEMORY=1536m docker compose ...`.

La UI del maestro de Spark queda en http://localhost:8081.


- Modelos: volumen `spark_models` (`/app/models`); `sentiment_best` es el que carga la Entrega 2.
- Resultados: colecciones `closure_by_category`, `closure_by_geohash`, `model_metrics`,
  `benchmark_runs`, `benchmark_summary` y `partition_skew`; CSV y JSON en el volumen `spark_output`.
- Celdas de geohash de precisión 6 (`GEOHASH_PRECISION`, ~1,2 km x 0,6 km).
- Mínimo de días-negocio para comparar tasas: 3650 (`MIN_BUSINESS_DAYS`). Con 10 años-negocio un
  solo cierre equivale a una tasa de 10 %; con menos exposición la tasa sería ruido de grupos pequeños.
  Los grupos bajo el mínimo se guardan con `meets_min_days = false` en vez de eliminarse.
