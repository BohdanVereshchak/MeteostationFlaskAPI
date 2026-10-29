import ast
from pathlib import Path
import re
import unittest

from flask import g
from i18n import ENGLISH_MESSAGES, t
from tools.demo_data import load_demo_app


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_demo_app()

    def setUp(self):
        self.client = self.module.app.test_client()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.module.demo_user_id
            session["station_id"] = self.module.demo_station_id
            session["csrf_token"] = "language-test-csrf"

    def test_english_default_and_browser_preference(self):
        response = self.client.get("/login")
        self.assertIn(b'<html lang="en">', response.data)
        self.assertIn(b"Sign in to Meteo", response.data)
        self.assertEqual(response.headers["Content-Language"], "en")
        response = self.client.get("/login", headers={"Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8"})
        self.assertIn('<html lang="uk">', response.get_data(as_text=True))

    def test_explicit_choice_persists_and_unknown_languages_are_rejected(self):
        self.client.get("/login?lang=uk")
        self.assertEqual(self.client.get("/login").headers["Content-Language"], "uk")
        self.client.get("/login?lang=en")
        self.assertEqual(self.client.get("/login").headers["Content-Language"], "en")
        self.assertEqual(self.client.get("/login?lang=unknown").headers["Content-Language"], "en")

    def test_private_pages_translate_without_changing_the_selected_station(self):
        self.sign_in()
        pages = {
            "/web": "Weather, here and now",
            "/web/history": "Observation archive",
            "/web/comparison": "Two views of the weather",
            "/web/settings": "Your station",
            "/web/stations": "My stations",
        }
        for path, heading in pages.items():
            response = self.client.get(path + "?lang=en")
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(heading, response.get_data(as_text=True), path)
            self.assertIn(b'<html lang="en">', response.data, path)
        self.client.get("/web?lang=uk")
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], self.module.demo_user_id)
            self.assertEqual(session["station_id"], self.module.demo_station_id)
            self.assertEqual(session["csrf_token"], "language-test-csrf")

    def test_api_errors_and_registration_validation_use_the_requested_language(self):
        response = self.client.get("/api/data?lang=en")
        self.assertEqual(response.json["error"], "Sign in to your account.")
        response = self.client.get("/api/data?lang=uk")
        self.assertEqual(response.json["error"], "Увійдіть до свого облікового запису.")
        self.client.get("/register?lang=en")
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
        response = self.client.post(
            "/register",
            data={
                "username": "english_reader",
                "password": "short",
                "password_confirmation": "short",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Your password must contain between 10 and 128 characters.", response.data)

    def test_catalog_preserves_placeholders_and_all_used_ukrainian_messages_exist(self):
        placeholder = re.compile(r"\{(\w+)\}")
        for original, translated in ENGLISH_MESSAGES.items():
            self.assertEqual(
                set(placeholder.findall(original)), set(placeholder.findall(translated)), original
            )
        root = Path(__file__).resolve().parents[1]
        literal_call = re.compile(r"""\bt\(\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""")
        paths = [
            *root.glob("templates/*.html"),
            *root.glob("static/js/*.js"),
            root / "auth.py",
            root / "app.py",
        ]
        for path in paths:
            for match in literal_call.finditer(path.read_text(encoding="utf-8")):
                message = ast.literal_eval(match[1])
                if re.search(r"[А-Яа-яІіЇїЄєҐґ]", message):
                    self.assertTrue(message in ENGLISH_MESSAGES, f"Missing translation in {path.name}: {message}")

    def test_dynamic_values_are_inserted_once_and_unknown_messages_are_unchanged(self):
        with self.module.app.test_request_context("/"):
            g.language = "en"
            self.assertEqual(
                t("{shown} із {total} записів", shown=0, total=100), "0 of 100 readings"
            )
            self.assertEqual(t("A new message"), "A new message")
            g.language = "uk"
            self.assertEqual(t("Огляд"), "Огляд")


if __name__ == "__main__":
    unittest.main()
