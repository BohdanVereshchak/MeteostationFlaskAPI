import unittest
from datetime import datetime, timedelta, timezone

import mongomock
from accounts import AccountStore, station_data_filter


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = AccountStore(mongomock.MongoClient()["account_tests"])
        self.alice = self.store.register("Alice", "long-password-alice")
        self.bob = self.store.register("Bob", "long-password-bob")

    def test_passwords_are_hashed_and_usernames_are_case_insensitive(self):
        stored = self.store.users.find_one({"username_key": "alice"})
        self.assertNotEqual(stored["password_hash"], "long-password-alice")
        self.assertTrue(stored["password_hash"].startswith("scrypt:"))
        self.assertNotIn("password_hash", self.store.authenticate("ALICE", "long-password-alice"))
        self.assertIsNone(self.store.authenticate("Alice", "wrong-password"))
        with self.assertRaises(ValueError):
            self.store.register("alice", "another-long-password")

    def test_station_claim_is_exclusive_and_settings_are_owner_scoped(self):
        station = self.store.claim(
            self.alice["_id"], "sensor-a", "Garden", {"temperature": {"min": 0}}
        )
        with self.assertRaises(ValueError):
            self.store.claim(self.bob["_id"], "sensor-a", "Stolen", {})
        self.assertIsNone(self.store.owned_station(str(station["_id"]), self.bob["_id"]))
        self.assertFalse(
            self.store.save_settings(
                str(station["_id"]), self.bob["_id"], {"temperature": {"min": -10}}
            )
        )
        self.assertEqual(
            self.store.station_for_device("sensor-a")["settings"]["temperature"]["min"], 0
        )

    def test_disconnect_preserves_measurements_configuration_and_reconnection(self):
        station = self.store.claim(
            self.alice["_id"], "sensor-a", "Garden", {"system": {"update_interval_ms": 60000}}
        )
        self.assertFalse(self.store.disconnect(str(station["_id"]), self.bob["_id"]))
        self.assertTrue(self.store.disconnect(str(station["_id"]), self.alice["_id"]))
        self.assertEqual(
            self.store.station_for_device("sensor-a")["settings"]["system"]["update_interval_ms"],
            60000,
        )
        transferred = self.store.claim(self.bob["_id"], "sensor-a", "New name", {})
        self.assertEqual(transferred["owner_id"], self.bob["_id"])
        self.assertEqual(transferred["settings"]["system"]["update_interval_ms"], 60000)

    def test_unassigned_legacy_data_requires_an_explicit_station_flag(self):
        self.assertEqual(station_data_filter({"device_id": "a"}), {"device_id": "a"})
        self.assertEqual(
            station_data_filter({"device_id": "a", "include_legacy": True}),
            {"$or": [{"device_id": "a"}, {"device_id": {"$exists": False}}]},
        )

    def test_pairing_codes_are_hashed_single_use_and_time_limited(self):
        code = self.store.issue_pairing_code("new-sensor")
        stored = self.store.pairing_codes.find_one({})
        self.assertNotIn(code, str(stored))
        self.assertEqual(self.store.consume_pairing_code(code)["device_id"], "new-sensor")
        self.assertIsNone(self.store.consume_pairing_code(code))
        expired = self.store.issue_pairing_code("new-sensor")
        self.store.pairing_codes.update_many(
            {}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}}
        )
        self.assertIsNone(self.store.consume_pairing_code(expired))


if __name__ == "__main__":
    unittest.main()
