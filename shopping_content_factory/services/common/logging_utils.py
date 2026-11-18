"""로그·저장 데이터의 비밀값 마스킹.

원칙: 키·토큰·서명·비밀번호는 로그와 DB(원본 응답 저장 포함) 어디에도 평문으로 남기지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any

MASK = "***REDACTED***"
_SECRET_ENV_HINT = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD)", re.I)
_PATTERNS = [
    re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?)(bearer\s+)?[^\s\",}]+"),
    re.compile(r"(?i)(access-key=)[^,\s\"]+"),
    re.compile(r"(?i)(signature=)[^,\s\"&]+"),
    re.compile(r"(?i)((?:access|refresh|id)_token\"?\s*[:=]\s*\"?)[^&\s\",}]+"),
    re.compile(r"(?i)(client_secret\"?\s*[:=]\s*\"?)[^&\s\",}]+"),
    re.compile(r"(?i)(x-naver-client-secret\"?\s*[:=]\s*\"?)[^\s\",}]+"),
    re.compile(r"(?i)(x-api-key\"?\s*[:=]\s*\"?)[^\s\",}]+"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
]
_SECRET_KEYS = re.compile(r"(?i)(secret|token|password|passwd|api[_-]?key|access[_-]?key|signature|authorization)")


def _secret_values() -> list[str]:
    values = []
    for name, value in os.environ.items():
        if value and len(value) >= 6 and _SECRET_ENV_HINT.search(name):
            values.append(value)
    # 긴 값부터 치환해야 부분 일치로 일부가 남지 않는다
    return sorted(set(values), key=len, reverse=True)


def redact(text: Any) -> str:
    s = text if isinstance(text, str) else str(text)
    for value in _secret_values():
        s = s.replace(value, MASK)
    for pattern in _PATTERNS:
        if pattern.groups:
            s = pattern.sub(lambda m: (m.group(1) or "") + MASK, s)
        else:
            s = pattern.sub(MASK, s)
    return s


def redact_obj(obj: Any) -> Any:
    """dict/list 를 재귀적으로 돌며 비밀 키 이름의 값과 문자열 속 비밀값을 마스킹."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEYS.search(k):
                out[k] = MASK
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


def redact_json(obj: Any) -> str:
    return json.dumps(redact_obj(obj), ensure_ascii=False, default=str)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — 포맷 실패도 원문 노출 없이 처리
            message = str(record.msg)
        record.msg = redact(message)
        record.args = ()
        return True


_configured = False


def setup_logging(level: str | None = None, log_file: str | None = None) -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level or os.environ.get("SCF_LOG_LEVEL", "INFO"))
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactingFilter())
        root.addHandler(h)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())
    return logger
