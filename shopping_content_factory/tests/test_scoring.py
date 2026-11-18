from datetime import timedelta

from sqlalchemy import select

from tests.conftest import RUN_DATE


def _scored(env_dir):
    from services.product_discovery.discovery import discover_products
    from services.product_scoring.scoring import score_candidates
    from services.trend_collector.collector import collect_trends

    collect_trends(RUN_DATE)
    discover_products(RUN_DATE)
    return score_candidates(RUN_DATE)


def test_scores_are_0_to_100_and_breakdown_sums(env):
    from app.models import ProductScore
    from config.settings import load_policy
    from services.common.db import session_scope

    res = _scored(env)
    weights = load_policy("scoring")["weights"]
    assert sum(weights.values()) == 100
    with session_scope() as s:
        for sc in s.scalars(select(ProductScore)):
            assert 0 <= sc.total <= 100
            sub = sum(v["score"] for v in sc.breakdown.values())
            pen = sum(p["points"] for p in sc.penalties)
            assert abs(max(0, sub - pen) - sc.total) < 0.05
            for k, v in sc.breakdown.items():
                assert 0 <= v["score"] <= v["max"] == weights[k]
                assert v["evidence"]
    assert len(res["top5"]) == 5


def test_hard_filters(env):
    from app.models import ProductScore
    from services.common.db import session_scope

    _scored(env)
    with session_scope() as s:
        by = {sc.product_id: sc for sc in s.scalars(select(ProductScore))}
    assert by["DEMO-005"].filter_result == "exclude"   # 품절
    assert by["DEMO-009"].filter_result == "exclude"   # 검증 불가 효과
    assert by["DEMO-018"].filter_result == "exclude"   # 규제 위험(락스)
    assert by["DEMO-012"].filter_result == "exclude"   # 30일 내 동일 상품
    assert by["DEMO-024"].filter_result == "exclude"   # 안전 위험
    assert by["DEMO-003"].filter_result == "hold"      # 이미지 권리 미확인
    assert by["DEMO-015"].filter_result == "hold"      # 점수 높아도 권리 미확인이면 보류
    assert by["DEMO-008"].filter_result == "hold"      # 사양 부족
    assert by["DEMO-011"].filter_result == "hold"      # 가격 확인 만료
    assert any("이미지 사용권" in r for r in by["DEMO-015"].filter_reasons)
    assert by["DEMO-013"].penalties and by["DEMO-014"].penalties  # 가격 변동·재고 부족 감점


def test_conservative_scoring_when_evidence_missing(env):
    from app.models import Product
    from services.product_scoring.scoring import score_problem, score_visual, score_interest

    p = Product(id="X", slug="x", name="x", category_key="desk_cable", problem={}, signals={})
    rules = {"conservative_cap": 0.3, "mock_evidence_cap": 0.8}
    c1 = score_problem(p, 20, rules)
    c2 = score_visual(p, 10, rules)
    c3 = score_interest(p, [], 15, rules)
    assert c1.conservative and c1.score <= 20 * 0.3
    assert c2.conservative and c2.score <= 10 * 0.3
    assert c3.conservative and c3.score <= 15 * 0.3


def test_selection_is_logged_and_final_chosen(env):
    from app.models import SelectionLog
    from services.common.db import session_scope
    from services.product_scoring.selection import select_final

    _scored(env)
    res = select_final(RUN_DATE)
    assert res["final"] == "DEMO-001"
    with session_scope() as s:
        steps = [l.step for l in s.scalars(select(SelectionLog).where(SelectionLog.run_date == RUN_DATE))]
    assert steps == ["discover", "score", "final"]


def test_final_skips_candidate_that_fails_reverification(env):
    from app.models import Product
    from services.common.db import session_scope
    from services.common.timeutil import now_utc
    from services.product_scoring.selection import select_final

    _scored(env)
    with session_scope() as s:
        s.get(Product, "DEMO-001").price_checked_at = now_utc() - timedelta(hours=48)
    res = select_final(RUN_DATE)
    assert res["final"] != "DEMO-001"
    assert "가격 확인 만료" in res["checked"][0]["problems"]


def test_nothing_produced_when_below_min_score(env, monkeypatch):
    import pytest

    from config.settings import reload_settings
    from services.product_scoring.selection import NothingToProduce, select_final

    _scored(env)
    monkeypatch.setenv("SCF_MIN_FINAL_SCORE", "99")
    reload_settings()
    with pytest.raises(NothingToProduce):
        select_final(RUN_DATE)
