"""API de LifeMap: consultas geoespaciales, tasas de cierre y sentimiento sobre MongoDB.

Endpoints:
- GET  /health                 estado de MongoDB, del modelo de sentimiento y de Kafka (con el retraso de los consumidores).
- GET  /businesses/near        negocios cerca de un punto ($near).
                               lat, lon (obligatorios), radius (m, 1000), category, limit (20).
- POST /businesses/within      negocios dentro de un polígono GeoJSON ($geoWithin).
                               Cuerpo: Polygon, MultiPolygon o Feature. Query: category, limit (100).
- GET  /zones/summary          sentimiento medio y tasa de cierre alrededor de un punto ($geoNear).
                               lat, lon (obligatorios), radius (m, 1000), category, min_days (3650).
- GET  /stats/closure          tasas de cierre por categoría o por celda de geohash.
                               by (category | cell), min_days (3650), include_below_min (false),
                               order (desc | asc), limit (20).
- GET  /live/hotspots          hotspots de una ventana de 30 días dentro de un radio (window latest|YYYY-MM-DD, lat, lon, radius).
- GET  /live/evolution         % de reseñas negativas por ventana, en un radio o en todo el dataset.
- GET  /alerts                 alertas de riesgo de cierre por radio; POST /alerts, por polígono GeoJSON.
- GET  /survival               grupos con curva de supervivencia; GET /survival/<nombre>: la curva (by=category|zone).
- GET  /risk/near              riesgo de cierre de los negocios cerca de un punto ($near).
- GET  /models                métricas de los modelos de sentimiento entrenados.
- POST /predict                sentimiento de un texto nuevo. Cuerpo: {"text": "..."}.

Los endpoints de tablas aceptan ?format=csv (lo que consume Power BI). Los errores de parámetros responden 400 con
{"error": "..."}.
"""

import logging
import os
import threading

import pymongo
from flask import Flask, Response, jsonify, request
from pymongo.errors import OperationFailure, PyMongoError

from kafka_monitor import KafkaMonitor, probe_kafka
from live import (
    ALERT_COLUMNS,
    CURVE_COLUMNS,
    EVOLUTION_COLUMNS,
    HOTSPOT_COLUMNS,
    RISK_COLUMNS,
    SURVIVAL_GROUP_COLUMNS,
    SURVIVAL_KINDS,
    alert_row,
    alerts_query,
    evolution_pipeline,
    evolution_row,
    hotspot_row,
    hotspots_query,
    iso,
    parse_format,
    parse_optional_circle,
    parse_state,
    parse_survival_kind,
    parse_window,
    risk_near_query,
    risk_row,
    survival_curve_rows,
    survival_summary,
    to_csv,
)
from queries import (
    BUSINESS_PROJECTION,
    DEFAULT_MIN_BUSINESS_DAYS,
    BadRequest,
    clean_json,
    closure_stats_query,
    format_model_metrics,
    geojson_point,
    haversine_m,
    mark_min_days,
    near_query,
    parse_bool,
    parse_category,
    parse_float,
    parse_int,
    parse_point,
    parse_polygon,
    summarize_zone,
    with_distance,
    within_query,
    zone_summary_pipeline,
)
from sentiment import ModelNotAvailable, SentimentModel, overall_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lifemap-api")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/lifemap_db")
DB_NAME = "lifemap_db"
MAX_RADIUS_M = 50_000
MAX_TEXT_LENGTH = 10_000

# Kafka (Entrega 2): vacío = no configurado (staging), y /health no lo cuenta como fallo
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "reviews")

app = Flask(__name__)
app.json.ensure_ascii = False

# Un solo cliente para toda la API: pymongo mantiene el pool de conexiones
client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
db = client[DB_NAME]
model = SentimentModel()


def read_consumer_progress():
    """Siguiente offset a procesar por partición de cada consumidor: {consumidor: {partición: offset}}.

    - streaming_alerts deja su avance en `stream_progress` (lo escribe cada micro-lote).
    - streaming_inference no guarda avance: se deduce del mayor `kafka_offset` de cada partición en `review_predictions`.
    """
    progress = {}
    alerts = db.stream_progress.find_one({"_id": "streaming_alerts"})
    if alerts and alerts.get("partitions"):
        progress["streaming_alerts"] = alerts["partitions"]
    inference = {}
    for partition in db.review_predictions.distinct("kafka_partition"):
        last = db.review_predictions.find_one(
            {"kafka_partition": partition}, {"kafka_offset": 1}, sort=[("kafka_offset", pymongo.DESCENDING)]
        )
        if last is not None:
            inference[str(partition)] = last["kafka_offset"] + 1
    if inference:
        progress["streaming_inference"] = inference
    return progress


kafka_monitor = KafkaMonitor(KAFKA_BOOTSTRAP, KAFKA_TOPIC, probe_kafka, read_consumer_progress)


def ensure_indexes():
    """Índices que necesitan las consultas. Si ya existen, no hace nada.

    - businesses.location (2dsphere): $near y $geoNear fallan sin él.
    - reviews.business_id: el $lookup de /zones/summary busca las reseñas de cada negocio.
    - alerts.geometry, risk_scores.location, geohash_windows.centroid (2dsphere): /alerts, /risk/near y /live/*.
    - review_predictions (kafka_partition, kafka_offset): el avance de la inferencia para el retraso de /health.
    """
    try:
        db.businesses.create_index([("location", pymongo.GEOSPHERE)])
        db.reviews.create_index("business_id")
        db.alerts.create_index([("geometry", pymongo.GEOSPHERE)])
        db.risk_scores.create_index([("location", pymongo.GEOSPHERE)])
        db.geohash_windows.create_index([("centroid", pymongo.GEOSPHERE)])
        db.geohash_windows.create_index("window_start")
        db.review_predictions.create_index(
            [("kafka_partition", pymongo.ASCENDING), ("kafka_offset", pymongo.DESCENDING)]
        )
        log.info("Índices de MongoDB listos")
    except PyMongoError as e:
        log.warning("No se pudieron crear los índices: %s", e)


@app.errorhandler(BadRequest)
def bad_request(error):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(PyMongoError)
def mongo_error(error):
    log.exception("Error de MongoDB")
    return jsonify({"error": "error de MongoDB", "detail": str(error)}), 503


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        raise BadRequest("el cuerpo debe ser JSON (Content-Type: application/json)")
    return body


@app.route("/health", methods=["GET"])
def health_check():
    try:
        client.admin.command("ping")
        mongo_status = "healthy"
    except Exception as e:
        mongo_status = f"unhealthy: {e!s}"

    healthy = mongo_status == "healthy"
    model_status = model.status()
    kafka = kafka_monitor.snapshot()  # la última foto del hilo de fondo: no espera a Kafka
    body = {
        "status": overall_status(mongo_status, model_status, kafka["status"]),
        "services": {
            "mongodb": mongo_status,
            "sentiment_model": model_status,
            "kafka": kafka["status"],
            "api": "healthy",
        },
        "commit_hash": os.getenv("GIT_COMMIT", "unknown"),
    }
    if kafka_monitor.configured:
        body["kafka"] = {"topic": kafka.get("topic"), "end_offsets": kafka.get("end_offsets", {})}
        body["consumer_lag"] = kafka.get("consumers", {})
    # 503 solo si MongoDB falla: con el modelo roto o Kafka caído la API sigue sirviendo el resto de endpoints y
    # el healthcheck de Docker no debe tumbar el despliegue; el fallo se ve en `status`.
    return jsonify(body), 200 if healthy else 503


@app.route("/businesses/near", methods=["GET"])
def businesses_near():
    lon, lat = parse_point(request.args)
    radius = parse_float(request.args, "radius", default=1000, minimum=1, maximum=MAX_RADIUS_M)
    category = parse_category(request.args)
    limit = parse_int(request.args, "limit", default=20, minimum=1, maximum=200)

    cursor = db.businesses.find(near_query(lon, lat, radius, category), BUSINESS_PROJECTION).limit(limit)
    businesses = [with_distance(clean_json(b), lon, lat) for b in cursor]
    return jsonify(
        {
            "center": {"type": "Point", "coordinates": [lon, lat]},
            "radius_m": radius,
            "category": category,
            "returned": len(businesses),
            "businesses": businesses,
        }
    )


@app.route("/businesses/within", methods=["POST"])
def businesses_within():
    geometry = parse_polygon(json_body())
    category = parse_category(request.args)
    limit = parse_int(request.args, "limit", default=100, minimum=1, maximum=1000)

    query = within_query(geometry, category)
    try:
        total = db.businesses.count_documents(query)
        businesses = [clean_json(b) for b in db.businesses.find(query, BUSINESS_PROJECTION).limit(limit)]
    except OperationFailure as e:
        # Polígonos que MongoDB no acepta (p. ej. bordes que se cruzan)
        raise BadRequest(f"geometría no válida para MongoDB: {e.details.get('errmsg', e)}") from e
    return jsonify(
        {
            "geometry": geometry,
            "category": category,
            "total": total,
            "returned": len(businesses),
            "businesses": businesses,
        }
    )


@app.route("/zones/summary", methods=["GET"])
def zones_summary():
    lon, lat = parse_point(request.args)
    radius = parse_float(request.args, "radius", default=1000, minimum=1, maximum=MAX_RADIUS_M)
    category = parse_category(request.args)
    min_days = parse_int(request.args, "min_days", default=DEFAULT_MIN_BUSINESS_DAYS, minimum=0)

    groups = list(db.businesses.aggregate(zone_summary_pipeline(lon, lat, radius, min_days, category)))
    return jsonify(clean_json(summarize_zone(groups, lon, lat, radius, min_days, category)))


@app.route("/stats/closure", methods=["GET"])
def stats_closure():
    by = request.args.get("by", "category")
    min_days = parse_int(request.args, "min_days", default=DEFAULT_MIN_BUSINESS_DAYS, minimum=0)
    include_below_min = parse_bool(request.args, "include_below_min")
    order = request.args.get("order", "desc")
    limit = parse_int(request.args, "limit", default=20, minimum=1, maximum=1000)

    collection, query, projection, sort = closure_stats_query(by, min_days, include_below_min, order)
    rows = [clean_json(r) for r in db[collection].find(query, projection).sort(sort).limit(limit)]
    return jsonify(
        {
            "by": by,
            "min_business_days": min_days,
            "include_below_min": include_below_min,
            "returned": len(rows),
            "results": mark_min_days(rows, min_days),
        }
    )


def table_response(rows, fmt, name, columns=None, **meta):
    """Filas planas como CSV (Power BI) o como JSON junto con los metadatos de la consulta."""
    if fmt == "csv":
        return Response(
            to_csv(rows, columns),
            mimetype="text/csv",
            headers={"Content-Disposition": f'inline; filename="{name}.csv"'},
        )
    return jsonify(clean_json({**meta, "returned": len(rows), name: rows}))


@app.route("/live/hotspots", methods=["GET"])
def live_hotspots():
    fmt = parse_format(request.args)
    window = parse_window(request.args)
    circle = parse_optional_circle(request.args)
    limit = parse_int(request.args, "limit", default=500, minimum=1, maximum=5000)

    latest = window is None
    if latest:
        newest = db.geohash_windows.find_one({}, {"window_start": 1, "window_end": 1}, sort=[("window_start", -1)])
        window = newest["window_start"] if newest else None
    meta = {"window_start": iso(window), "latest": latest}
    if circle:
        meta.update(center=geojson_point(circle[0], circle[1]), radius_m=circle[2])
    if window is None:  # todavía no hay ventanas cerradas
        return table_response([], fmt, "hotspots", HOTSPOT_COLUMNS, total=0, **meta)

    query = hotspots_query(window, circle)
    projection = {
        "_id": 0,
        "geometry": 1,
        "centroid": 1,
        "geohash": 1,
        "window_start": 1,
        "window_end": 1,
        "n_reviews": 1,
        "n_negative": 1,
        "pct_negative": 1,
        "prev_pct_negative": 1,
        "delta_pp": 1,
        "threshold_pp": 1,
        "is_hotspot": 1,
    }
    docs = list(db.geohash_windows.find(query, projection).sort("delta_pp", pymongo.DESCENDING).limit(limit))
    rows = [hotspot_row(d) for d in docs]
    if fmt == "json":  # la geometría de la celda solo va en JSON; el CSV es tabular
        rows = [dict(row, geometry=d.get("geometry")) for row, d in zip(rows, docs)]
    return table_response(
        rows, fmt, "hotspots", HOTSPOT_COLUMNS, total=db.geohash_windows.count_documents(query), **meta
    )


@app.route("/live/evolution", methods=["GET"])
def live_evolution():
    fmt = parse_format(request.args)
    circle = parse_optional_circle(request.args)
    rows = [evolution_row(g) for g in db.geohash_windows.aggregate(evolution_pipeline(circle))]
    meta = {}
    if circle:
        meta.update(center=geojson_point(circle[0], circle[1]), radius_m=circle[2])
    return table_response(rows, fmt, "windows", EVOLUTION_COLUMNS, **meta)


def list_alerts(circle=None, geometry=None):
    fmt = parse_format(request.args)
    state = parse_state(request.args)
    min_probability = parse_float(request.args, "min_probability", default=0.0, minimum=0, maximum=1)
    limit = parse_int(request.args, "limit", default=1000, minimum=1, maximum=20000)
    query = alerts_query(state, min_probability, circle, geometry)
    try:
        total = db.alerts.count_documents(query)
        docs = list(db.alerts.find(query, {"_id": 0}).sort("probability", pymongo.DESCENDING).limit(limit))
    except OperationFailure as e:
        raise BadRequest(f"geometría no válida para MongoDB: {e.details.get('errmsg', e)}") from e
    meta = {"state": state, "min_probability": min_probability, "total": total}
    if circle:
        meta.update(center=geojson_point(circle[0], circle[1]), radius_m=circle[2])
    if geometry:
        meta["geometry"] = geometry
    return table_response([alert_row(d) for d in docs], fmt, "alerts", ALERT_COLUMNS, **meta)


@app.route("/alerts", methods=["GET"])
def alerts_by_radius():
    return list_alerts(circle=parse_optional_circle(request.args))


@app.route("/alerts", methods=["POST"])
def alerts_by_polygon():
    return list_alerts(geometry=parse_polygon(json_body()))


@app.route("/survival", methods=["GET"])
def survival_groups():
    fmt = parse_format(request.args)
    collection = SURVIVAL_KINDS[parse_survival_kind(request.args)]
    only_reliable = parse_bool(request.args, "meets_min")
    limit = parse_int(request.args, "limit", default=200, minimum=1, maximum=2000)
    query = {"meets_min": True} if only_reliable else {}
    docs = db[collection].find(query, {"curve": 0}).sort("n_businesses", pymongo.DESCENDING).limit(limit)
    return table_response([survival_summary(d) for d in docs], fmt, "groups", SURVIVAL_GROUP_COLUMNS)


@app.route("/survival/<path:name>", methods=["GET"])
def survival_curve(name):
    fmt = parse_format(request.args)
    kind = parse_survival_kind(request.args)
    doc = db[SURVIVAL_KINDS[kind]].find_one({"_id": name})
    if doc is None:
        return jsonify(
            {"error": "survival_not_found", "detail": f"no hay curva de supervivencia para '{name}' (by={kind})"}
        ), 404
    rows = survival_curve_rows(doc)
    if fmt == "csv":
        return table_response(rows, fmt, "curve", CURVE_COLUMNS)
    return jsonify(clean_json({"summary": survival_summary(doc), "returned": len(rows), "curve": rows}))


@app.route("/risk/near", methods=["GET"])
def risk_near():
    fmt = parse_format(request.args)
    lon, lat = parse_point(request.args)
    radius = parse_float(request.args, "radius", default=1000, minimum=1, maximum=MAX_RADIUS_M)
    min_probability = parse_float(request.args, "min_probability", default=0.0, minimum=0, maximum=1)
    limit = parse_int(request.args, "limit", default=100, minimum=1, maximum=5000)
    docs = db.risk_scores.find(risk_near_query(lon, lat, radius, min_probability), {"_id": 0}).limit(limit)
    rows = []
    for doc in docs:
        row = risk_row(doc)
        row["distance_m"] = round(haversine_m(lon, lat, row["lon"], row["lat"]), 1)
        rows.append(row)
    return table_response(
        rows,
        fmt,
        "businesses",
        RISK_COLUMNS,
        center=geojson_point(lon, lat),
        radius_m=radius,
        min_probability=min_probability,
    )


@app.route("/models", methods=["GET"])
def models_info():
    """Métricas de los modelos de sentimiento entrenados (las guarda spark_batch/sentiment_model.py)."""
    info = format_model_metrics(db.model_metrics.find_one({"_id": "sentiment"}))
    if info is None:
        return jsonify(
            {
                "error": "models_not_available",
                "detail": "aún no hay modelos entrenados: ejecuta spark-submit /app/sentiment_model.py",
            }
        ), 404
    return jsonify(clean_json(info))


@app.route("/predict", methods=["POST"])
def predict_sentiment():
    body = json_body()
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise BadRequest("falta 'text' (texto no vacío)")
    if len(text) > MAX_TEXT_LENGTH:
        raise BadRequest(f"'text' supera {MAX_TEXT_LENGTH} caracteres")

    try:
        result = model.predict([text])[0]
    except ModelNotAvailable as e:
        return jsonify(
            {
                "error": "model_not_available",
                "detail": str(e),
                "hint": "entrena el modelo: docker compose --profile jobs run --rm spark-jobs "
                "spark-submit /app/sentiment_model.py",
            }
        ), 503
    return jsonify(result)


if __name__ == "__main__":
    ensure_indexes()
    kafka_monitor.start()
    threading.Thread(target=model.warm_up, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
