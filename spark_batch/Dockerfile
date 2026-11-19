# Imagen única para el maestro, el worker y los jobs de Spark (sentimiento, tasas, balanceo y,
# en la Entrega 2, la inferencia en streaming desde Kafka).
# - Spark 3.5 con Scala 2.12, compatible con el MongoDB Spark Connector 10.4.
# - Los JAR del conector y del driver de MongoDB se descargan al construir la imagen,
#   para no depender de --packages (ni de internet) al ejecutar los jobs.
# - numpy lo exige MLlib, pandas lo importa pyspark.ml.functions (vector_to_array, en el streaming) y pymongo se usa para índices y colecciones pequeñas; se instalan con uv
#   en el Python del sistema porque la imagen base no tiene proyecto ni entorno virtual.
FROM apache/spark:3.5.5-python3

USER root

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN uv pip install --system --no-cache numpy pandas pymongo

ADD https://repo1.maven.org/maven2/org/mongodb/spark/mongo-spark-connector_2.12/10.4.1/mongo-spark-connector_2.12-10.4.1.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-sync/5.1.4/mongodb-driver-sync-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-core/5.1.4/mongodb-driver-core-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/bson/5.1.4/bson-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/bson-record-codec/5.1.4/bson-record-codec-5.1.4.jar /opt/spark/jars/

# Entrega 2: fuente Kafka de Structured Streaming (misma versión que Spark) y sus dependencias
ADD https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.12/3.5.5/spark-sql-kafka-0-10_2.12-3.5.5.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/apache/spark/spark-token-provider-kafka-0-10_2.12/3.5.5/spark-token-provider-kafka-0-10_2.12-3.5.5.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/apache/kafka/kafka-clients/3.4.1/kafka-clients-3.4.1.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/apache/commons/commons-pool2/2.11.1/commons-pool2-2.11.1.jar /opt/spark/jars/

RUN chmod 644 /opt/spark/jars/mongo*.jar /opt/spark/jars/bson*.jar /opt/spark/jars/*kafka*.jar \
    /opt/spark/jars/commons-pool2-2.11.1.jar

WORKDIR /app
COPY . /app
ENV PYTHONPATH=/app
ENV PATH="/opt/spark/bin:${PATH}"
