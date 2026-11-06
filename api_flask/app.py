import os

import pymongo
from flask import Flask, jsonify, request

app = Flask(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/lifemap_db")

def get_db():
    client = pymongo.MongoClient(MONGO_URI)
    return client["lifemap_db"]

@app.route('/health', methods=['GET'])
def health_check():
    try:
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        client.server_info()
        mongo_status = "healthy"
    except Exception as e:
        mongo_status = f"unhealthy: {e!s}"

    commit_hash = os.getenv("GIT_COMMIT", "unknown")
    return jsonify({
        "status": "ok" if mongo_status == "healthy" else "degraded",
        "services": {"mongodb": mongo_status, "spark": "running", "dask": "running", "api": "healthy"},
        "commit_hash": commit_hash
    }), 200

@app.route('/businesses/near', methods=['GET'])
def businesses_near():
    db = get_db()
    lat = float(request.args.get('lat', 0))
    lon = float(request.args.get('lon', 0))
    max_distance = float(request.args.get('radius', 5000)) # en metros

    query = {
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [lon, lat]},
                "$maxDistance": max_distance
            }
        }
    }
    results = list(db.businesses.find(query, {"_id": 0, "name": 1, "city": 1, "categories": 1, "location": 1}).limit(20))
    return jsonify(results), 200

@app.route('/stats/closure', methods=['GET'])
def stats_closure():
    db = get_db()
    min_days = int(request.args.get('min_days', 365))

    # Agregación para calcular tasa de cierre anualizada por categoría
    pipeline = [
        {"$match": {"days_business": {"$gte": min_days}}},
        {"$group": {
            "_id": "$categories",
            "total_businesses": {"$sum": 1},
            "total_closures": {"$sum": "$event"},
            "total_business_days": {"$sum": "$days_business"}
        }},
        {"$project": {
            "category": "$_id",
            "total_businesses": 1,
            "closure_rate_annualized": {
                "$cond": [
                    {"$eq": ["$total_business_days", 0]},
                    0,
                    {"$multiply": [{"$divide": ["$total_closures", {"$divide": ["$total_business_days", 365]}]}, 100]}
                ]
            }
        }},
        {"$limit": 10}
    ]
    results = list(db.businesses.aggregate(pipeline))
    return jsonify(results), 200

@app.route('/predict', methods=['POST'])
def predict_sentiment():
    data = request.get_json()
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Lógica simplificada de prueba para la API (luego se conecta al modelo de Spark)
    sentiment = "positive" if len(text) > 10 else "neutral"
    return jsonify({"text": text, "predicted_sentiment": sentiment}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
