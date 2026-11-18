"""실측·추정 분리, 미귀속 매출 비귀속, CSV 품질 게이트."""
from tests.conftest import RUN_DATE, register_verified_link

CID = "C20261118-01"


def _write(path, text):
    path.write_text(text, encoding="utf-8-sig")
    return path


def test_measured_vs_estimated_and_unattributed(pipeline):
    from app.models import SiteEvent
    from services.analytics.funnel import content_funnels, unattributed_affiliate
    from services.analytics.importers import import_affiliate_csv, import_metrics_csv
    from services.common.db import session_scope

    register_verified_link()  # sub-c01 ↔ C20261118-01
    with session_scope() as s:
        for _ in range(10):
            s.add(SiteEvent(event_type="page_view", product_id="DEMO-001", content_id=CID, src="ig"))
        for _ in range(4):
            s.add(SiteEvent(event_type="link_click", product_id="DEMO-001", content_id=CID, src="ig"))
    m = import_metrics_csv(_write(pipeline / "m.csv", "date,platform,content_id,variant,metric,value\n"
                                                         f"2026-11-19,instagram,{CID},A,views,2000\n"
                                                         f"2026-11-19,instagram,{CID},A,saved,15\n"))
    assert m["imported"] == 2
    a = import_affiliate_csv(_write(pipeline / "a.csv",
                                    "date,sub_id,clicks,orders,gmv_krw,commission_krw,cancel_count,cancel_amount_krw,status\n"
                                    "2026-11-19,sub-c01,4,1,65000,1950,0,0,pending\n"
                                    "2026-11-19,,30,3,150000,4500,0,0,pending\n"))
    assert a["imported"] == 2
    row = next(r for r in content_funnels() if r["content_id"] == CID)
    assert row["measured"]["views"] == 2000
    assert row["measured"]["landing_visits"] == 10 and row["measured"]["link_clicks"] == 4
    assert row["measured"]["commission_krw"] == 1950          # sub_id 로 귀속된 것만
    assert row["rates"]["landing_rate"] == 10 / 2000
    assert row["rpm_measured"] == 1950 / 2000 * 1000
    assert row["estimated"]["orders_low"] == 4 * 0.03 and row["estimated"]["orders_high"] == 4 * 0.08
    un = unattributed_affiliate()
    assert un["commission_krw"] == 4500 and un["orders"] == 3  # 미귀속은 콘텐츠에 나누지 않음


def test_no_metrics_means_waiting_not_zero(pipeline):
    from services.analytics.funnel import content_funnels

    row = next(r for r in content_funnels() if r["content_id"] == CID)
    assert row["measured"]["views"] is None
    assert row["measured"]["commission_krw"] is None and row["rpm_measured"] is None


def test_csv_quality_gate_rejects_bad_rows(pipeline):
    from services.analytics.importers import import_affiliate_csv, import_metrics_csv

    m = import_metrics_csv(_write(pipeline / "bad.csv", "date,platform,content_id,variant,metric,value\n"
                                                        "2026-11-19,instagram,NOPE,A,views,10\n"
                                                        f"2026-11-19,instagram,{CID},A,views,-5\n"
                                                        f"2026-11-19,tiktok,{CID},A,views,5\n"
                                                        f"2026-11-19,instagram,{CID},A,revenue,5\n"
                                                        f"bad-date,instagram,{CID},A,views,5\n"))
    assert m["imported"] == 0 and len(m["rejected"]) == 5
    a = import_affiliate_csv(_write(pipeline / "bad2.csv",
                                    "date,sub_id,clicks,orders,gmv_krw,commission_krw,cancel_count,cancel_amount_krw,status\n"
                                    "2026-11-19,x,1,2,0,0,0,0,pending\n"
                                    "2026-11-19,x,-1,0,0,0,0,0,pending\n"))
    assert a["imported"] == 0 and len(a["rejected"]) == 2


def test_daily_report_generated(pipeline):
    from services.analytics.reports import build_daily_report

    res = build_daily_report(RUN_DATE)
    html = open(res["report"], encoding="utf-8").read()
    assert "데이터 기준" in html and "연동 대기" in html and "조회수·좋아요는 매출이 아닙니다" in html


def test_learning_needs_enough_samples(pipeline):
    from services.analytics.learning import category_profit_multiplier

    assert category_profit_multiplier("desk_cable") is None
