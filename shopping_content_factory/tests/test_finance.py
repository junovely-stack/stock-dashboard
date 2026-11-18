"""재무 산식 검산 — 손으로 계산한 값과 비교."""
import pytest

from services.analytics import finance as F
from services.analytics.simulation import breakeven_table, simulate


def test_basic_formulas():
    assert F.affiliate_revenue(65000, 0.03) == pytest.approx(1950)
    assert F.expected_orders(100_000, 0.01, 0.30, 0.05) == pytest.approx(15)
    assert F.labor_cost(30, 25000) == 750_000
    assert F.adjusted_profit(1_000_000, 250_000, 1_000_000, 750_000) == -1_000_000
    assert F.after_tax(1_000_000, 0.066) == pytest.approx(934_000)
    assert F.after_tax(-500_000, 0.066) == -500_000          # 손실이면 세금 없음
    assert F.adjusted_roe(1_250_000, 5_000_000) == pytest.approx(25.0)
    assert F.rpm(1950, 100_000) == pytest.approx(19.5)
    assert F.rpm(100, 0) is None
    with pytest.raises(ValueError):
        F.adjusted_roe(1, 0)


def test_revenue_per_view_and_required_views():
    # 조회 1회 → 0.01 × 0.3 × 0.05 = 0.00015 주문 → × 65,000 × 0.95 × 0.03 = 0.2778750원
    per_view = F.revenue_per_view_chain(65000, 0.03, 0.01, 0.30, 0.05, 0.05)
    assert per_view == pytest.approx(0.277875)
    assert F.required_monthly_views(1_000_000, 65000, 0.03, 0.01, 0.30, 0.05, 0.05) == pytest.approx(1_000_000 / 0.277875)


A = {"initial_equity_krw": 5_000_000, "avg_order_value_krw": 65000, "effective_commission_rate": 0.03,
     "initial_build_cost_krw": 1_000_000, "monthly_cash_opex_krw": 250_000, "founder_hours_per_month": 30,
     "labor_rate_krw_per_hour": 25000, "extra_hours_per_extra_daily_content": 10, "tax_rate": 0.066,
     "cancel_rate": 0.0, "days_per_month": 30, "target_roe_pct": 25}


def test_simulation_hand_calculated_constant_views():
    sc = {"label": "t", "views_start": 10000, "views_end": 10000, "landing_rate": 0.01, "link_ctr": 0.3,
          "purchase_cvr": 0.05, "contents_per_day": 1, "scale_to_per_day": 1}
    r = simulate(sc, A)
    m1 = r["months"][0]
    # 월 조회 10,000×30=300,000 → 주문 45 → 구매액 2,925,000 → 수익 87,750
    assert m1["views"] == 300_000 and m1["orders"] == pytest.approx(45)
    assert m1["revenue"] == pytest.approx(87_750)
    assert m1["adjusted_profit"] == pytest.approx(87_750 - 250_000 - 1_000_000 - 750_000)
    an = r["annual"]
    assert an["revenue"] == pytest.approx(87_750 * 12)
    expected_adj = 87_750 * 12 - 250_000 * 12 - 1_000_000 - 750_000 * 12
    assert an["adjusted_profit"] == pytest.approx(expected_adj)
    assert an["adjusted_roe_pct"] == pytest.approx(expected_adj / 5_000_000 * 100)   # 손실 → 세금 0
    assert an["rpm"] == pytest.approx(87_750 / 300_000 * 1000)


def test_scale_up_only_after_two_profitable_months():
    sc = {"label": "t", "views_start": 400_000, "views_end": 400_000, "landing_rate": 0.01, "link_ctr": 0.3,
          "purchase_cvr": 0.05, "contents_per_day": 1, "scale_to_per_day": 3}
    r = simulate(sc, A)
    per_day = [m["contents_per_day"] for m in r["months"]]
    assert per_day[:2] == [1, 1]
    # 1월은 구축비 때문에 현금이익이 음수일 수 있으므로 2·3월 연속 흑자 후 4월부터 확대
    first_scaled = per_day.index(3)
    profits = [m["cash_profit"] for m in r["months"]]
    assert profits[first_scaled - 1] > 0 and profits[first_scaled - 2] > 0
    assert r["months"][first_scaled]["labor_hours"] == 30 + 10 * 2


def test_breakeven_table_math():
    sc = {"base": {"label": "기준", "landing_rate": 0.01, "link_ctr": 0.3, "purchase_cvr": 0.05}}
    b = breakeven_table(A, sc)[0]
    per_view = 0.01 * 0.3 * 0.05 * 65000 * 0.03
    assert b["monthly_fixed_cost"] == 1_000_000
    assert b["breakeven_monthly_views"] == pytest.approx(1_000_000 / per_view)
    target_pre_tax = 5_000_000 * 0.25 / (1 - 0.066)
    assert b["roe_target_monthly_views"] == pytest.approx((1_000_000 + (1_000_000 + target_pre_tax) / 12) / per_view)


def test_default_config_runs_and_reports_honestly():
    from services.analytics.simulation import run_all, to_markdown

    res = run_all()
    assert set(res["scenarios"]) == {"conservative", "base", "optimistic"}
    md = to_markdown(res)
    assert "가정" in md and "벤치마크가 아니며" in md
    cons, opt = res["scenarios"]["conservative"]["annual"], res["scenarios"]["optimistic"]["annual"]
    assert cons["adjusted_roe_pct"] < opt["adjusted_roe_pct"]
