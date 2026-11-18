"""운영 API — n8n·외부 스케줄러가 단계 실행을 요청하는 용도. X-SCF-Token 필수."""
from __future__ import annotations

import hmac
import shutil

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import select, text

from app.models import DataSource
from config.settings import get_settings
from services.common.db import session_scope
from services.common.timeutil import parse_date
from workflows.pipeline import STAGE_MAP, FileLock, run_stage

bp = Blueprint("api", __name__)


def _auth() -> None:
    token = get_settings().api_token
    given = request.headers.get("X-SCF-Token", "")
    if not token or not hmac.compare_digest(token, given):
        abort(401)


@bp.post("/jobs/run")
def run_job():
    _auth()
    data = request.get_json(silent=True) or {}
    stage = data.get("stage")
    if stage not in STAGE_MAP:
        return jsonify({"error": "unknown stage", "stages": list(STAGE_MAP)}), 400
    run_date = parse_date(data.get("date"))
    try:
        with FileLock(get_settings().output_dir / ".pipeline.lock"):
            res = run_stage(run_date, stage, force=bool(data.get("force")))
    except RuntimeError as exc:
        return jsonify({"stage": stage, "status": "busy", "message": str(exc)}), 409
    res.pop("detail", None)
    return jsonify(res)


@bp.get("/health")
def health():
    with session_scope() as s:
        s.execute(text("select 1"))
        sources = {d.name: d.state for d in s.scalars(select(DataSource))}
    return jsonify({"ok": True, "ffmpeg": bool(shutil.which("ffmpeg")), "sources": sources})
