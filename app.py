from flask import Flask, request, jsonify, make_response, render_template, g
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime, timezone, timedelta
import certifi
import requests
import json
import hmac
import hashlib
import logging
import os
from config.config_db import (
    AUTHORIZED_TOKENS,
    COLLECTION_NAME,
    CONFIG_NAME,
    DB_NAME,
    MONGO_URI,
    OPENWEATHER_API_KEY,
    SECRET_KEY,
    WEATHER_LOCATION_LAT,
    WEATHER_LOCATION_LON,
)
from pymongo.errors import PyMongoError
from weather_data import (
    finite_number,
    history_report,
    latest_reading,
    parse_timestamp,
    rainfall_report,
    timestamp_stage,
    validate_configuration,
)

from auth import (
    account_store,
    active_data_filter,
    authorized_device,
    configuration_for_device,
    install_authentication,
)

ROUND_HOURLY_RAINFALL_TIME = True

app = Flask(__name__)

CORS(
    app,
    origins=["*"],
    allow_headers=["Content-Type", "Authorization", "X-Signature"],
    methods=["GET", "POST", "OPTIONS"],
)

# Підключення до MongoDB
client = MongoClient(
    MONGO_URI,
    server_api=ServerApi("1"),
    tls=True,
    tlsAllowInvalidCertificates=False,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=10000,
)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]
config = db[CONFIG_NAME]

install_authentication(app, db, AUTHORIZED_TOKENS, config)

logging.basicConfig(level=logging.INFO)


@app.errorhandler(PyMongoError)
def database_unavailable(error):
    app.logger.warning("Database request failed: %s", type(error).__name__)
    return (
        jsonify({"error": "Сховище вимірювань тимчасово недоступне. Повторіть запит пізніше."}),
        503,
    )


def verify_hmac_signature(raw_bytes: bytes, received_signature: str) -> bool:
    """
    Обчислити HMAC SHA256 по сирому payload і порівняти з отриманою сигнатурою.
    received_signature - hex string ("abcd1234...")
    """
    computed = hmac.new(SECRET_KEY, raw_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, received_signature)


def validate_environment(env: dict, config_data: dict):
    alerts = []
    # перевірка типів і значень
    if "temperature" in env:
        try:
            temp = float(env["temperature"])
            tmin = config_data.get("temperature", {}).get("min")
            tmax = config_data.get("temperature", {}).get("max")
            if tmin is not None and temp < tmin:
                alerts.append(f"⚠️ Температура нижче мінімуму: {temp:.2f} < {tmin}")
            if tmax is not None and temp > tmax:
                alerts.append(f"⚠️ Температура вище максимуму: {temp:.2f} > {tmax}")
        except Exception:
            alerts.append("⚠️ Некоректне значення temperature")
    if "humidity" in env:
        try:
            humidity = float(env["humidity"])
            hmin = config_data.get("humidity", {}).get("min")
            hmax = config_data.get("humidity", {}).get("max")
            if hmin is not None and humidity < hmin:
                alerts.append(f"⚠️ Вологість нижче мінімуму: {humidity:.2f} < {hmin}")
            if hmax is not None and humidity > hmax:
                alerts.append(f"⚠️ Вологість вище максимуму: {humidity:.2f} > {hmax}")
        except Exception:
            alerts.append("⚠️ Некоректне значення humidity")
    return alerts


@app.route("/")
def main_page():
    return render_template("index.html")


@app.route("/api/data", methods=["POST"])
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
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        app.logger.error(f"JSON parse error: {str(e)}")
        return jsonify({"error": "Bad JSON"}), 400

    if not isinstance(data, dict):
        return jsonify({"error": "Payload must be a JSON object"}), 400
    for section in ["environment", "air_quality", "rainfall", "system"]:
        if section in data and not isinstance(data[section], dict):
            return jsonify({"error": f"{section} must be an object"}), 400
    if "timestamp" in data and parse_timestamp(data["timestamp"]) is None:
        return jsonify({"error": "Invalid timestamp"}), 400
    data["device_id"] = AUTHORIZED_TOKENS[token]

    # Отримуємо поточну конфігурацію
    config_data = configuration_for_device(data["device_id"])
    alerts = []

    if "environment" in data and isinstance(data["environment"], dict):
        alerts = validate_environment(data["environment"], config_data)

    # Зберігаємо дані
    try:
        if "timestamp" not in data:
            # store as ISO 8601 with timezone (UTC) so clients and queries are unambiguous
            data["timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        collection.insert_one(data)
    except Exception as e:
        app.logger.error(f"DB insert error: {str(e)}")
        return jsonify({"error": "DB error"}), 500

    return jsonify({"status": "success", "alerts": alerts}), 201


@app.route("/api/data", methods=["GET"])
def get_data():
    data = list(
        collection.aggregate(
            [
                {"$match": active_data_filter()},
                timestamp_stage(),
                {"$match": {"observed_at": {"$ne": None}}},
                {"$sort": {"observed_at": -1}},
                {"$limit": 20},
                {"$project": {"_id": 0, "observed_at": 0}},
            ]
        )
    )
    return jsonify(data)


@app.route("/api/data/history", methods=["GET"])
def get_history():
    try:
        hours = int(request.args.get("hours", 24))
    except ValueError:
        return jsonify({"error": "Період має бути цілим числом годин."}), 400
    if not 1 <= hours <= 720:
        return jsonify({"error": "Оберіть період від 1 до 720 годин."}), 400
    return jsonify(history_report(collection, hours, device_filter=active_data_filter()))


@app.route("/api/data/all", methods=["GET"])
def get_all_data():
    data = list(collection.find(active_data_filter(), {"_id": 0}).sort("timestamp", -1))
    return jsonify(data)


@app.route("/api/data/last", methods=["GET"])
def get_last_data():
    reading = latest_reading(collection, device_filter=active_data_filter())
    return jsonify([reading] if reading else [])


# http://127.0.0.1:3000/api/data/stats?days=7
@app.route("/api/data/stats", methods=["GET"])
def get_stats():
    try:
        days = int(request.args.get("days", 1))
        if days < 1:
            return jsonify({"error": "Days must be >= 1"}), 400
    except ValueError:
        return jsonify({"error": "Invalid 'days' parameter"}), 400

    now = datetime.now(timezone.utc)
    past = now - timedelta(days=days)
    past_str = past.replace(microsecond=0).isoformat()

    # Найближчий до часу `past_str`, але не пізніше (≤)
    first = collection.find_one(
        {"$and": [active_data_filter(), {"timestamp": {"$lte": past_str}}]},
        sort=[("timestamp", -1)],
    )

    # Найновіший запис (використаємо поточний час як максимум)
    now_str = now.replace(microsecond=0).isoformat()
    last = collection.find_one(
        {"$and": [active_data_filter(), {"timestamp": {"$lte": now_str}}]}, sort=[("timestamp", -1)]
    )

    rainfall_mm = None
    if first and last:
        t1 = first.get("rainfall", {}).get("tips", 0)
        t2 = last.get("rainfall", {}).get("tips", 0)
        rainfall_mm = round((t2 - t1) * 0.987, 2)

    # Агрегація температури з моменту "past_str" (тобто все, що було після дня назад)
    pipeline = [
        {"$match": active_data_filter()},
        {"$match": {"timestamp": {"$gte": past_str}}},
        {
            "$group": {
                "_id": None,
                "avg_temp": {"$avg": "$environment.temperature"},
                "min_temp": {"$min": "$environment.temperature"},
                "max_temp": {"$max": "$environment.temperature"},
            }
        },
    ]

    stats = list(collection.aggregate(pipeline))
    result = stats[0] if stats else {}
    result["rainfall_mm"] = rainfall_mm
    return jsonify(result), 200


def requested_rainfall(hours, round_hour=False):
    configuration = g.station.get("settings", {})
    interval = configuration.get("system", {}).get("update_interval_ms", 60000)
    return rainfall_report(
        collection, hours, interval, round_hour=round_hour, device_filter=active_data_filter()
    )


@app.route("/api/data/rainfall", methods=["GET"])
def get_rainfall():
    try:
        hours = int(request.args.get("interval", 1))
    except ValueError:
        return jsonify({"error": "Interval must be an integer."}), 400
    if not 1 <= hours <= 168:
        return jsonify({"error": "Interval must be between 1 and 168 hours."}), 400
    report = requested_rainfall(hours)
    complete = all(bucket["complete"] for bucket in report["data"])
    total = sum(bucket["rainfall_mm"] or 0 for bucket in report["data"])
    return jsonify(
        {
            "interval_hours": hours,
            "rainfall_mm": round(total, 2) if complete else None,
            "start_time": report["data"][0]["start_ts"],
            "end_time": report["data"][-1]["end_ts"],
            "complete": complete,
        }
    )


@app.route("/api/data/hourly_rainfall", methods=["GET"])
def get_hourly_rainfall():
    try:
        hours = int(request.args.get("hours", 3))
    except ValueError:
        return jsonify({"error": "Hours must be an integer."}), 400
    if not 1 <= hours <= 168:
        return jsonify({"error": "Hours must be between 1 and 168."}), 400
    return jsonify(requested_rainfall(hours, ROUND_HOURLY_RAINFALL_TIME))


@app.route("/api/config", methods=["GET"])
def get_config():
    device_id = authorized_device(request.headers.get("Authorization", ""))
    configuration = (
        configuration_for_device(device_id)
        if device_id is not None
        else g.station.get("settings", {})
    )
    return jsonify(configuration)


@app.route("/api/config", methods=["POST"])
def update_config():
    try:
        new_configuration = validate_configuration(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    saved = account_store().save_settings(str(g.station["_id"]), g.user["_id"], new_configuration)
    if not saved:
        return jsonify({"error": "Станція більше не належить цьому обліковому запису."}), 403
    return jsonify({"status": "updated"}), 200


@app.route("/time", methods=["GET"])
def get_time():
    try:
        now = datetime.now(timezone.utc)
        response = {
            "unix_time": int(now.timestamp()),
            "iso_datetime": now.replace(microsecond=0).isoformat(),
            "timezone": "UTC",
        }
        resp = make_response(jsonify(response), 200)
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Content-Length"] = str(len(resp.data))
        resp.headers["Connection"] = "close"
        return resp
    except Exception as e:
        app.logger.error(f"Time endpoint error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/weather/forecast", methods=["GET"])
def get_weather_forecast():
    """Keep the legacy URL while retrieving current OpenWeather conditions."""
    if not OPENWEATHER_API_KEY:
        return jsonify({"error": "OpenWeatherMap API key not configured"}), 500

    try:
        # Get location from config or use defaults
        location = g.station.get("settings", {}).get("location", {})

        # Get current weather data
        url = f"https://api.openweathermap.org/data/2.5/weather"
        params = {
            "lat": location.get("latitude", WEATHER_LOCATION_LAT),
            "lon": location.get("longitude", WEATHER_LOCATION_LON),
            "appid": OPENWEATHER_API_KEY,
            "units": "metric",
            "lang": "uk",
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        # print("Weather API response:", data)

        # Extract relevant weather data
        forecast_data = {
            "temperature": data["main"]["temp"],
            "humidity": data["main"]["humidity"],
            "pressure": data["main"]["pressure"],
            "description": data["weather"][0]["description"],
            "timestamp": datetime.fromtimestamp(data["dt"], timezone.utc).isoformat(),
            "location": data["name"],
        }

        return jsonify(forecast_data), 200

    except requests.RequestException as e:
        app.logger.warning("OpenWeather request failed: %s", type(e).__name__)
        return jsonify({"error": "Не вдалося отримати поточну погоду OpenWeather."}), 500
    except Exception as e:
        app.logger.warning("OpenWeather response invalid: %s", type(e).__name__)
        return jsonify({"error": "Внутрішня помилка сервера"}), 500


@app.route("/api/weather/comparison", methods=["GET"])
def get_weather_comparison():
    station = latest_reading(collection, device_filter=active_data_filter())
    if not station:
        return jsonify({"error": "Станція ще не передала вимірювань."}), 404
    reference_response, status = get_weather_forecast()
    if status != 200:
        return reference_response, status
    reference = reference_response.get_json()
    comparison = {
        "timestamp": station["timestamp"],
        "reference_timestamp": reference["timestamp"],
        "forecast_description": reference["description"],
        "location": reference["location"],
    }
    for metric in ["temperature", "humidity", "pressure"]:
        observed = finite_number(station.get("environment", {}).get(metric))
        external = finite_number(reference.get(metric))
        if observed is None or external is None:
            return (
                jsonify(
                    {"error": "Для зіставлення потрібні температура, вологість і тиск обох джерел."}
                ),
                422,
            )
        difference = observed - external
        comparison[metric] = {
            "station": round(observed, 2),
            "forecast": external,
            "difference": round(difference, 1),
            # Retained for older API clients; the interface uses absolute differences.
            "difference_percent": round(difference / external * 100, 1) if external else 0,
        }
    return jsonify(comparison)


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


if __name__ == "__main__":
    from waitress import serve

    port = int(os.environ.get("PORT", "5000"))
    print(f"Starting production server with Waitress on http://0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port)
