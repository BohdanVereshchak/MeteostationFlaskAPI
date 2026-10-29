"""Account persistence and station ownership; independent of Flask routes."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
from threading import Lock

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash


class AccountStore:
    def __init__(self, database):
        self.users = database["meteo_users"]
        self.stations = database["meteo_stations"]
        self.pairing_codes = database["meteo_pairing_codes"]
        self._indexes_ready = False
        self._index_lock = Lock()
        self._dummy_hash = generate_password_hash("not-an-account-password")

    def ensure_indexes(self):
        with self._index_lock:
            if self._indexes_ready:
                return
            self.users.create_index("username_key", unique=True)
            self.stations.create_index("device_id", unique=True)
            self.stations.create_index("owner_id")
            self.pairing_codes.create_index("digest", unique=True)
            self.pairing_codes.create_index("expires_at", expireAfterSeconds=0)
            self._indexes_ready = True

    def register(self, username, password):
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            raise ValueError("Ім’я: 3–32 латинські літери, цифри, крапка, дефіс або підкреслення.")
        if not 10 <= len(password) <= 128:
            raise ValueError("Пароль має містити від 10 до 128 символів.")
        self.ensure_indexes()
        user = {
            "username": username,
            "username_key": username.casefold(),
            "password_hash": generate_password_hash(password),
            "created_at": datetime.now(timezone.utc),
        }
        try:
            result = self.users.insert_one(user)
        except DuplicateKeyError:
            raise ValueError("Це ім’я вже зайняте. Оберіть інше.") from None
        return self.user(str(result.inserted_id))

    def authenticate(self, username, password):
        user = self.users.find_one({"username_key": username.strip().casefold()})
        password_hash = user["password_hash"] if user else self._dummy_hash
        valid = check_password_hash(password_hash, password)
        return self.user(str(user["_id"])) if user and valid else None

    def user(self, user_id):
        if not ObjectId.is_valid(user_id):
            return None
        return self.users.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})

    def owned_stations(self, owner_id):
        return list(self.stations.find({"owner_id": owner_id}).sort("label", 1))

    def owned_station(self, station_id, owner_id):
        if not ObjectId.is_valid(station_id):
            return None
        return self.stations.find_one({"_id": ObjectId(station_id), "owner_id": owner_id})

    def station_for_device(self, device_id):
        return self.stations.find_one({"device_id": device_id})

    def issue_pairing_code(self, device_id):
        self.ensure_indexes()
        station = self.station_for_device(device_id)
        if station and station.get("owner_id") is not None:
            raise ValueError("Спочатку від’єднайте станцію від поточного облікового запису.")
        code = secrets.token_hex(16)
        self.pairing_codes.delete_many({"device_id": device_id})
        self.pairing_codes.insert_one(
            {
                "digest": pairing_digest(code),
                "device_id": device_id,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
            }
        )
        return "-".join(code[index : index + 4] for index in range(0, len(code), 4))

    def consume_pairing_code(self, code):
        if not code or len(code) > 128:
            return None
        return self.pairing_codes.find_one_and_delete(
            {
                "digest": pairing_digest(code),
                "expires_at": {"$gt": datetime.now(timezone.utc)},
            }
        )

    def claim(self, owner_id, device_id, label, configuration, include_legacy=False):
        label = label.strip()
        if not 1 <= len(label) <= 60:
            raise ValueError("Дайте станції назву від 1 до 60 символів.")
        self.ensure_indexes()
        try:
            return self.stations.find_one_and_update(
                {"device_id": device_id, "$or": [{"owner_id": None}, {"owner_id": owner_id}]},
                {
                    "$set": {"owner_id": owner_id, "label": label},
                    "$setOnInsert": {
                        "settings": configuration,
                        "include_legacy": include_legacy,
                        "connected_at": datetime.now(timezone.utc),
                    },
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raise ValueError("Цю станцію вже підключено до іншого облікового запису.") from None

    def save_settings(self, station_id, owner_id, configuration):
        if not ObjectId.is_valid(station_id):
            return False
        updates = {
            f"settings.{section}.{field}": value
            for section, fields in configuration.items()
            for field, value in fields.items()
        }
        result = self.stations.update_one(
            {"_id": ObjectId(station_id), "owner_id": owner_id}, {"$set": updates}
        )
        return result.matched_count == 1

    def disconnect(self, station_id, owner_id):
        if not ObjectId.is_valid(station_id):
            return False
        result = self.stations.update_one(
            {"_id": ObjectId(station_id), "owner_id": owner_id}, {"$set": {"owner_id": None}}
        )
        return result.matched_count == 1


def station_data_filter(station):
    device = {"device_id": station["device_id"]}
    if station.get("include_legacy"):
        return {"$or": [device, {"device_id": {"$exists": False}}]}
    return device


def pairing_digest(code):
    normalized = "".join(code.split()).replace("-", "").lower()
    return sha256(normalized.encode("utf-8")).hexdigest()
