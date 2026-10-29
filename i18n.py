"""Shared translations and a language preference independent of login sessions."""

import json
import re
from pathlib import Path

from flask import g, request, url_for

SUPPORTED_LANGUAGES = ("en", "uk")
ENGLISH_MESSAGES = json.loads(
    (Path(__file__).parent / "translations" / "en.json").read_text(encoding="utf-8")
)


def current_language():
    return getattr(g, "language", "en")


def t(message, **values):
    translated = ENGLISH_MESSAGES.get(message, message) if current_language() == "en" else message
    return re.sub(r"\{(\w+)\}", lambda match: str(values.get(match[1], match[0])), translated)


def language_url(language):
    rule = request.url_rule
    if rule is None or "GET" not in rule.methods:
        return url_for("index_page", lang=language)
    arguments = request.args.to_dict(flat=False)
    arguments.update(request.view_args or {})
    arguments["lang"] = language
    return url_for(request.endpoint, **arguments)


def install_localization(app):
    @app.before_request
    def select_language():
        requested = request.args.get("lang")
        saved = request.cookies.get("meteo_language")
        if requested in SUPPORTED_LANGUAGES:
            g.language = requested
        elif saved in SUPPORTED_LANGUAGES:
            g.language = saved
        else:
            g.language = request.accept_languages.best_match(SUPPORTED_LANGUAGES, default="en")

    @app.context_processor
    def translation_context():
        language = current_language()
        return {
            "t": t,
            "language": language,
            "language_url": language_url,
            "translation_messages": ENGLISH_MESSAGES if language == "en" else {},
        }

    @app.after_request
    def remember_language(response):
        requested = request.args.get("lang")
        if requested in SUPPORTED_LANGUAGES:
            response.set_cookie(
                "meteo_language",
                requested,
                max_age=365 * 24 * 3600,
                httponly=True,
                samesite="Lax",
                secure=app.config.get("SESSION_COOKIE_SECURE", True),
            )
        if request.endpoint != "static":
            response.headers["Content-Language"] = current_language()
            response.vary.add("Accept-Language")
            response.vary.add("Cookie")
        return response
