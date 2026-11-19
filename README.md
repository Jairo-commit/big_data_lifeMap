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

## Interfaz web

Un frontend en React y TypeScript muestra las consultas geoespaciales de MongoDB sobre un mapa (cada negocio
es un punto con su ficha al pasar el cursor) y los modelos de sentimiento entrenados (métricas, matrices de
confusión y una prueba en vivo). Necesita la API en marcha y los modelos entrenados.

```bash
docker compose --profile frontend up -d frontend    # http://localhost:3000
```

Más detalles, desarrollo local y decisiones de diseño en [`frontend/README.md`](frontend/README.md).

## Entrega 2: API y dashboard (punto 8)

La API suma los endpoints `/live/hotspots` y `/live/evolution` (ventanas con hotspots), `/alerts` (por radio o polígono), `/survival/<categoría>` y
`/risk/near`, y su `/health` incluye el estado de Kafka y el **retraso de cada consumidor** (offset final del topic menos el procesado). Las tablas se pueden
pedir como CSV con `?format=csv`: es lo que consume el dashboard de Power BI de [`powerbi/`](powerbi/README.md), que trae las consultas de Power Query y una guía
paso a paso para armar las cuatro visualizaciones (mapa de hotspots, alertas activas, curvas de supervivencia y evolución del % negativo). Cada endpoint está
documentado, con ejemplos, en [`api_flask/API.md`](api_flask/API.md).

## Jobs de Spark (Entrega 1, puntos 4 a 6)

Requieren que la ingesta y la vida de los negocios (puntos 2 y 3) ya estén en MongoDB. La vida de
los negocios (GeoJSON, días-negocio, evento y censura) se calcula después de la ingesta, en la imagen
de ingesta, y se puede repetir sin dañar los datos:

```bash
docker compose --profile jobs run --rm business-life
```

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

## Entrega 2: streaming con Kafka

```
MongoDB (reseñas con date >= T) --> producer (reloj acelerado) --> Kafka, topic `reviews`
    (3 particiones, clave business_id) --> Spark Structured Streaming + modelo `sentiment_best`
    --> MongoDB, colección `review_predictions`
```

- **Kafka** (`apache/kafka`, un nodo en modo KRaft, sin ZooKeeper) arranca con `docker compose up`
  junto a mongodb y la API, que siguen en las mismas URL. `kafka-init` crea el topic `reviews` con 3
  particiones (`KAFKA_PARTITIONS`) y termina. Dentro de Compose el broker es `kafka:9092`; desde el
  host, `localhost:9094`.
- **Fecha de corte T = 2021-01-01**: la constante `CUTOFF_DATE` de `spark_batch/lifemap_common.py`,
  la única definición en todo el código. La usan el entrenamiento (date < T), el productor (date >= T; su
  imagen copia ese archivo) y la inferencia en streaming (descarta lo anterior a T), así que no pueden
  usar fechas distintas; para cambiarla se edita ahí y se reconstruyen las
  imágenes y el modelo. Simula un despliegue real: el
  modelo aprende solo del pasado (reseñas con fecha < T) y en streaming clasifica reseñas "futuras" que
  nunca vio. Si el streaming repitiera reseñas del entrenamiento habría fuga de datos y la exactitud
  en streaming no diría nada sobre datos nuevos. Se usa todo el dataset, sin muestreo: lo anterior a T
  entrena y lo posterior a T se transmite.
- **Productor** (`kafka_streaming/producer.py`): lee de MongoDB las reseñas con fecha >= T en orden de
  fecha y las publica con clave `business_id` (todas las reseñas de un negocio van a la misma
  partición, en orden). El reloj acelerado publica cada reseña en el instante
  `(fecha - T) / SPEED_DAYS días * SPEED_SECONDS`: por defecto un mes de reseñas cada 10 segundos.
- **Inferencia** (`spark_batch/streaming_inference.py`): Structured Streaming lee el topic, carga
  `sentiment_best` de la Entrega 1 sin reentrenarlo, clasifica cada reseña y la escribe en
  `review_predictions` (upsert por `review_id`, así un lote repetido no duplica). El checkpoint
  (volumen `spark_checkpoints`) guarda los offsets: al reiniciar continúa donde iba.

```bash
docker compose build
docker compose up -d                       # mongodb, api, kafka (+ topic reviews) e ingesta

# El modelo se entrena solo con las reseñas anteriores a T (una vez)
docker compose up -d spark-master spark-worker
docker compose --profile jobs run --rm spark-jobs spark-submit /app/sentiment_model.py

# Terminal 1: inferencia en streaming (Ctrl+C para detenerla; --timeout 600 la detiene sola)
docker compose --profile jobs run --rm spark-jobs spark-submit /app/streaming_inference.py

# Terminal 2: productor (un mes cada 10 s). Otra velocidad: SPEED_DAYS=7 SPEED_SECONDS=5 docker compose ...
docker compose --profile streaming run --rm producer
# o con argumentos: ... run --rm producer --speed-days 30 --speed-seconds 10 --end 2021-07-01 --limit 10000
```

Comprobaciones:

```bash
# Topic con 3 particiones y mensajes repartidos por clave
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic reviews
docker compose exec kafka /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server localhost:9092 --topic reviews

# Predicciones en MongoDB
docker compose exec mongodb mongosh --quiet lifemap_db --eval \
  'db.review_predictions.countDocuments(); db.review_predictions.findOne()'
```

- Volver a procesar el topic desde el principio: `streaming_inference.py --reset` (borra el checkpoint).
- Volver a publicar: el productor se puede ejecutar otra vez; como `review_predictions` usa
  `review_id` como `_id`, las reseñas repetidas reemplazan a las anteriores.
- Cada documento de `review_predictions` tiene `sentiment`, `probabilities`, `true_sentiment` (según
  las estrellas), `correct`, la fecha de la reseña y la partición y el offset de Kafka.

### Punto 4: ventanas geoespaciales y hotspots

```
Kafka (reviews) --> Spark Structured Streaming + sentiment_best --> celda de geohash del negocio
    --> ventana de 30 días con watermark de 7 días sobre `date` --> MongoDB, colección `geohash_windows`
```

- **Tiempo del evento**: las ventanas y el watermark usan el campo `date` de la reseña (cuándo se escribió), no el
  momento en que llega a Kafka o a Spark. El watermark de 7 días cierra una ventana cuando la fecha más reciente
  vista supera su fin en 7 días y descarta lo que llegue más tarde, así el estado en memoria queda acotado.
- **Alineadas con T**: las ventanas empiezan exactamente en T (`geo_windows.window_offset_days`: 28 días de desplazamiento
  respecto a 1970 con T = 2021-01-01), el mismo reloj del productor. Modo `append`: solo se emiten ventanas cerradas
  (las últimas no cierran hasta que llegue una reseña posterior). Una reseña repetida no se cuenta dos veces
  (`dropDuplicates(review_id)` dentro del watermark).
- Cada ventana cerrada se guarda con el conteo y el porcentaje de reseñas negativas (según el modelo; las negativas por
  estrellas se guardan aparte para contrastar), **la geometría de su celda** (índice 2dsphere, consultable con `$geoWithin` y
  `$geoIntersects`) y la decisión de hotspot. El `_id` es `celda|inicio`: reprocesar no duplica.
- **Hotspot**: una celda lo es cuando su % negativo sube frente a la ventana anterior de la misma celda al menos `threshold_pp`
  puntos y ambas ventanas tienen al menos `min_reviews` reseñas (con 20 reseñas el error estándar de un porcentaje ya llega a
  ±11 puntos). **El umbral sale de los datos**: `calibrate_hotspots.py` mide, con las reseñas anteriores a T, cuánto cambia
  normalmente el % negativo de una celda de un mes al siguiente y toma el **percentil 95** de esas variaciones (queda en
  `hotspot_config`): un hotspot es una subida que solo ocurre 1 de cada 20 veces en condiciones normales. Cada ventana guarda
  `delta_pp`, `is_hotspot` y `hotspot_reason` (hotspot, bajo_umbral, pocas_resenas, sin_ventana_previa...).

```bash
docker compose up -d mongodb kafka kafka-init spark-master spark-worker
docker compose --profile jobs run --rm spark-jobs spark-submit /app/calibrate_hotspots.py      # umbral con el histórico < T

# Terminal 1: ventanas en streaming (--reset borra el checkpoint y las ventanas; --timeout la detiene sola)
docker compose --profile jobs run --rm spark-jobs spark-submit /app/streaming_windows.py --reset --timeout 300
# Terminal 2: productor (3 s por mes simulado hasta septiembre de 2021)
docker compose --profile streaming run --rm producer --speed-seconds 3 --end 2021-09-01

docker compose exec mongodb mongosh --quiet lifemap_db --eval \
  'db.geohash_windows.find({is_hotspot: true}, {geohash: 1, window_start: 1, pct_negative: 1, delta_pp: 1}).sort({delta_pp: -1}).limit(5)'
```

### Punto 5: supervivencia (Kaplan-Meier)

`survival_km.py` calcula curvas de Kaplan-Meier por **categoría principal** y por **zona**, tratando la censura y la entrada tardía
(la lógica pura está en `spark_batch/survival.py`, con pruebas contra un ejemplo de libro de texto).

- **Tiempo y evento**: el tiempo es la vida del negocio, los días entre su primera y su última reseña (el dataset no trae fechas
  de apertura ni de cierre: es una aproximación). Evento = cierre observado (`is_open = 0`). Un negocio abierto está **censurado**:
  solo se sabe que seguía vivo en la fecha de corte del dataset; nunca se descarta ni se cuenta como cierre.
- **Entrada tardía**: la ventana de observación empieza en `--window-start` (por defecto 2010-01-01: las reseñas son escasas antes,
  en 2009 hay la mitad que en 2010 y 12 veces menos que en 2019). Un negocio con primera reseña anterior ya existía cuando empieza
  la observación: entra al conjunto en riesgo con la edad que tenía en esa fecha (`entry_days`). Si se contara desde la edad 0 se
  inflaría la supervivencia, porque los negocios que murieron antes de 2010 no están en los datos. Los que terminan antes de
  esa fecha no se observaron y se excluyen. En riesgo en el instante t: `entrada < t <= salida`.
- **Curvas**: por instante con cierres guardan el tiempo (días), el **número en riesgo**, cierres, censurados, S(t) y su intervalo
  de confianza del 95 % (Greenwood, escala log-log); y por grupo, la **mediana de vida** (`null` si la curva no baja de 0,5), S a 1, 3,
  5 y 10 años y `meets_min` (al menos 100 negocios y 20 cierres: los grupos pequeños no permiten conclusiones).
- **Zonas**: cada zona es un polígono (`zones`; por defecto, el área de las ciudades con más negocios) y los negocios que caen dentro
  se consultan en MongoDB con **`$geoWithin`** sobre `business_survival.location`. `--zones-file` admite zonas propias en GeoJSON.
- Colecciones: `business_survival` (un registro por negocio, con su ubicación), `survival_by_category`, `zones` y `survival_by_zone`.

```bash
docker compose --profile jobs run --rm spark-jobs spark-submit /app/survival_km.py [--window-start 2010-01-01] [--top-zones 10]

docker compose exec mongodb mongosh --quiet lifemap_db --eval \
  'db.survival_by_zone.find({}, {group: 1, n_businesses: 1, n_events: 1, median_years: 1, survival_5y: 1}).toArray()'
```

### Punto 6: modelo de riesgo de cierre

`risk_model.py` es el patrón de KafkaMed aplicado a negocios: con los datos **anteriores a T** se construyen variables por negocio y un
clasificador estima la probabilidad de que cierre en los 12 meses siguientes (la lógica pura está en `spark_batch/risk_logic.py`).

- **Población**: negocios que existían en T (tienen reseñas anteriores a T) y tuvieron actividad desde T; los que no tuvieron actividad
  después de T se excluyen. **Etiqueta**: 1 si el negocio está cerrado (`is_open = 0`) y su última reseña cae entre T y T + 12 meses;
  0 si sigue con actividad después de ese plazo o sigue abierto.
- **Variables** (solo con reseñas < T): sentimiento medio (positiva +1, neutral 0, negativa −1), tendencia del % negativo en los últimos
  6 meses (3 meses recientes menos los 3 anteriores, en puntos; 0 si alguna mitad tiene menos de 5 reseñas), estrellas medias, número de
  reseñas, edad en T y **densidad de competidores de la misma categoría a 500 m con `$geoNear`**. Las estrellas y el número de reseñas se
  recalculan con las reseñas < T: los campos `stars` y `review_count` del negocio son los del corte del dataset e incluirían el futuro.
- **Modelo**: partición 60/20/20 **por negocio** (hash de `business_id`), regresión logística y GBT con pesos de clase (el cierre es la
  clase rara), elegido por **AUC-PR** en validación; el **umbral** maximiza el F1 en validación. En prueba se reportan **AUC-ROC,
  AUC-PR (frente a la prevalencia, que es lo que lograría un modelo sin información) y recall**, precision y matriz de confusión en ese
  umbral. Como control, un modelo entrenado con las etiquetas barajadas (10 barajaduras, se promedian) no debe aprender nada: su AUC-ROC medio debe ser ~0,5 y el del modelo real debe superarlo. La ausencia de fuga temporal se comprueba aparte recalculando las variables con las reseñas < T.
- Resultados: `risk_features` (variables por negocio), `risk_scores` (probabilidad de cierre y alerta con la ubicación del negocio),
  `model_metrics` (`_id: "risk"`) y los modelos en `/app/models/risk_best`, `risk_logistic_regression` y `risk_gbt`.

```bash
docker compose --profile jobs run --rm spark-jobs spark-submit /app/risk_model.py
# Volver a entrenar sin repetir la agregación de reseñas ni los competidores (~2 min en lugar de ~30):
docker compose --profile jobs run --rm spark-jobs spark-submit /app/risk_model.py --from-features

docker compose exec mongodb mongosh --quiet lifemap_db --eval \
  'db.model_metrics.findOne({_id: "risk"}, {mejor_modelo: 1, umbral: 1, prueba: 1})'
```

### Punto 7: alertas de riesgo en streaming

```
Kafka (reviews) --> Spark Structured Streaming + foreachBatch --> variables al instante t --> modelo de riesgo
    --> MongoDB: alerts (geometría, probabilidad, fecha), alert_state y stream_progress
```

`streaming_alerts.py` aplica el modelo de riesgo del punto 6 al flujo. En cada micro-lote (`foreachBatch`), para los negocios que recibieron reseñas:

1. **Actualiza sus variables** (`alerts_logic.features_at`): las seis del modelo (sentimiento medio, tendencia del % negativo en los últimos 6 meses,
   estrellas medias, número de reseñas, edad y competidores a 500 m) al instante de su última reseña, **solo con reseñas de fecha <= t**. La parte anterior
   a T sale de `risk_features` (y de `reviews` con fecha < T para la ventana de la tendencia); la posterior, de las reseñas que llegan por Kafka, guardadas
   por negocio y por `review_id` en `alert_state`: repetir un lote no las cuenta dos veces.
2. **Los puntúa** con `risk_best` (el `PipelineModel` guardado, sin reentrenar).
3. **Guarda en `alerts`** los que superan el umbral (el que eligió el entrenamiento, `model_metrics`; `--threshold` lo anula). Cada negocio es un documento
   (`_id = business_id`) con su **geometría** (Point con índice 2dsphere), la **probabilidad**, la **fecha** del evento, el umbral y las variables con las que se
   puntuó. Si el negocio ya estaba en alerta se actualiza; si baja del umbral se marca `active: false` con su `cleared_date`.
4. Guarda en `stream_progress` los offsets procesados por partición: es la base del retraso del consumidor.

Solo se evalúan los negocios de la población del modelo (los que existían en T); los demás se cuentan en el log y se ignoran. Una alerta es un criterio de
prioridad (el modelo tiene una señal moderada), no una sentencia.

```bash
docker compose up -d mongodb kafka kafka-init spark-master spark-worker
docker compose --profile jobs run --rm spark-jobs spark-submit /app/streaming_alerts.py --reset --timeout 900   # --reset: empieza de cero
docker compose --profile streaming run --rm producer --speed-seconds 3 --end 2021-09-01                          # en otra terminal

docker compose exec mongodb mongosh --quiet lifemap_db --eval \
  'db.alerts.find({active: true}, {business_id: 1, city: 1, probability: 1, alert_date: 1}).sort({probability: -1}).limit(5)'
```
