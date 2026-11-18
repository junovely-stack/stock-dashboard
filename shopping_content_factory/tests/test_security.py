"""비밀키가 로그·저장소에 노출되지 않는지."""
import logging
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_logs_mask_secrets(monkeypatch, caplog):
    from services.common.logging_utils import get_logger, redact, redact_obj

    monkeypatch.setenv("COUPANG_SECRET_KEY", "super-secret-value-123")
    log = get_logger("test.secret")
    with caplog.at_level(logging.INFO):
        log.info("auth header CEA algorithm=HmacSHA256, access-key=AK123, signed-date=x, signature=abcdef0123 "
                 "and key super-secret-value-123 and sk-ant-api03-ABCDEFGHIJKLMNOP")
    text = caplog.text
    assert "super-secret-value-123" not in text and "abcdef0123" not in text and "AK123" not in text
    assert "sk-ant-api03-ABCDEFGHIJKLMNOP" not in text and "REDACTED" in text
    obj = redact_obj({"access_token": "tok", "nested": {"client_secret": "s", "ok": "fine"}})
    assert obj["access_token"] == "***REDACTED***" and obj["nested"]["client_secret"] == "***REDACTED***"
    assert obj["nested"]["ok"] == "fine"
    assert "Bearer" not in redact("Authorization: Bearer abc.def.ghi") or "abc.def.ghi" not in redact(
        "Authorization: Bearer abc.def.ghi")


def test_failed_api_call_records_redacted_error(env):
    import requests

    from app.models import ApiUsage
    from services.common.db import session_scope
    from services.common.http import ExternalAPIError, HttpClient, HttpConfig
    from sqlalchemy import select

    class Resp:
        status_code = 500
        text = "server error access_token=LEAKME123"
        headers = {}
        ok = False

    class Sess:
        def request(self, *a, **k):
            return Resp()

    c = HttpClient("unit", HttpConfig(max_retries=1, backoff_base=0), session=Sess(), sleep=lambda s: None)
    try:
        c.get("https://example.invalid/x", operation="unit.op")
    except ExternalAPIError as exc:
        assert "LEAKME123" not in str(exc)
    with session_scope() as s:
        row = s.scalars(select(ApiUsage)).one()
        assert row.success is False and row.attempts == 2 and "LEAKME123" not in (row.error or "")


def test_env_files_ignored_and_no_hardcoded_keys():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi and "*.db" in gi and "outputs/" in gi
    patterns = [re.compile(p) for p in (r"sk-ant-[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}", r"ghp_[A-Za-z0-9]{30,}",
                                        r"EAAB[A-Za-z0-9]{30,}", r"ya29\.[A-Za-z0-9_\-]{20,}")]
    for path in ROOT.rglob("*"):
        if path.is_dir() or any(part in {".venv", "outputs", "__pycache__", ".git", "assets", "demo"} for part in path.parts):
            continue
        if path.suffix in {".png", ".mp4", ".ttf", ".db", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in patterns:
            assert not pat.search(text), f"{path}: {pat.pattern}"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if re.match(r"^(\w*(KEY|SECRET|TOKEN|PASSWORD)\w*)=", line):
            assert line.split("=", 1)[1].strip() == "", f".env.example 에 값이 들어 있음: {line}"


def test_dotenv_not_tracked_by_git():
    out = subprocess.run(["git", "ls-files", "--", "shopping_content_factory/.env", ".env"], cwd=ROOT.parent,
                         capture_output=True, text=True)
    assert out.stdout.strip() == ""
