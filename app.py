from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from config.config_db import *
from datetime import datetime, timezone
import time


app = Flask(__name__)
CORS(app)

# Підключення до MongoDB
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
db = client[DB_NAME]
collection = db[COLLECTION_NAME]
config = db[CONFIG_NAME]


@app.route('/')
def hello_world():
    # for web
    return 'Hello, World!'


@app.route('/api/data', methods=['POST'])
def receive_data():
    data = request.json
    data['timestamp'] = datetime.now()
    collection.insert_one(data)
    return jsonify({"status": "success"}), 201


@app.route('/api/data', methods=['GET'])
def get_data():
    data = list(collection.find({}, {'_id': 0}).sort('timestamp', -1))
    return jsonify(data)


# http://127.0.0.1:3000/api/data/stats?days=7
@app.route('/api/data/stats', methods=['GET'])
def get_stats():
    from datetime import timedelta

    try:
        days = int(request.args.get('days', 1))  # значення за замовчуванням — 1 день
        if days < 1:
            return jsonify({"error": "Days must be >= 1"}), 400
    except ValueError:
        return jsonify({"error": "Invalid 'days' parameter"}), 400

    now = datetime.now()
    past = now - timedelta(days=days)

# Добавити інші дані
    pipeline = [
        {"$match": {"timestamp": {"$gte": past}}},
        {"$group": {
            "_id": None,
            "avg_temp": {"$avg": "$environment.temperature"},
            "min_temp": {"$min": "$environment.temperature"},
            "max_temp": {"$max": "$environment.temperature"},
        }}
    ]
    stats = list(collection.aggregate(pipeline))
    return jsonify(stats[0] if stats else {}), 200


@app.route('/api/config', methods=['GET'])
def get_config():
    result = config.find_one({}, {'_id': 0})
    if result:
        return jsonify(result)
    else:
        return jsonify({"error": "No config found"}), 404


@app.route('/api/config', methods=['POST'])
def update_config():
    new_config = request.json
    config.update_one({}, {'$set': new_config}, upsert=True)
    return jsonify({"status": "updated"}), 200


@app.route("/time", methods=["GET"])
def get_time():
    try:
        now = datetime.now()
        response = {
            "unix_time": int(now.timestamp()),
            "iso_datetime": now.isoformat(timespec='seconds'),
            "timezone": "UTC"
        }
        resp = make_response(jsonify(response), 200)
        resp.headers['Content-Type'] = 'application/json'
        resp.headers['Content-Length'] = str(len(resp.data))
        resp.headers['Connection'] = 'close'
        return resp
    except Exception as e:
        app.logger.error(f"Time endpoint error: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=3000, debug=True)
