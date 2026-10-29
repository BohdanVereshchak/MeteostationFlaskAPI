import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from bson import ObjectId
from pymongo.errors import ServerSelectionTimeoutError
from tools.demo_data import load_demo_app


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_demo_app()
        cls.client = cls.module.app.test_client()
        cls.client.environ_base["HTTP_X_CSRF_TOKEN"] = "route-test-csrf"
        with cls.client.session_transaction() as session:
            session["user_id"] = cls.module.demo_user_id
            session["station_id"] = cls.module.demo_station_id
            session["csrf_token"] = "route-test-csrf"

    def test_pages_render_without_external_ui_dependencies(self):
        for path in ["/", "/web", "/web/history", "/web/settings", "/web/comparison"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn(b"cdn.jsdelivr", response.data)
            self.assertIn(b'type="module"', response.data)

    def test_signed_esp32_upload_contract_is_preserved(self):
        payload = {"environment": {"temperature": 0, "humidity": 40}, "rainfall": {"tips": 0}}
        raw = json.dumps(payload).encode()
        signature = hmac.new(b"local-demo-only", raw, hashlib.sha256).hexdigest()
        response = self.client.post(
            "/api/data",
            data=raw,
            headers={
                "Authorization": "demo-token",
                "X-Signature": signature,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.module.collection.readings[-1]["device_id"], "demo-station")
        self.module.collection.readings.pop()

    def test_unsigned_and_badly_signed_uploads_are_rejected(self):
        count = len(self.module.collection.readings)
        self.assertEqual(self.client.post("/api/data", json={}).status_code, 401)
        response = self.client.post(
            "/api/data", json={}, headers={"Authorization": "demo-token", "X-Signature": "bad"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.module.collection.readings), count)

    def test_signed_invalid_shapes_are_rejected_without_storing_records(self):
        count = len(self.module.collection.readings)
        for payload in [[], {"environment": None}, {"rainfall": []}, {"timestamp": "invalid"}]:
            raw = json.dumps(payload).encode()
            signature = hmac.new(b"local-demo-only", raw, hashlib.sha256).hexdigest()
            response = self.client.post(
                "/api/data",
                data=raw,
                headers={"Authorization": "demo-token", "X-Signature": signature},
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.module.collection.readings), count)

    def test_history_and_rainfall_inputs_are_bounded(self):
        for query in ["hours=0", "hours=721", "hours=abc"]:
            self.assertEqual(self.client.get("/api/data/history?" + query).status_code, 400)
        for query in ["hours=0", "hours=169", "hours=no"]:
            self.assertEqual(self.client.get("/api/data/hourly_rainfall?" + query).status_code, 400)

    def test_configuration_partial_updates_keep_unedited_device_fields(self):
        self.module.app.extensions["accounts"].stations.update_one(
            {"_id": ObjectId(self.module.demo_station_id)},
            {"$set": {"settings.system.sensor_mode": "existing"}},
        )
        response = self.client.post(
            "/api/config",
            json={
                "system": {"update_interval_ms": 30000},
                "location": {"latitude": 0, "longitude": 0},
            },
        )
        self.assertEqual(response.status_code, 200)
        configuration = self.client.get("/api/config").json
        self.assertEqual(configuration["system"]["sensor_mode"], "existing")
        self.assertEqual(configuration["location"]["latitude"], 0)

    def test_invalid_settings_do_not_write_configuration(self):
        before = self.client.get("/api/config").json
        response = self.client.post("/api/config", json={"temperature": {"min": 30, "max": 20}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(before, self.client.get("/api/config").json)

    def test_database_error_returns_actionable_json_without_connection_details(self):
        with patch.object(
            self.module,
            "history_report",
            side_effect=ServerSelectionTimeoutError("private-connection-details"),
        ):
            response = self.client.get("/api/data/history?hours=24")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-connection-details", response.get_data(as_text=True))

    def test_comparison_includes_observation_times_for_both_sources(self):
        response = self.client.get("/api/weather/comparison")
        self.assertEqual(response.status_code, 200)
        self.assertIn("reference_timestamp", response.json)
        self.assertIn("timestamp", response.json)


if __name__ == "__main__":
    unittest.main()
