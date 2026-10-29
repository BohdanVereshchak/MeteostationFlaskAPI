"""Deterministic local fixtures. Never imports the real database configuration."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from math import sin
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch
import os
import mongomock
from accounts import AccountStore
from i18n import t

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


def matches(record, query):
    if not query:
        return True
    for key, value in query.items():
        if key == "$or":
            if not any(matches(record, child) for child in value):
                return False
        elif key == "$and":
            if not all(matches(record, child) for child in value):
                return False
        elif isinstance(value, dict):
            if "$exists" in value and (key in record) != value["$exists"]:
                return False
            if "$lte" in value and record.get(key, "") > value["$lte"]:
                return False
        elif record.get(key) != value:
            return False
    return True


class MemoryCursor(list):
    def sort(self, key, direction):
        return MemoryCursor(
            sorted(self, key=lambda record: record.get(key, ""), reverse=direction < 0)
        )

    def limit(self, count):
        return MemoryCursor(self[:count])


class MemoryReadings:
    def __init__(self, readings):
        self.readings = readings

    def find(self, query, *args):
        return MemoryCursor(
            [deepcopy(record) for record in self.readings if matches(record, query)]
        )

    def find_one(self, query, *args, sort=None):
        records = self.find(query)
        if sort:
            records = records.sort(*sort[0])
        return records[0] if records else None

    def aggregate(self, pipeline):
        query = pipeline[0].get("$match", {})
        records = self.find(query).sort("timestamp", -1)
        return records[:20]

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


def demo_history(collection, hours, now=None, device_filter=None):
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    records = [
        record
        for record in collection.readings
        if matches(record, device_filter) and start <= parse_timestamp(record["timestamp"]) <= end
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


def demo_rainfall(collection, hours, update_interval_ms=60000, round_hour=True, device_filter=None):
    now = datetime.now(timezone.utc)
    end = (
        (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0) if round_hour else now
    )
    start = end - timedelta(hours=hours)
    records = [
        record
        for record in collection.readings
        if matches(record, device_filter)
        and start - timedelta(minutes=10) <= parse_timestamp(record["timestamp"]) <= end
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
    configuration.AUTHORIZED_TOKENS = {
        "demo-token": "demo-station",
        "demo-roof-token": "demo-roof",
        "demo-spare-token": "demo-spare",
    }
    configuration.OPENWEATHER_API_KEY = ""
    configuration.WEATHER_LOCATION_LAT = 0
    configuration.WEATHER_LOCATION_LON = 0
    configuration.__all__ = [name for name in vars(configuration) if name.isupper()]
    package = ModuleType("config")
    package.__path__ = []
    root = Path(__file__).resolve().parents[1]
    specification = importlib.util.spec_from_file_location("meteo_demo_app", root / "app.py")
    module = importlib.util.module_from_spec(specification)
    with patch.dict(
        sys.modules, {"config": package, "config.config_db": configuration}
    ), patch.dict(
        os.environ,
        {
            "METEO_SESSION_SECRET": "isolated-demo-session-secret-keep-out-of-production",
            "METEO_COOKIE_SECURE": "0",
        },
    ), patch(
        "pymongo.MongoClient"
    ):
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
    readings = sample_readings()
    roof = deepcopy(readings[-1441:])
    for reading in roof:
        reading["device_id"] = "demo-roof"
        reading["environment"]["temperature"] -= 2.5
    spare = deepcopy(readings[-61:])
    for reading in spare:
        reading["device_id"] = "demo-spare"
        reading["environment"]["temperature"] += 1.5
    module.collection = MemoryReadings(readings + roof + spare)
    module.config = MemoryConfiguration()
    store = AccountStore(mongomock.MongoClient()["offline_accounts"])
    module.app.extensions["accounts"] = store
    module.app.extensions["legacy_station_config"] = module.config
    user = store.register("observer", "ocean-breeze-demo")
    station = store.claim(user["_id"], "demo-station", "Сад, Львів", module.config.find_one())
    store.claim(user["_id"], "demo-roof", "Дах, Львів", module.config.find_one())
    module.demo_pairing_code = store.issue_pairing_code("demo-spare")
    module.app.jinja_env.globals["preview_pairing_code"] = module.demo_pairing_code
    module.demo_user_id = str(user["_id"])
    module.demo_station_id = str(station["_id"])
    module.history_report = demo_history
    module.latest_reading = lambda collection, before=None, device_filter=None: next(
        (
            record
            for record in reversed(collection.readings)
            if matches(record, device_filter)
            and (before is None or parse_timestamp(record["timestamp"]) <= before)
        ),
        None,
    )
    module.rainfall_report = demo_rainfall

    def demo_forecast():
        latest = module.latest_reading(module.collection, device_filter=module.active_data_filter())
        environment = latest["environment"]
        return (
            module.jsonify(
                {
                    "temperature": round(environment["temperature"] - 1.2, 1),
                    "humidity": 57,
                    "pressure": 1017,
                    "description": t("хмарно з проясненнями (демо)"),
                    "timestamp": latest["timestamp"],
                    "location": t("Львів · демонстраційне місце"),
                }
            ),
            200,
        )

    module.get_weather_forecast = demo_forecast
    module.app.jinja_env.globals["preview_mode"] = True
    module.app.config["TESTING"] = True
    return module
