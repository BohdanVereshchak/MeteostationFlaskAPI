from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime
from config.config_db import *


app = Flask(__name__)
CORS(app)

# Підключення до MongoDB
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
db = client[DB_NAME]
collection = db[COLLECTION_NAME]


@app.route('/')
def hello_world():
    # for web
    return 'Hello, World!'


@app.route('/api/sensors', methods=['POST'])
def receive_data():
    data = request.json
    data['timestamp'] = datetime.now()
    collection.insert_one(data)
    return jsonify({"status": "success"}), 201


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=3000, debug=True)
