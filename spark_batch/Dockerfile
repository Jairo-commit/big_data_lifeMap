# Imagen única para el maestro, el worker y los jobs de Spark (sentimiento, tasas y balanceo).
# - Spark 3.5 con Scala 2.12, compatible con el MongoDB Spark Connector 10.4.
# - Los JAR del conector y del driver de MongoDB se descargan al construir la imagen,
#   para no depender de --packages (ni de internet) al ejecutar los jobs.
# - numpy lo exige MLlib, pymongo se usa para índices y colecciones pequeñas y pandas para la vida
#   de los negocios (process_business_life.py); se instalan con uv
#   en el Python del sistema porque la imagen base no tiene proyecto ni entorno virtual.
FROM apache/spark:3.5.5-python3

USER root

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN uv pip install --system --no-cache numpy pymongo pandas

ADD https://repo1.maven.org/maven2/org/mongodb/spark/mongo-spark-connector_2.12/10.4.1/mongo-spark-connector_2.12-10.4.1.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-sync/5.1.4/mongodb-driver-sync-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-core/5.1.4/mongodb-driver-core-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/bson/5.1.4/bson-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/bson-record-codec/5.1.4/bson-record-codec-5.1.4.jar /opt/spark/jars/

RUN chmod 644 /opt/spark/jars/mongo*.jar /opt/spark/jars/bson*.jar

WORKDIR /app
COPY . /app
ENV PYTHONPATH=/app
ENV PATH="/opt/spark/bin:${PATH}"
