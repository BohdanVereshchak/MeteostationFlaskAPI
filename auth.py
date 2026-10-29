"""Browser sessions, CSRF checks, and station connection routes."""

from collections import defaultdict, deque
from datetime import timedelta
import hmac
import os
from pathlib import Path
import secrets
from threading import Lock
from time import monotonic

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from accounts import AccountStore, station_data_filter
from i18n import t

auth_pages = Blueprint("auth", __name__)


def account_store():
    return current_app.extensions["accounts"]


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def authorized_device(token):
    if not token:
        return None
    for allowed, device_id in current_app.extensions["device_tokens"].items():
        if hmac.compare_digest(str(allowed).encode(), token.encode()):
            return device_id
    return None


def session_secret(root):
    configured = os.environ.get("METEO_SESSION_SECRET")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("METEO_SESSION_SECRET must contain at least 32 characters.")
        return configured
    path = Path(root) / ".session-secret"
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(secrets.token_urlsafe(48))
        path.chmod(0o600)
    except FileExistsError:
        pass
    secret = path.read_text(encoding="utf-8").strip()
    if len(secret) < 32:
        raise RuntimeError("The local .session-secret file is invalid.")
    return secret


class AttemptLimiter:
    def __init__(self):
        self.attempts = defaultdict(deque)
        self.lock = Lock()

    def allow(self, key, limit=15, window=900):
        now = monotonic()
        with self.lock:
            if len(self.attempts) > 10000:
                self.attempts.clear()
            attempts = self.attempts[key]
            while attempts and attempts[0] <= now - window:
                attempts.popleft()
            if len(attempts) >= limit:
                return False
            attempts.append(now)
            return True


def configuration_for_device(device_id):
    station = account_store().station_for_device(device_id)
    if station and station.get("settings"):
        return station["settings"]
    return current_app.extensions["legacy_station_config"].find_one({}, {"_id": 0}) or {}


def active_data_filter():
    return station_data_filter(g.station)


def begin_session(user):
    session.clear()
    session["user_id"] = str(user["_id"])
    session.permanent = True
    csrf_token()


@auth_pages.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index_page"))
    error = ""
    status = 200
    if request.method == "POST":
        limiter = current_app.extensions["auth_limiter"]
        if not limiter.allow(("login", request.remote_addr)):
            error, status = t("Забагато спроб. Повторіть вхід через 15 хвилин."), 429
        else:
            username = request.form.get("username", "")[:128]
            password = request.form.get("password", "")
            user = (
                account_store().authenticate(username, password) if len(password) <= 128 else None
            )
            if user:
                begin_session(user)
                return redirect(url_for("index_page"), code=303)
            error, status = t("Перевірте ім’я користувача та пароль."), 400
    return render_template("auth.html", register=False, error=error), status


@auth_pages.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index_page"))
    error = ""
    status = 200
    if request.method == "POST":
        if not current_app.extensions["auth_limiter"].allow(
            ("register", request.remote_addr), 5, 3600
        ):
            error, status = t("Забагато спроб реєстрації. Повторіть пізніше."), 429
        else:
            try:
                password = request.form.get("password", "")
                if password != request.form.get("password_confirmation", ""):
                    raise ValueError(t("Паролі не збігаються."))
                user = account_store().register(request.form.get("username", ""), password)
                begin_session(user)
                return redirect(url_for("auth.stations"), code=303)
            except ValueError as failure:
                error, status = t(str(failure)), 400
    return render_template("auth.html", register=True, error=error), status


@auth_pages.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"), code=303)


@auth_pages.route("/web/stations", methods=["GET", "POST"])
def stations():
    error = ""
    status = 200
    if request.method == "POST":
        if not current_app.extensions["auth_limiter"].allow(("claim", str(g.user["_id"])), 10, 900):
            error, status = t("Забагато спроб підключення. Повторіть через 15 хвилин."), 429
        else:
            label = request.form.get("label", "").strip()
            pairing = (
                account_store().consume_pairing_code(request.form.get("pairing_code", ""))
                if 1 <= len(label) <= 60
                else None
            )
            device_id = pairing["device_id"] if pairing else None
            if (
                device_id is None
                or device_id not in current_app.extensions["device_tokens"].values()
            ):
                error, status = (
                    t(
                        "Перевірте назву та код підключення. Код діє 15 хвилин і використовується один раз."
                    ),
                    400,
                )
            else:
                try:
                    baseline = configuration_for_device(device_id)
                    settings = {
                        name: baseline.get(name, {})
                        for name in ["system", "location", "temperature", "humidity"]
                    }
                    devices = list(current_app.extensions["device_tokens"].values())
                    legacy = len(set(devices)) == 1
                    station = account_store().claim(
                        g.user["_id"], device_id, label, settings, legacy
                    )
                    session["station_id"] = str(station["_id"])
                    return redirect(url_for("index_page"), code=303)
                except ValueError as failure:
                    error, status = t(str(failure)), 400
    return render_template("stations.html", error=error), status


@auth_pages.post("/stations/select")
def select_station():
    station = account_store().owned_station(request.form.get("station_id", ""), g.user["_id"])
    if not station:
        return jsonify({"error": t("Ця станція недоступна для вашого облікового запису.")}), 403
    session["station_id"] = str(station["_id"])
    return redirect(url_for("index_page"), code=303)


@auth_pages.post("/stations/disconnect")
def disconnect_station():
    station_id = request.form.get("station_id", "")
    if not account_store().disconnect(station_id, g.user["_id"]):
        return jsonify({"error": t("Станція недоступна.")}), 403
    if session.get("station_id") == station_id:
        session.pop("station_id", None)
    return redirect(url_for("auth.stations"), code=303)


def install_authentication(app, database, tokens, legacy_configuration):
    app.secret_key = session_secret(app.root_path)
    app.config.update(
        SESSION_COOKIE_NAME="meteo_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("METEO_COOKIE_SECURE", "1") != "0",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    app.extensions["accounts"] = AccountStore(database)
    app.extensions["device_tokens"] = tokens
    app.extensions["legacy_station_config"] = legacy_configuration
    app.extensions["auth_limiter"] = AttemptLimiter()
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.register_blueprint(auth_pages)

    @app.before_request
    def guard_access():
        g.user = None
        g.station = None
        g.stations = []
        if request.endpoint == "static":
            return None
        machine_upload = request.path == "/api/data" and request.method == "POST"
        machine_configuration = (
            request.path == "/api/config"
            and request.method == "GET"
            and authorized_device(request.headers.get("Authorization", "")) is not None
        )
        if machine_upload or machine_configuration or request.path == "/time":
            return None
        if session.get("user_id"):
            g.user = account_store().user(session["user_id"])
            if not g.user:
                session.clear()
        public_auth = request.endpoint in {"auth.login", "auth.register"}
        if not g.user and not public_auth:
            if request.path.startswith("/api/"):
                return jsonify({"error": t("Увійдіть до свого облікового запису.")}), 401
            return redirect(url_for("auth.login"))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            received = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected.encode(), received.encode()):
                if request.path.startswith("/api/"):
                    return jsonify({"error": t("Оновіть сторінку й повторіть дію.")}), 400
                return render_template("auth_error.html"), 400
        if not g.user:
            return None
        g.stations = account_store().owned_stations(g.user["_id"])
        station_id = session.get("station_id", "")
        g.station = account_store().owned_station(station_id, g.user["_id"])
        if g.station is None and g.stations:
            g.station = g.stations[0]
            session["station_id"] = str(g.station["_id"])
        account_route = request.endpoint is not None and request.endpoint.startswith("auth.")
        if not g.station and not account_route:
            if request.path.startswith("/api/"):
                return jsonify({"error": t("Спочатку підключіть власну станцію.")}), 409
            return redirect(url_for("auth.stations"))

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response
