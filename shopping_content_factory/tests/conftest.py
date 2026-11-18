"""테스트 공통 — 실제 외부 API 를 절대 호출하지 않도록 자격증명 환경변수를 비우고 mock 모드로 고정.

golden: 세션당 한 번 mock 파이프라인을 qa_check 까지 실행(영상 렌더 포함, fps 6).
pipeline: golden 의 DB·산출물을 테스트마다 복사해 서로 영향 없이 상태를 바꿀 수 있게 한다.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RUN_DATE = date(2026, 11, 18)
CRED_VARS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "COUPANG_ACCESS_KEY",
             "COUPANG_SECRET_KEY", "INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN", "YOUTUBE_CLIENT_ID",
             "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "SCF_PUBLIC_MEDIA_BASE_URL", "NCP_APIGW_API_KEY_ID",
             "NCP_APIGW_API_KEY"]


def apply_env(tmp: Path, **extra) -> None:
    from config.settings import reload_settings
    from services.common.db import init_db, reset_engine

    base = {
        "SCF_ENV": "test", "SCF_DATABASE_URL": f"sqlite:///{tmp / 'test.db'}", "SCF_OUTPUT_DIR": str(tmp / "out"),
        "SCF_DATA_DIR": str(ROOT / "data"), "SCF_RENDER_FPS": "6", "SCF_ADMIN_PASSWORD": "pw-test-123",
        "SCF_SECRET_KEY": "test-secret-key", "SCF_API_TOKEN": "tok-test-123456", "SCF_LLM_PROVIDER": "mock",
        "SCF_TREND_PROVIDER": "mock", "SCF_PRODUCT_PROVIDER": "mock", "SCF_TTS_PROVIDER": "none",
        "SCF_LOG_LEVEL": "WARNING", "AUTO_PUBLISH": "false", "SCF_COST_CAP_DAILY_KRW": "3000",
    }
    base.update(extra)
    for k in CRED_VARS:
        os.environ.pop(k, None)
    for k, v in base.items():
        os.environ[k] = v
    reload_settings()
    reset_engine()
    (tmp / "out").mkdir(parents=True, exist_ok=True)
    init_db()


@pytest.fixture
def env(tmp_path):
    apply_env(tmp_path)
    yield tmp_path


@pytest.fixture(scope="session")
def golden(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("golden")
    apply_env(tmp)
    from workflows.pipeline import run_daily

    results = run_daily(RUN_DATE, until="qa_check", include_publish=False)
    assert all(r["status"] == "succeeded" for r in results), results
    return tmp


@pytest.fixture
def pipeline(golden, tmp_path):
    """golden 상태의 독립 복사본 (content_id = C20261118-01, 상태 awaiting_approval)."""
    src = sqlite3.connect(golden / "test.db")  # WAL 모드라 파일 복사 대신 backup API 로 일관된 사본
    con = sqlite3.connect(tmp_path / "test.db")
    src.backup(con)
    src.close()
    shutil.copytree(golden / "out", tmp_path / "out")
    con.execute("UPDATE contents SET output_dir = replace(output_dir, ?, ?)", (str(golden), str(tmp_path)))
    con.commit()
    con.close()
    apply_env(tmp_path)
    return tmp_path


@pytest.fixture
def app_client(pipeline):
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def admin_login(client) -> str:
    client.get("/admin/login")
    with client.session_transaction() as s:
        token = s["csrf"]
    r = client.post("/admin/login", data={"password": "pw-test-123", "name": "tester", "csrf_token": token})
    assert r.status_code == 302
    return token


def register_verified_link(pid: str = "DEMO-001", url: str = "https://link.coupang.com/a/TESTONLY1") -> None:
    """테스트 전용 — 형식만 맞는 가짜 링크. 실제 운영 데이터에 넣지 않는다."""
    from app.models import Product
    from services.affiliate_links.links import confirm_link, register_manual_link
    from services.common.db import session_scope

    with session_scope() as s:
        p = s.get(Product, pid)
        link = register_manual_link(s, p, url, "tester", sub_id="sub-c01", content_id="C20261118-01")
        s.flush()
        confirm_link(s, link, "tester")
