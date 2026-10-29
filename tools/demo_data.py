"""Deterministic local fixtures. Never imports the real database configuration."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from math import sin
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch

from weather_data import finite_number, parse_timestamp, rainfall_buckets


class MemoryConfiguration:
    def __init__(self):
        self.value = {
            "system": {"update_interval_ms": 60000},
            "location": {"latitude": 49.8815, "longitude": 24.0929},
            "temperature": {"min": 0, "max": 35},
            "humidity": {"min": 0, "max": 100},
        }

    def find_one(self, *args, **kwargs):
        return deepcopy(self.value)

    def update_one(self, query, update, **kwargs):
        for field, value in update["$set"].items():
            section, name = field.split(".")
            self.value.setdefault(section, {})[name] = value


class MemoryReadings:
    def __init__(self, readings):
        self.readings = readings

    def aggregate(self, pipeline):
        return list(reversed(self.readings[-20:]))

    def insert_one(self, reading):
        self.readings.append(deepcopy(reading))


def sample_readings():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    readings = []
    tips = 300
    for minute in range(30 * 24 * 60 + 1):
        timestamp = now - timedelta(minutes=30 * 24 * 60 - minute)
        phase = timestamp.hour + timestamp.minute / 60
        if 6 <= timestamp.hour < 9 and minute % 37 == 0:
            tips += 1
        temperature = 18.7 + sin((phase - 8) / 24 * 6.283) * 3.2
        readings.append(
            {
                "timestamp": timestamp.isoformat(),
                "device_id": "demo-station",
                "environment": {
                    "temperature": round(temperature, 2),
                    "humidity": round(59 - sin(phase / 24 * 6.283) * 8, 2),
                    "pressure": round(1015.6 + sin(phase / 7) * 1.5, 2),
                },
                "air_quality": {
                    "aqi": 1,
                    "eco2": round(430 + sin(phase) * 15),
                    "tvoc": round(32 + sin(phase) * 6),
                },
                "rainfall": {"tips": tips},
            }
        )
    return readings


def demo_history(collection, hours, now=None):
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    records = [
        record
        for record in collection.readings
        if start <= parse_timestamp(record["timestamp"]) <= end
    ]
    bucket_seconds = max(60, hours * 3600 // 240)
    groups = {}
    for record in records:
        timestamp = parse_timestamp(record["timestamp"])
        key = int(timestamp.timestamp() // bucket_seconds) * bucket_seconds
        groups.setdefault(key, []).append(record)
    series = []
    for key, group in sorted(groups.items()):
        point = {"timestamp": datetime.fromtimestamp(key, timezone.utc).isoformat()}
        for field in ["temperature", "humidity", "pressure", "eco2", "tvoc", "aqi"]:
            section = (
                "environment" if field in {"temperature", "humidity", "pressure"} else "air_quality"
            )
            values = [finite_number(record[section].get(field)) for record in group]
            values = [value for value in values if value is not None]
            point[field] = sum(values) / len(values) if values else None
        series.append(point)
    temperatures = [record["environment"]["temperature"] for record in records]
    summary = {"count": len(records)}
    if temperatures:
        summary.update(
            minimum=min(temperatures),
            maximum=max(temperatures),
            average=sum(temperatures) / len(temperatures),
        )
    return {
        "hours": hours,
        "bucket_seconds": bucket_seconds,
        "series": series,
        "readings": list(reversed(records[-100:])),
        "summary": summary,
    }


def demo_rainfall(collection, hours, update_interval_ms=60000, round_hour=True):
    now = datetime.now(timezone.utc)
    end = (
        (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0) if round_hour else now
    )
    start = end - timedelta(hours=hours)
    records = [
        record
        for record in collection.readings
        if start - timedelta(minutes=10) <= parse_timestamp(record["timestamp"]) <= end
    ]
    data = rainfall_buckets(records, start, hours, max(600, update_interval_ms / 1000 * 3))
    if end > now:
        data[-1].update(complete=False, rainfall_mm=None)
    return {"hours": hours, "data": data}


def load_demo_app():
    configuration = ModuleType("config.config_db")
    configuration.MONGO_URI = "mongodb://127.0.0.1:27017"
    configuration.DB_NAME = "unused_demo"
    configuration.COLLECTION_NAME = "readings"
    configuration.CONFIG_NAME = "configuration"
    configuration.SECRET_KEY = b"local-demo-only"
    configuration.AUTHORIZED_TOKENS = {"demo-token": "demo-station"}
    configuration.OPENWEATHER_API_KEY = ""
    configuration.WEATHER_LOCATION_LAT = 0
    configuration.WEATHER_LOCATION_LON = 0
    configuration.__all__ = [name for name in vars(configuration) if name.isupper()]
    package = ModuleType("config")
    package.__path__ = []
    root = Path(__file__).resolve().parents[1]
    specification = importlib.util.spec_from_file_location("meteo_demo_app", root / "app.py")
    module = importlib.util.module_from_spec(specification)
    with patch.dict(sys.modules, {"config": package, "config.config_db": configuration}), patch(
        "pymongo.MongoClient"
    ):
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
    module.collection = MemoryReadings(sample_readings())
    module.config = MemoryConfiguration()
    module.history_report = demo_history
    module.latest_reading = lambda collection, before=None: next(
        (
            record
            for record in reversed(collection.readings)
            if before is None or parse_timestamp(record["timestamp"]) <= before
        ),
        None,
    )
    module.rainfall_report = demo_rainfall

    def demo_forecast():
        latest = module.collection.readings[-1]
        environment = latest["environment"]
        return (
            module.jsonify(
                {
                    "temperature": round(environment["temperature"] - 1.2, 1),
                    "humidity": 57,
                    "pressure": 1017,
                    "description": "хмарно з проясненнями (демо)",
                    "timestamp": latest["timestamp"],
                    "location": "Львів · демонстраційне місце",
                }
            ),
            200,
        )

    module.get_weather_forecast = demo_forecast
    module.app.jinja_env.globals["preview_mode"] = True
    module.app.config["TESTING"] = True
    return module
