"""외부 API 공통 HTTP 클라이언트.

- 연결/읽기 타임아웃
- 429·5xx·네트워크 오류만 재시도 (4xx 는 재시도하지 않음)
- 지수 백오프 + 지터, Retry-After 준수, 재시도 횟수 상한
- 분당 호출 제한(프로세스 내 토큰버킷)
- 호출 결과는 api_usage 테이블에 기록 (비밀값 마스킹)
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from services.common.logging_utils import get_logger, redact

log = get_logger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class ExternalAPIError(RuntimeError):
    def __init__(self, provider: str, message: str, status_code: int | None = None):
        super().__init__(redact(f"[{provider}] {message}"))
        self.provider = provider
        self.status_code = status_code


class NotConfiguredError(RuntimeError):
    """자격증명·권한이 없어 실제 호출을 하지 않음 (mock/대기 상태로 처리해야 함)."""


class _RateLimiter:
    def __init__(self, per_minute: int | None):
        self.per_minute = per_minute
        self.lock = threading.Lock()
        self.calls: list[float] = []

    def wait(self, sleep: Callable[[float], None]) -> None:
        if not self.per_minute:
            return
        with self.lock:
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < 60]
            if len(self.calls) >= self.per_minute:
                delay = 60 - (now - self.calls[0])
                if delay > 0:
                    sleep(delay)
            self.calls.append(time.monotonic())


@dataclass
class HttpConfig:
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    max_retries: int = 3
    backoff_base: float = 1.0
    max_backoff: float = 30.0
    per_minute: int | None = None


def record_usage(provider: str, operation: str, **fields: Any) -> None:
    """api_usage 기록. DB 가 없거나 실패해도 본 작업을 깨지 않는다."""
    try:
        from app.models import ApiUsage
        from services.common.db import session_scope

        with session_scope() as s:
            s.add(
                ApiUsage(
                    provider=provider,
                    operation=operation,
                    status_code=fields.get("status_code"),
                    success=fields.get("success", True),
                    latency_ms=fields.get("latency_ms"),
                    attempts=fields.get("attempts", 1),
                    units=fields.get("units"),
                    cost_krw=fields.get("cost_krw", 0.0),
                    error=redact(fields["error"])[:2000] if fields.get("error") else None,
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("api_usage 기록 실패: %s", exc)


class HttpClient:
    def __init__(
        self,
        provider: str,
        config: HttpConfig | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        recorder: Callable[..., None] | None = record_usage,
    ):
        self.provider = provider
        self.config = config or HttpConfig()
        self.session = session or requests.Session()
        self.sleep = sleep
        self.recorder = recorder
        self.limiter = _RateLimiter(self.config.per_minute)

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.config.max_backoff)
            except ValueError:
                pass
        base = self.config.backoff_base * (2 ** attempt)
        return min(self.config.max_backoff, base + random.uniform(0, self.config.backoff_base))

    def request(self, method: str, url: str, operation: str = "", **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", (self.config.connect_timeout, self.config.read_timeout))
        last_error: str = ""
        status: int | None = None
        started = time.monotonic()
        for attempt in range(self.config.max_retries + 1):
            self.limiter.wait(self.sleep)
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                status = None
            else:
                status = resp.status_code
                if status not in RETRY_STATUS:
                    if self.recorder:
                        self.recorder(
                            self.provider,
                            operation or url.split("?")[0][-60:],
                            status_code=status,
                            success=resp.ok,
                            latency_ms=int((time.monotonic() - started) * 1000),
                            attempts=attempt + 1,
                            error=None if resp.ok else resp.text[:500],
                        )
                    return resp
                last_error = f"HTTP {status}: {resp.text[:300]}"
                retry_after = resp.headers.get("Retry-After")
                if attempt < self.config.max_retries:
                    delay = self._backoff(attempt, retry_after)
                    log.warning("%s %s 재시도 %d/%d (%.1fs) — %s", self.provider, operation, attempt + 1,
                                self.config.max_retries, delay, last_error)
                    self.sleep(delay)
                continue
            if attempt < self.config.max_retries:
                delay = self._backoff(attempt, None)
                log.warning("%s %s 네트워크 오류 재시도 %d/%d (%.1fs) — %s", self.provider, operation,
                            attempt + 1, self.config.max_retries, delay, last_error)
                self.sleep(delay)
        if self.recorder:
            self.recorder(
                self.provider,
                operation or url.split("?")[0][-60:],
                status_code=status,
                success=False,
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=self.config.max_retries + 1,
                error=last_error,
            )
        raise ExternalAPIError(self.provider, f"재시도 한도 초과: {last_error}", status)

    def get(self, url: str, **kw: Any) -> requests.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> requests.Response:
        return self.request("POST", url, **kw)
