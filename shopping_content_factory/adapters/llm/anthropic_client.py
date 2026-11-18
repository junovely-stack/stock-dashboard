"""Anthropic Claude 구조화 출력 클라이언트.

- LLM 은 '문장 초안'만 만든다. 점수·수치·사실 판단은 파이썬 규칙이 한다.
- 출력은 JSON Schema 로 강제(output_config.format) → 이후 fact_guard·정책 검사를 다시 통과해야 한다.
- 호출 전 비용 상한 확인, 호출 후 실제 usage 로 비용 기록.
- 안전 분류기 거절(stop_reason=refusal)은 서버측 fallbacks="default" 로 대체 모델이 이어받게 하고,
  그래도 거절이면 예외 → 해당 단계 BLOCKED.
"""
from __future__ import annotations

import json
import time

from config.settings import Settings, load_policy
from services.common.cost_guard import anthropic_cost_krw, check_budget
from services.common.http import NotConfiguredError, record_usage
from services.common.logging_utils import get_logger

log = get_logger(__name__)


class LLMRefusal(RuntimeError):
    pass


class LLMOutputError(RuntimeError):
    pass


class AnthropicJSONClient:
    provider = "anthropic"

    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.model = settings.anthropic_model
        self._client = client

    def is_configured(self) -> bool:
        return self._client is not None or self.settings.anthropic_api_key_present

    def client(self):
        if self._client is None:
            if not self.settings.anthropic_api_key_present:
                raise NotConfiguredError("ANTHROPIC_API_KEY 없음")
            import anthropic

            self._client = anthropic.Anthropic(max_retries=2, timeout=180.0)
        return self._client

    def estimate_cost_krw(self, stage: str) -> float:
        est = load_policy("costs")["estimate"]
        return anthropic_cost_krw(self.model, est[f"{stage}_input_tokens"], est[f"{stage}_output_tokens"])

    def generate(self, stage: str, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        check_budget(self.estimate_cost_krw(stage), f"anthropic.{stage}")
        import anthropic

        started = time.monotonic()
        try:
            resp = self.client().beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.anthropic_effort,
                               "format": {"type": "json_schema", "schema": schema}},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.RateLimitError as exc:
            record_usage(self.provider, stage, status_code=429, success=False, error=str(exc))
            raise
        except anthropic.APIStatusError as exc:
            record_usage(self.provider, stage, status_code=exc.status_code, success=False, error=str(exc))
            raise
        except anthropic.APIConnectionError as exc:
            record_usage(self.provider, stage, success=False, error=str(exc))
            raise

        served_model = getattr(resp, "model", self.model) or self.model
        usage = resp.usage
        try:
            cost = anthropic_cost_krw(served_model, usage.input_tokens, usage.output_tokens)
        except Exception:  # noqa: BLE001 — 대체 모델 단가 미등록 시 요청 모델 단가로 기록
            cost = anthropic_cost_krw(self.model, usage.input_tokens, usage.output_tokens)
        record_usage(self.provider, stage, status_code=200, success=resp.stop_reason not in {"refusal", "max_tokens"},
                     latency_ms=int((time.monotonic() - started) * 1000),
                     units=float(usage.input_tokens + usage.output_tokens), cost_krw=cost,
                     error=None if resp.stop_reason not in {"refusal", "max_tokens"} else resp.stop_reason)
        meta = {"model": served_model, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                "cost_krw": cost, "stop_reason": resp.stop_reason}
        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"모델 거절: {getattr(resp, 'stop_details', None)}")
        if resp.stop_reason == "max_tokens":
            raise LLMOutputError("출력이 max_tokens 에서 잘림")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if not text:
            raise LLMOutputError("텍스트 블록 없음")
        try:
            return json.loads(text), meta
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"JSON 파싱 실패: {exc}") from exc
