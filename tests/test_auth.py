import unittest

from auth import AttemptLimiter
from tools.demo_data import load_demo_app


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_demo_app()
        cls.store = cls.module.app.extensions["accounts"]
        cls.other = cls.store.register("other_reader", "another-long-password")
        cls.other_station = cls.store.claim(
            cls.other["_id"], "demo-spare", "Private spare", {"temperature": {"min": -12}}
        )

    def setUp(self):
        self.client = self.module.app.test_client()
        self.module.app.extensions["auth_limiter"] = AttemptLimiter()

    def sign_in(self, user_id=None, station_id=None):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id or self.module.demo_user_id
            session["station_id"] = station_id or self.module.demo_station_id
            session["csrf_token"] = "test-csrf"

    def test_anonymous_reading_and_configuration_access_is_denied(self):
        for path in [
            "/api/data",
            "/api/data/last",
            "/api/data/all",
            "/api/data/history",
            "/api/data/stats",
            "/api/data/rainfall",
            "/api/data/hourly_rainfall",
            "/api/config",
            "/api/weather/forecast",
            "/api/weather/comparison",
        ]:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.get("/web").status_code, 302)
        self.assertEqual(self.client.get("/time").status_code, 200)

    def test_valid_device_can_fetch_its_configuration_without_a_browser_session(self):
        response = self.client.get("/api/config", headers={"Authorization": "demo-spare-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["temperature"]["min"], -12)
        self.assertEqual(
            self.client.get("/api/config", headers={"Authorization": "invalid"}).status_code, 401
        )

    def test_missing_csrf_cannot_change_settings_or_select_someone_elses_station(self):
        self.sign_in()
        self.assertEqual(
            self.client.post("/api/config", json={"temperature": {"min": 0}}).status_code, 400
        )
        response = self.client.post(
            "/stations/select",
            data={"station_id": str(self.other_station["_id"]), "csrf_token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/stations/disconnect",
            data={"station_id": str(self.other_station["_id"]), "csrf_token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 403)

    def test_query_parameters_cannot_select_another_accounts_readings(self):
        self.sign_in()
        for path in ["/api/data", "/api/data/last", "/api/data/all"]:
            response = self.client.get(path + "?station_id=" + str(self.other_station["_id"]))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(
                all(record["device_id"] == "demo-station" for record in response.json), path
            )
        response = self.client.get("/api/data/history?hours=24")
        self.assertTrue(
            all(record["device_id"] == "demo-station" for record in response.json["readings"])
        )

    def test_upload_token_does_not_allow_claiming_a_station(self):
        self.sign_in()
        response = self.client.post(
            "/web/stations",
            data={
                "csrf_token": "test-csrf",
                "device_token": "demo-spare-token",
                "label": "Not mine",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.station_for_device("demo-spare")["owner_id"], self.other["_id"])
        self.assertNotIn(b"demo-spare-token", response.data)

    def test_new_device_can_be_connected_once_with_an_operator_pairing_code(self):
        self.module.app.extensions["device_tokens"]["demo-extra-token"] = "demo-extra"
        code = self.store.issue_pairing_code("demo-extra")
        self.sign_in()
        response = self.client.post(
            "/web/stations",
            data={"csrf_token": "test-csrf", "pairing_code": code, "label": "A new station"},
        )
        self.assertEqual(response.status_code, 303)
        station = self.store.station_for_device("demo-extra")
        self.assertEqual(str(station["owner_id"]), self.module.demo_user_id)
        self.assertEqual(self.client.get("/api/data/last").json, [])
        response = self.client.post(
            "/web/stations",
            data={"csrf_token": "test-csrf", "pairing_code": code, "label": "Duplicate"},
        )
        self.assertEqual(response.status_code, 400)

    def test_real_login_rotates_session_and_logout_requires_csrf(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
            session["old_marker"] = "discard"
        response = self.client.post(
            "/login",
            data={"username": "observer", "password": "ocean-breeze-demo", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 303)
        with self.client.session_transaction() as session:
            self.assertNotIn("old_marker", session)
            self.assertNotEqual(session["csrf_token"], token)
            token = session["csrf_token"]
        self.assertEqual(self.client.post("/logout").status_code, 400)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": token}).status_code, 303)
        self.assertEqual(self.client.get("/api/data").status_code, 401)

    def test_registration_works_without_a_station_and_password_is_not_returned(self):
        self.client.get("/register")
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
        response = self.client.post(
            "/register",
            data={
                "username": "new_reader",
                "password": "a-unique-long-password",
                "password_confirmation": "a-unique-long-password",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get("/api/data").status_code, 409)
        self.assertNotIn(b"a-unique-long-password", self.client.get("/web/stations").data)

    def test_failed_logins_are_rate_limited(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
        for _ in range(15):
            response = self.client.post(
                "/login", data={"username": "nobody", "password": "incorrect", "csrf_token": token}
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.client.post(
                "/login", data={"username": "nobody", "password": "incorrect", "csrf_token": token}
            ).status_code,
            429,
        )


if __name__ == "__main__":
    unittest.main()
