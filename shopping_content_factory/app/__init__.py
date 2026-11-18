"""Flask 앱 팩토리 — 공개 랜딩(/), 관리자(/admin), API(/api)."""
from __future__ import annotations

import secrets

from flask import Flask, render_template, request, session

from config.settings import get_settings, load_policy
from services.common.db import init_db
from services.common.logging_utils import get_logger, setup_logging
from services.common.timeutil import fmt_local, hours_since

log = get_logger(__name__)


def create_app() -> Flask:
    settings = get_settings()
    setup_logging()
    init_db()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.env == "prod",
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )

    from app.routes.admin import bp as admin_bp
    from app.routes.api import bp as api_bp
    from app.routes.public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.template_filter("krw")
    def krw(v):
        return "-" if v is None else f"{v:,.0f}원"

    @app.template_filter("num")
    def num(v, digits=0):
        if v is None:
            return "연동 대기"
        return f"{v:,.{digits}f}"

    @app.template_filter("pct")
    def pct(v, digits=1):
        return "-" if v is None else f"{v * 100:.{digits}f}%"

    @app.template_filter("dt")
    def dt(v):
        return fmt_local(v)

    @app.context_processor
    def inject():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return {"settings": settings, "disclosure": load_policy("compliance")["disclosure"],
                "csrf_token": session["csrf"], "hours_since": hours_since}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; media-src 'self'; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        return resp

    @app.errorhandler(404)
    def not_found(_e):
        tpl = "admin/error.html" if request.path.startswith("/admin") else "public/error.html"
        return render_template(tpl, code=404, message="페이지를 찾을 수 없습니다."), 404

    @app.errorhandler(500)
    def server_error(e):
        log.error("500: %s", e)
        tpl = "admin/error.html" if request.path.startswith("/admin") else "public/error.html"
        return render_template(tpl, code=500, message="일시적인 오류입니다. 로그를 확인하세요."), 500

    return app
