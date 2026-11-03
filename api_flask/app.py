from flask import Flask, jsonify
import pymongo
import os

app = Flask(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/lifemap_db")

@app.route('/health', methods=['GET'])
def health_check():
    # Verificación del estado de MongoDB
    try:
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        client.server_info()
        mongo_status = "healthy"
    except Exception as e:
        mongo_status = f"unhealthy: {str(e)}"

    # Puedes inyectar el hash del commit mediante una variable de entorno configurada en Jenkins
    commit_hash = os.getenv("GIT_COMMIT", "unknown")

    status_data = {
        "status": "ok" if mongo_status == "healthy" else "degraded",
        "services": {
            "mongodb": mongo_status,
            "spark": "running",
            "dask": "running",
            "api": "healthy"
        },
        "commit_hash": commit_hash
    }
    return jsonify(status_data), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
