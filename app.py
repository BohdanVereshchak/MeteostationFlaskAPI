from flask import Flask, request, jsonify, make_response, render_template
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import certifi
import requests
import json
import hmac
import hashlib
import logging
from config.config_db import *
from functools import wraps

ROUND_HOURLY_RAINFALL_TIME = True

app = Flask(__name__)

CORS(app, origins=["*"], allow_headers=["Content-Type", "Authorization", "X-Signature"], methods=["GET", "POST", "OPTIONS"])

# Підключення до MongoDB
client = MongoClient(
    MONGO_URI,
    server_api=ServerApi('1'),
    tls=True,
    tlsAllowInvalidCertificates=False,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=10000
)   
db = client[DB_NAME]
collection = db[COLLECTION_NAME]
config = db[CONFIG_NAME]

logging.basicConfig(level=logging.INFO)

def verify_hmac_signature(raw_bytes: bytes, received_signature: str) -> bool:
    """
    Обчислити HMAC SHA256 по сирому payload і порівняти з отриманою сигнатурою.
    received_signature - hex string ("abcd1234...")
    """
    computed = hmac.new(SECRET_KEY, raw_bytes, hashlib.sha256).hexdigest()
    # Використовуємо secure compare
    return hmac.compare_digest(computed, received_signature)

def require_token(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "")
        if token not in AUTHORIZED_TOKENS:
            return jsonify({"error": "Unauthorized - invalid token"}), 401
        # attach device id or user info if потрібно
        request.device_id = AUTHORIZED_TOKENS[token]
        return f(*args, **kwargs)
    return wrapper

def validate_environment(env: dict, config_data: dict):
    alerts = []
    # перевірка типів і значень
    if 'temperature' in env:
        try:
            temp = float(env['temperature'])
            tmin = config_data.get('temperature', {}).get('min')
            tmax = config_data.get('temperature', {}).get('max')
            if tmin is not None and temp < tmin:
                alerts.append(f"⚠️ Температура нижче мінімуму: {temp:.2f} < {tmin}")
            if tmax is not None and temp > tmax:
                alerts.append(f"⚠️ Температура вище максимуму: {temp:.2f} > {tmax}")
        except Exception:
            alerts.append("⚠️ Некоректне значення temperature")
    if 'humidity' in env:
        try:
            humidity = float(env['humidity'])
            hmin = config_data.get('humidity', {}).get('min')
            hmax = config_data.get('humidity', {}).get('max')
            if hmin is not None and humidity < hmin:
                alerts.append(f"⚠️ Вологість нижче мінімуму: {humidity:.2f} < {hmin}")
            if hmax is not None and humidity > hmax:
                alerts.append(f"⚠️ Вологість вище максимуму: {humidity:.2f} > {hmax}")
        except Exception:
            alerts.append("⚠️ Некоректне значення humidity")
    return alerts

# Helper: get cumulative rain "tips" value at or before given ISO timestamp (returns (tips, timestamp))
def get_latest_tips_before_or_equal(ts_iso: str):
    """
    Return (tips_value, record_timestamp) for the latest record with timestamp <= ts_iso.
    If none found, return (0, None).
    
    This function handles two timestamp formats stored as strings:
    1. Correct ISO format: "2025-10-30T22:00:00+00:00"
    2. Legacy 'space' format: "2025-10-30 22:00:00"
    """
    
    rec = None
    try:
        dt_obj = datetime.fromisoformat(ts_iso)
        legacy_ts_str = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
        rec = collection.find_one(
            {"timestamp": {"$not": {"$regex": "T"}, "$lte": legacy_ts_str}},
            sort=[("timestamp", -1)]
        )

        if not rec:
            return 0, None
        
        tips = rec.get("rainfall", {}).get("tips", 0)
        try:
            tips = float(tips)
        except Exception:
            tips = 0
        return tips, rec.get("timestamp")
    
    except Exception as e:
        app.logger.error(f"FATAL ERROR in get_latest_tips_before_or_equal: {e}")
        return 0, None

@app.route('/')
def main_page():
    return render_template("index.html")


@app.route('/api/data', methods=['POST'])
def receive_data():
    token = request.headers.get("Authorization", "")
    if token not in AUTHORIZED_TOKENS:
        return jsonify({"error": "Unauthorized - invalid token"}), 401
    
    received_sig = request.headers.get("X-Signature", "")
    if not received_sig:
        return jsonify({"error": "Missing signature"}), 401

    raw = request.get_data()  # bytes
    if not verify_hmac_signature(raw, received_sig):
        return jsonify({"error": "Invalid signature"}), 401

    try:
        data = json.loads(raw.decode('utf-8'))
    except Exception as e:
        app.logger.error(f"JSON parse error: {str(e)}")
        return jsonify({"error": "Bad JSON"}), 400

    data['device_id'] = AUTHORIZED_TOKENS[token]

    # Отримуємо поточну конфігурацію
    config_data = config.find_one({}, {'_id': 0}) or {}
    alerts = []

    if 'environment' in data and isinstance(data['environment'], dict):
        alerts = validate_environment(data['environment'], config_data)

    # Зберігаємо дані
    try:
        if 'timestamp' not in data:
            # store as ISO 8601 with timezone (UTC) so clients and queries are unambiguous
            data['timestamp'] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        collection.insert_one(data)
    except Exception as e:
        app.logger.error(f"DB insert error: {str(e)}")
        return jsonify({"error": "DB error"}), 500

    return jsonify({
        "status": "success",
        "alerts": alerts
    }), 201

@app.route('/api/data', methods=['GET'])
def get_data():
    data = list(collection.find({}, {'_id': 0}).sort('timestamp', -1).limit(20))
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

    now = datetime.now(timezone.utc)
    past = now - timedelta(days=days)
    past_str = past.replace(microsecond=0).isoformat()

    # Найближчий до часу `past_str`, але не пізніше (≤)
    first = collection.find_one(
        {"timestamp": {"$lte": past_str}},
        sort=[("timestamp", -1)]
    )

    # Найновіший запис (використаємо поточний час як максимум)
    now_str = now.replace(microsecond=0).isoformat()
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

    now = datetime.now(timezone.utc).replace(microsecond=0)
    past = (now - timedelta(hours=interval_hours)).replace(microsecond=0)

    past_str = past.isoformat()
    now_str = now.isoformat()

    # Get cumulative tips at or before past and now (fallback to 0)
    t1, t1_ts = get_latest_tips_before_or_equal(past_str)
    t2, t2_ts = get_latest_tips_before_or_equal(now_str)

    # Convert tips difference to mm (sensor factor 0.987) and clamp to >= 0
    rainfall_mm = round(max(0.0, (t2 - t1) * 0.987), 2)

    return jsonify({
        "interval_hours": interval_hours,
        "rainfall_mm": rainfall_mm,
        "start_time": t1_ts,
        "end_time": t2_ts
    }), 200

@app.route('/api/data/hourly_rainfall', methods=['GET'])
def get_hourly_rainfall():
    try:
        # Кількість годин для аналізу (за замовчуванням 3)
        hours = int(request.args.get('hours', 3))
        if hours < 1:
            return jsonify({"error": "Hours must be >= 1"}), 400
    except ValueError:
        return jsonify({"error": "Invalid 'hours' parameter"}), 400

    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    if ROUND_HOURLY_RAINFALL_TIME:
        # ВАРІАНТ 1 (True): Заокруглюємо час ДО НАСТУПНОЇ ГОДИНИ
        if now_utc.minute > 0 or now_utc.second > 0:
            now_utc = (now_utc + timedelta(hours=1)).replace(minute=0, second=0)
        else:
            now_utc = now_utc

    data_points = []
    for i in range(hours, 0, -1):
        end_time_utc = now_utc - timedelta(hours=i-1)
        start_time_utc = now_utc - timedelta(hours=i)

        start_str = start_time_utc.isoformat()
        end_str = end_time_utc.isoformat()

        # cumulative tips at or before start and end
        t_start, ts_start = get_latest_tips_before_or_equal(start_str)
        t_end, ts_end = get_latest_tips_before_or_equal(end_str)

        rainfall_mm = round(max(0.0, (t_end - t_start) * 0.987), 2)

        kyiv_label_time = end_time_utc.astimezone(ZoneInfo("Europe/Kyiv"))
        data_points.append({
            "hour": kyiv_label_time.hour,
            "rainfall_mm": rainfall_mm,
            "time_label": kyiv_label_time.strftime("%H:%M"),
            "start_ts": ts_start,
            "end_ts": ts_end
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
        now = datetime.now(timezone.utc)
        response = {
             "unix_time": int(now.timestamp()),
             "iso_datetime": now.replace(microsecond=0).isoformat(),
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
        # Get location from config or use defaults
        config_data = config.find_one({}, {'_id': 0})
        location = config_data.get('location', {}) if config_data else {}
        
        # Get current weather data
        url = f"https://api.openweathermap.org/data/2.5/weather"
        params = {
            'lat': location.get('latitude', WEATHER_LOCATION_LAT),
            'lon': location.get('longitude', WEATHER_LOCATION_LON),
            'appid': OPENWEATHER_API_KEY,
            'units': 'metric'
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        print("Weather API response:", data)

        # Extract relevant weather data
        forecast_data = {
             'temperature': data['main']['temp'],
             'humidity': data['main']['humidity'],
             'pressure': data['main']['pressure'],
             'description': data['weather'][0]['description'],
             'timestamp': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
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
    app.run(host='0.0.0.0', port=8080, debug=True, ssl_context=('cert.pem', 'key.pem'))


