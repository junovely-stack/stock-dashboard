from datetime import date

from sqlalchemy import select

from tests.conftest import RUN_DATE


def test_mock_trends_have_source_time_raw_confidence(env):
    from app.models import TrendSnapshot
    from services.common.db import session_scope
    from services.trend_collector.collector import collect_trends

    summary = collect_trends(RUN_DATE)
    assert summary["keywords"] >= 20
    assert summary["excluded_buzz"] == 3  # 랜선집들이·밈·브이로그
    with session_scope() as s:
        rows = list(s.scalars(select(TrendSnapshot)))
        for t in rows:
            assert t.collected_at is not None
            assert t.source_url and t.raw_ref
            assert t.confidence == "mock"
        buzz = [t for t in rows if t.intent == "buzz"]
        assert all(t.excluded_reason for t in buzz)


def test_trend_features_and_dedupe():
    from services.trend_collector.collector import classify_intent, normalize_keyword, series_features

    series = [{"period": f"2026-10-{i + 1:02d}", "ratio": 10.0} for i in range(28)] + \
             [{"period": f"2026-11-{i + 1:02d}", "ratio": 20.0} for i in range(7)]
    f = series_features(series)
    assert f["latest"] == 20.0
    assert abs(f["growth_7d"] - 1.0) < 1e-9
    assert normalize_keyword("  케이블   정리 ") == normalize_keyword("케이블 정리")
    assert classify_intent("케이블 정리 밈") == "buzz"
    assert classify_intent("무타공 선반") == "purchase"


def test_rerun_is_idempotent(env):
    from app.models import TrendSnapshot
    from services.common.db import session_scope
    from services.trend_collector.collector import collect_trends

    collect_trends(RUN_DATE)
    collect_trends(RUN_DATE)
    with session_scope() as s:
        n = len(list(s.scalars(select(TrendSnapshot).where(TrendSnapshot.run_date == RUN_DATE))))
    assert n == 28


def test_discovery_collects_at_least_20_candidates(env):
    from services.product_discovery.discovery import discover_products
    from services.trend_collector.collector import collect_trends

    collect_trends(RUN_DATE)
    res = discover_products(RUN_DATE)
    assert res["candidates"] >= 20
    assert res["insufficient"] is False


def test_naver_anchor_rescale_and_body():
    from adapters.naver.datalab import NaverDataLabAdapter, rescale_by_anchor

    body = NaverDataLabAdapter.build_keyword_body("50000004", "책상 정리", ["a", "b", "c", "d", "e"],
                                                  date(2026, 10, 1), date(2026, 11, 1))
    assert len(body["keyword"]) == 5 and body["keyword"][0]["name"] == "책상 정리"
    results = [{"title": "책상 정리", "data": [{"period": "p1", "ratio": 50}, {"period": "p2", "ratio": 50}]},
               {"title": "a", "data": [{"period": "p1", "ratio": 100}, {"period": "p2", "ratio": 25}]}]
    out = rescale_by_anchor(results, "책상 정리")
    assert out["a"][0]["ratio"] == 100.0 and out["a"][1]["ratio"] == 25.0 and "책상 정리" not in out
