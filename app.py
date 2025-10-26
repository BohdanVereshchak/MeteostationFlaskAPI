from flask import Flask, request, jsonify, make_response, redirect, url_for
from flask_socketio import SocketIO, emit

import urllib.parse
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from config.config_db import *
from datetime import datetime, timezone, timedelta
import time
from flask import render_template

import requests

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")  # Ініціалізація

CORS(app, origins=["*"], allow_headers=["Content-Type"], methods=["GET", "POST", "OPTIONS"])

# Підключення до MongoDB
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
db = client[DB_NAME]
collection = db[COLLECTION_NAME]
config = db[CONFIG_NAME]

weather_station_data = []

# @app.route('/')
# def hello_world():
#     # for web
#     return 'Hello, World!'

@app.route('/')
def main_page():
    return render_template("index.html")


@app.route('/api/data', methods=['POST'])
def receive_data():
    data = request.json

    # Отримуємо поточну конфігурацію
    config_data = config.find_one({}, {'_id': 0})

    # Перевіряємо межі значень
    alerts = []

    if 'environment' in data:
        env = data['environment']

        # Перевірка температури
        if 'temperature' in env and 'temperature' in config_data:
            temp = env['temperature']
            temp_config = config_data['temperature']

            if temp_config.get('min') is not None and temp < temp_config['min']:
                alerts.append(f"⚠️ Температура нижче мінімуму: {temp:.2f} < {temp_config['min']}")
            if temp_config.get('max') is not None and temp > temp_config['max']:
                alerts.append(f"⚠️ Температура вище максимуму: {temp:.2f} > {temp_config['max']}")

        # Перевірка вологості
        if 'humidity' in env and 'humidity' in config_data:
            humidity = env['humidity']
            humidity_config = config_data['humidity']

            if humidity_config.get('min') is not None and humidity < humidity_config['min']:
                alerts.append(f"⚠️ Вологість нижче мінімуму: {humidity:.2f} < {humidity_config['min']}")
            if humidity_config.get('max') is not None and humidity > humidity_config['max']:
                alerts.append(f"⚠️ Вологість вище максимуму: {humidity:.2f} > {humidity_config['max']}")

    # Зберігаємо дані
    collection.insert_one(data)

    if alerts:
        for a in alerts:
            socketio.emit('alert', {'message': a})

    return jsonify({
        "status": "success",
        "alerts": alerts
    }), 201

@app.route('/api/data', methods=['GET'])
def get_data():
    data = list(collection.find({}, {'_id': 0}).sort('timestamp', -1).limit(20))
    print("Fetched data:", data)
    return jsonify(data)

@app.route('/api/data/all', methods=['GET'])
def get_all_data():
    data = list(collection.find({}, {'_id': 0}).sort('timestamp', -1))
    return jsonify(data)

@app.route('/api/data/last', methods=['GET'])
def get_last_data():
    data = list(collection.find({}, {'_id': 0}).sort('timestamp', -1).limit(1))
    return jsonify(data)

# http://127.0.0.1:3000/api/data/stats?days=7
@app.route('/api/data/stats', methods=['GET'])
def get_stats():
    try:
        days = int(request.args.get('days', 1))
        if days < 1:
            return jsonify({"error": "Days must be >= 1"}), 400
    except ValueError:
        return jsonify({"error": "Invalid 'days' parameter"}), 400

    now = datetime.now()
    past = now - timedelta(days=days)
    past_str = past.strftime("%Y-%m-%d %H:%M:%S")

    # Найближчий до часу `past_str`, але не пізніше (≤)
    first = collection.find_one(
        {"timestamp": {"$lte": past_str}},
        sort=[("timestamp", -1)]
    )

    # Найновіший запис (використаємо поточний час як максимум)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    last = collection.find_one(
        {"timestamp": {"$lte": now_str}},
        sort=[("timestamp", -1)]
    )

    rainfall_mm = None
    if first and last:
        t1 = first.get("rainfall", {}).get("tips", 0)
        t2 = last.get("rainfall", {}).get("tips", 0)
        rainfall_mm = round((t2 - t1) * 0.987, 2)

    # Агрегація температури з моменту "past_str" (тобто все, що було після дня назад)
    pipeline = [
        {"$match": {"timestamp": {"$gte": past_str}}},
        {"$group": {
            "_id": None,
            "avg_temp": {"$avg": "$environment.temperature"},
            "min_temp": {"$min": "$environment.temperature"},
            "max_temp": {"$max": "$environment.temperature"},
        }}
    ]

    stats = list(collection.aggregate(pipeline))
    result = stats[0] if stats else {}
    result["rainfall_mm"] = rainfall_mm
    return jsonify(result), 200

@app.route('/api/data/rainfall', methods=['GET'])
def get_rainfall():
    try:
        # Get interval from query params (in hours)
        interval_hours = int(request.args.get('interval', 1))
        if interval_hours < 1:
            return jsonify({"error": "Interval must be >= 1 hour"}), 400
    except ValueError:
        return jsonify({"error": "Invalid 'interval' parameter"}), 400

    now = datetime.now()
    past = now - timedelta(hours=interval_hours)
    past_str = past.strftime("%Y-%m-%d %H:%M:%S")

    # Find the closest record to the past time (<=)
    first = collection.find_one(
        {"timestamp": {"$lte": past_str}},
        sort=[("timestamp", -1)]
    )

    # Find the most recent record (<= now)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    last = collection.find_one(
        {"timestamp": {"$lte": now_str}},
        sort=[("timestamp", -1)]
    )

    rainfall_mm = 0
    if first and last:
        t1 = first.get("rainfall", {}).get("tips", 0)
        t2 = last.get("rainfall", {}).get("tips", 0)
        rainfall_mm = round((t2 - t1) * 0.987, 2)

    return jsonify({
        "interval_hours": interval_hours,
        "rainfall_mm": rainfall_mm,
        "start_time": first["timestamp"] if first else None,
        "end_time": last["timestamp"] if last else None
    }), 200

@app.route('/api/data/hourly_rainfall', methods=['GET'])
def get_hourly_rainfall():
    try:
        # Кількість годин для аналізу (за замовчуванням 24)
        hours = int(request.args.get('hours', 6))
        if hours < 1:
            return jsonify({"error": "Hours must be >= 1"}), 400
    except ValueError:
        return jsonify({"error": "Invalid 'hours' parameter"}), 400

    now = datetime.now(tz=timezone.utc)
    now = now.astimezone(timezone(timedelta(hours=3)))  # Перетворення на український час (UTC+3)
    data_points = []
    offset = timedelta(hours=3)  # Український час (UTC+3)
    for i in range(hours, 0, -1):
        end_time = now - timedelta(hours=i-1)-timedelta(hours=3)
        start_time = now - timedelta(hours=i)-timedelta(hours=3)

        end_with_offset = end_time + offset

        start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

        # Знаходимо найближчі записи до початку та кінця годинного інтервалу
        start_record = collection.find_one(
            {"timestamp": {"$lte": start_str}},
            sort=[("timestamp", -1)]
        )
        end_record = collection.find_one(
            {"timestamp": {"$lte": end_str}},
            sort=[("timestamp", -1)]
        )

        rainfall_mm = 0
        if start_record and end_record:
            t1 = start_record.get("rainfall", {}).get("tips", 0)
            t2 = end_record.get("rainfall", {}).get("tips", 0)
            rainfall_mm = round((t2 - t1) * 0.987, 2)

        data_points.append({
            "hour": end_with_offset.hour,
            "rainfall_mm": rainfall_mm,
            "time_label": end_with_offset.strftime("%H:%M")
        })

    return jsonify({
        "hours": hours,
        "data": data_points
    }), 200

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


@app.route('/api/weather/forecast', methods=['GET'])
def get_weather_forecast():
    """Get weather forecast from OpenWeatherMap API"""
    if not OPENWEATHER_API_KEY:
        return jsonify({"error": "OpenWeatherMap API key not configured"}), 500

    try:
        # Get current weather data
        url = f"https://api.openweathermap.org/data/2.5/weather"
        params = {
            'lat': WEATHER_LOCATION_LAT,
            'lon': WEATHER_LOCATION_LON,
            'appid': OPENWEATHER_API_KEY,
            'units': 'metric'
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Extract relevant weather data
        forecast_data = {
            'temperature': data['main']['temp'],
            'humidity': data['main']['humidity'],
            'pressure': data['main']['pressure'],
            'description': data['weather'][0]['description'],
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'location': data['name']
        }

        return jsonify(forecast_data), 200

    except requests.RequestException as e:
        app.logger.error(f"Weather API error: {str(e)}")
        return jsonify({"error": "Помилка отримання даних прогнозу погоди"}), 500
    except Exception as e:
        app.logger.error(f"Forecast error: {str(e)}")
        return jsonify({"error": "Внутрішня помилка сервера"}), 500


@app.route('/api/weather/comparison', methods=['GET'])
def get_weather_comparison():
    """Compare weather station data with forecast"""
    try:
        # Get latest weather station data from MongoDB
        station_data = collection.find_one({}, {'_id': 0}, sort=[('timestamp', -1)])

        if not station_data:
            return jsonify({"error": "No weather station data found in database"}), 404

        # Get weather forecast
        forecast_response = get_weather_forecast()
        if forecast_response[1] != 200:
            return forecast_response

        forecast_data = forecast_response[0].get_json()

        # Calculate differences
        station_temp = station_data['environment']['temperature']
        station_humidity = station_data['environment']['humidity']
        station_pressure = station_data['environment']['pressure']

        forecast_temp = forecast_data['temperature']
        forecast_humidity = forecast_data['humidity']
        forecast_pressure = forecast_data['pressure']

        comparison = {
            'timestamp': station_data['timestamp'],
            'temperature': {
                'station': round(station_temp, 2),
                'forecast': forecast_temp,
                'difference': round(station_temp - forecast_temp, 1),
                'difference_percent': round(((station_temp - forecast_temp) / forecast_temp) * 100,
                                            1) if forecast_temp != 0 else 0
            },
            'humidity': {
                'station': round(station_humidity, 2),
                'forecast': forecast_humidity,
                'difference': round(station_humidity - forecast_humidity, 1),
                'difference_percent': round(((station_humidity - forecast_humidity) / forecast_humidity) * 100,
                                            1) if forecast_humidity != 0 else 0
            },
            'pressure': {
                'station': round(station_pressure, 2),
                'forecast': forecast_pressure,
                'difference': round(station_pressure - forecast_pressure, 1),
                'difference_percent': round(((station_pressure - forecast_pressure) / forecast_pressure) * 100,
                                            1) if forecast_pressure != 0 else 0
            },
            'forecast_description': forecast_data['description'],
            'location': forecast_data['location']
        }

        return jsonify(comparison), 200

    except Exception as e:
        app.logger.error(f"Comparison error: {str(e)}")
        return jsonify({"error": "Помилка порівняння даних"}), 500

# Шлях для сторінок
@app.route("/web", methods=["GET"])
def index_page():
    return render_template("index.html")

@app.route("/web/history")
def history_page():
    return render_template("history.html")

@app.route("/web/settings")
def settings_page():
    return render_template("settings.html")

@app.route("/web/comparison")
def comparison_page():
    return render_template("comparison.html")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=3000, debug=True, allow_unsafe_werkzeug=True)


