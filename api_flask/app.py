"""API de LifeMap: consultas geoespaciales, tasas de cierre y sentimiento sobre MongoDB.

Endpoints:
- GET  /health                 estado de MongoDB y del modelo de sentimiento.
- GET  /businesses/near        negocios cerca de un punto ($near).
                               lat, lon (obligatorios), radius (m, 1000), category, limit (20).
- POST /businesses/within      negocios dentro de un polígono GeoJSON ($geoWithin).
                               Cuerpo: Polygon, MultiPolygon o Feature. Query: category, limit (100).
- GET  /zones/summary          sentimiento medio y tasa de cierre alrededor de un punto ($geoNear).
                               lat, lon (obligatorios), radius (m, 1000), category, min_days (3650).
- GET  /stats/closure          tasas de cierre por categoría o por celda de geohash.
                               by (category | cell), min_days (3650), include_below_min (false),
                               order (desc | asc), limit (20).
- POST /predict                sentimiento de un texto nuevo. Cuerpo: {"text": "..."}.

Los errores de parámetros responden 400 con {"error": "..."}.
"""

import logging
import os
import threading

import pymongo
from flask import Flask, jsonify, request
from pymongo.errors import OperationFailure, PyMongoError

from queries import (
    BUSINESS_PROJECTION,
    DEFAULT_MIN_BUSINESS_DAYS,
    BadRequest,
    clean_json,
    closure_stats_query,
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
from sentiment import ModelNotAvailable, SentimentModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lifemap-api")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/lifemap_db")
DB_NAME = "lifemap_db"
MAX_RADIUS_M = 50_000
MAX_TEXT_LENGTH = 10_000

app = Flask(__name__)
app.json.ensure_ascii = False

# Un solo cliente para toda la API: pymongo mantiene el pool de conexiones
client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
db = client[DB_NAME]
model = SentimentModel()


def ensure_indexes():
    """Índices que necesitan las consultas. Si ya existen, no hace nada.

    - businesses.location (2dsphere): $near y $geoNear fallan sin él.
    - reviews.business_id: el $lookup de /zones/summary busca las reseñas de cada negocio.
    """
    try:
        db.businesses.create_index([("location", pymongo.GEOSPHERE)])
        db.reviews.create_index("business_id")
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
    return jsonify({
        "status": "ok" if healthy else "degraded",
        "services": {"mongodb": mongo_status, "sentiment_model": model.status(), "api": "healthy"},
        "commit_hash": os.getenv("GIT_COMMIT", "unknown"),
    }), 200 if healthy else 503


@app.route("/businesses/near", methods=["GET"])
def businesses_near():
    lon, lat = parse_point(request.args)
    radius = parse_float(request.args, "radius", default=1000, minimum=1, maximum=MAX_RADIUS_M)
    category = parse_category(request.args)
    limit = parse_int(request.args, "limit", default=20, minimum=1, maximum=200)

    cursor = db.businesses.find(near_query(lon, lat, radius, category), BUSINESS_PROJECTION).limit(limit)
    businesses = [with_distance(clean_json(b), lon, lat) for b in cursor]
    return jsonify({
        "center": {"type": "Point", "coordinates": [lon, lat]},
        "radius_m": radius,
        "category": category,
        "returned": len(businesses),
        "businesses": businesses,
    })


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
    return jsonify({
        "geometry": geometry,
        "category": category,
        "total": total,
        "returned": len(businesses),
        "businesses": businesses,
    })


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
    return jsonify({
        "by": by,
        "min_business_days": min_days,
        "include_below_min": include_below_min,
        "returned": len(rows),
        "results": mark_min_days(rows, min_days),
    })


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
        return jsonify({
            "error": "model_not_available",
            "detail": str(e),
            "hint": "entrena el modelo: docker compose --profile jobs run --rm spark-jobs "
                    "spark-submit /app/sentiment_model.py",
        }), 503
    return jsonify(result)


if __name__ == "__main__":
    ensure_indexes()
    threading.Thread(target=model.warm_up, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
