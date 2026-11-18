"""작업 큐: 중복 실행 방지, 상류 실패 → 하류 건너뜀, 재시도 한도, 비용 상한."""
from datetime import date

import pytest
from sqlalchemy import select

D = date(2026, 11, 18)


def test_stage_runs_once_per_day(env):
    from workflows.pipeline import run_stage

    assert run_stage(D, "collect_trends")["status"] == "succeeded"
    assert run_stage(D, "collect_trends")["status"] == "already_succeeded"
    assert run_stage(D, "collect_trends", force=True)["status"] == "succeeded"


def test_downstream_skipped_when_upstream_missing(env):
    from workflows.pipeline import run_stage

    res = run_stage(D, "score_candidates")
    assert res["status"] == "skipped_upstream" and "collect_trends" in res["message"]


def test_failure_retry_limit_and_backoff(env, monkeypatch):
    from app.models import JobRun
    from services.common.db import session_scope
    from workflows import pipeline

    calls = {"n": 0}

    def boom(d):
        calls["n"] += 1
        raise RuntimeError("일시 오류")

    monkeypatch.setattr(pipeline.STAGE_MAP["collect_trends"], "fn", boom)
    for _ in range(5):
        pipeline.run_stage(D, "collect_trends")
    assert calls["n"] == 3  # SCF_JOB_MAX_ATTEMPTS 기본 3
    with session_scope() as s:
        row = s.scalars(select(JobRun).where(JobRun.stage == "collect_trends")).one()
        assert row.status == "failed" and row.next_retry_at is not None and "일시 오류" in row.message
    assert pipeline.retry_ready(D, "collect_trends") is False


def test_policy_block_not_retried(env, monkeypatch):
    from workflows import pipeline

    def blocked(d):
        raise pipeline.PolicyBlock("기준 미달")

    monkeypatch.setattr(pipeline.STAGE_MAP["collect_trends"], "fn", blocked)
    assert pipeline.run_stage(D, "collect_trends")["status"] == "blocked"
    assert pipeline.run_stage(D, "collect_trends")["status"] == "blocked"
    assert pipeline.retry_ready(D, "collect_trends") is False


def test_file_lock_prevents_concurrent_runs(env):
    from config.settings import get_settings
    from workflows.pipeline import FileLock

    lock_path = get_settings().output_dir / ".pipeline.lock"
    with FileLock(lock_path):
        with pytest.raises(RuntimeError):
            with FileLock(lock_path):
                pass
    assert not lock_path.exists()


def test_cost_cap_blocks_paid_llm_and_is_logged(env, monkeypatch):
    from app.models import ApiUsage
    from config.settings import reload_settings
    from services.common.cost_guard import CostCapExceeded, check_budget
    from services.common.db import session_scope

    with session_scope() as s:
        s.add(ApiUsage(provider="anthropic", operation="script", cost_krw=2990.0))
    with pytest.raises(CostCapExceeded):
        check_budget(50.0, "anthropic.script")
    monkeypatch.setenv("SCF_COST_CAP_DAILY_KRW", "100000")
    reload_settings()
    check_budget(50.0, "anthropic.script")


def test_anthropic_client_with_fake_sdk_records_cost(env, monkeypatch):
    from types import SimpleNamespace

    from adapters.llm.anthropic_client import AnthropicJSONClient, LLMRefusal
    from app.models import ApiUsage
    from config.settings import get_settings
    from services.common.db import session_scope

    class FakeMessages:
        def __init__(self, stop="end_turn"):
            self.stop = stop
            self.kwargs = None

        def create(self, **kw):
            self.kwargs = kw
            return SimpleNamespace(model="claude-opus-5-5", stop_reason=self.stop, stop_details=None,
                                   usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
                                   content=[SimpleNamespace(type="text", text='{"ok": true}')])

    msgs = FakeMessages()
    client = AnthropicJSONClient(get_settings(), client=SimpleNamespace(beta=SimpleNamespace(messages=msgs)))
    data, meta = client.generate("script", "sys", "user", {"type": "object"})
    assert data == {"ok": True}
    assert msgs.kwargs["fallbacks"] == "default" and msgs.kwargs["thinking"] == {"type": "adaptive"}
    assert msgs.kwargs["output_config"]["format"]["type"] == "json_schema"
    expected = (1000 / 1e6 * 4 + 500 / 1e6 * 20) * get_settings().usd_krw
    assert meta["cost_krw"] == pytest.approx(expected, abs=0.01)
    with session_scope() as s:
        row = s.scalars(select(ApiUsage).where(ApiUsage.provider == "anthropic")).one()
        assert row.cost_krw == pytest.approx(expected, abs=0.01) and row.success
    refusing = AnthropicJSONClient(get_settings(), client=SimpleNamespace(
        beta=SimpleNamespace(messages=FakeMessages(stop="refusal"))))
    with pytest.raises(LLMRefusal):
        refusing.generate("script", "sys", "user", {"type": "object"})
