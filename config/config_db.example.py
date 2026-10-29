"""Copy to config_db.py; keep actual credentials in the ignored secrets.env file."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "secrets.env")

MONGO_URI = os.environ["MONGO_URI"]
DB_NAME = os.environ.get("DB_NAME", "meteostation")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "readings")
CONFIG_NAME = os.environ.get("CONFIG_NAME", "configuration")
SECRET_KEY = os.environ["STATION_HMAC_SECRET"].encode("utf-8")
AUTHORIZED_TOKENS = json.loads(os.environ["STATION_TOKENS_JSON"])
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
WEATHER_LOCATION_LAT = float(os.environ.get("WEATHER_LOCATION_LAT", "0"))
WEATHER_LOCATION_LON = float(os.environ.get("WEATHER_LOCATION_LON", "0"))
