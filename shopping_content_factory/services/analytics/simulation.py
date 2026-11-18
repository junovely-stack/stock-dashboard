"""12개월 수익 시뮬레이션 (보수·기준·낙관) + 손익분기 표.

모든 입력은 config/finance.toml 의 '가정'이다. 벤치마크가 아니다.
확대 규칙: 직전 2개월 '현금이익(노동비 제외)'이 모두 0 초과일 때만 하루 콘텐츠 수를 scale_to_per_day 로 늘린다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from config.settings import load_policy
from services.analytics import finance as F


@dataclass
class MonthRow:
    month: int
    contents_per_day: int
    contents: int
    views_per_content: float
    views: float
    landing_visits: float
    link_clicks: float
    orders: float
    gross_gmv: float
    recognized_gmv: float
    revenue: float
    cash_opex: float
    build_cost: float
    labor_hours: float
    labor_cost: float
    cash_profit: float
    adjusted_profit: float


def simulate(scenario: dict, a: dict, months: int = 12) -> dict:
    rows: list[MonthRow] = []
    per_day = scenario["contents_per_day"]
    for m in range(1, months + 1):
        if m >= 3 and per_day < scenario["scale_to_per_day"]:
            if rows[-1].cash_profit > 0 and rows[-2].cash_profit > 0:
                per_day = scenario["scale_to_per_day"]
        frac = (m - 1) / (months - 1) if months > 1 else 0
        vpc = scenario["views_start"] + (scenario["views_end"] - scenario["views_start"]) * frac
        contents = per_day * a["days_per_month"]
        views = vpc * contents
        landing = views * scenario["landing_rate"]
        clicks = landing * scenario["link_ctr"]
        orders = clicks * scenario["purchase_cvr"]
        gross = orders * a["avg_order_value_krw"]
        recognized = gross * (1 - a["cancel_rate"])
        revenue = F.affiliate_revenue(recognized, a["effective_commission_rate"])
        hours = a["founder_hours_per_month"] + a["extra_hours_per_extra_daily_content"] * (per_day - 1)
        labor = F.labor_cost(hours, a["labor_rate_krw_per_hour"])
        build = a["initial_build_cost_krw"] if m == 1 else 0
        cash_opex = a["monthly_cash_opex_krw"]
        rows.append(MonthRow(m, per_day, contents, vpc, views, landing, clicks, orders, gross, recognized, revenue,
                             cash_opex, build, hours, labor, revenue - cash_opex - build,
                             F.adjusted_profit(revenue, cash_opex, build, labor)))
    total = lambda f: sum(getattr(r, f) for r in rows)  # noqa: E731
    adj = total("adjusted_profit")
    at = F.after_tax(adj, a["tax_rate"])
    return {
        "label": scenario["label"], "assumptions": scenario, "months": [asdict(r) for r in rows],
        "annual": {"views": total("views"), "orders": total("orders"), "revenue": total("revenue"),
                   "cash_opex": total("cash_opex"), "build_cost": total("build_cost"),
                   "labor_cost": total("labor_cost"), "cash_profit": total("cash_profit"),
                   "adjusted_profit": adj, "after_tax_adjusted_profit": at,
                   "adjusted_roe_pct": F.adjusted_roe(at, a["initial_equity_krw"]),
                   "rpm": F.rpm(total("revenue"), total("views"))},
    }


def breakeven_table(a: dict, scenarios: dict) -> list[dict]:
    """1일 1콘텐츠 기준, 월 조정이익 0 과 연 ROE 목표를 맞추는 데 필요한 월 조회수."""
    monthly_fixed = a["monthly_cash_opex_krw"] + a["founder_hours_per_month"] * a["labor_rate_krw_per_hour"]
    target_after_tax = a["initial_equity_krw"] * a["target_roe_pct"] / 100
    target_pre_tax = target_after_tax / (1 - a["tax_rate"])
    roe_monthly_rev = monthly_fixed + (a["initial_build_cost_krw"] + target_pre_tax) / 12
    out = []
    for key, sc in scenarios.items():
        args = (a["avg_order_value_krw"], a["effective_commission_rate"], sc["landing_rate"], sc["link_ctr"],
                sc["purchase_cvr"], a["cancel_rate"])
        be = F.required_monthly_views(monthly_fixed, *args)
        roe = F.required_monthly_views(roe_monthly_rev, *args)
        per_view = F.revenue_per_view_chain(*args)
        out.append({"scenario": sc["label"], "funnel": f"{sc['landing_rate']:.1%} × {sc['link_ctr']:.0%} × "
                                                       f"{sc['purchase_cvr']:.0%}",
                    "revenue_per_1k_views": per_view * 1000, "monthly_fixed_cost": monthly_fixed,
                    "breakeven_monthly_views": be, "breakeven_views_per_content": be / a["days_per_month"],
                    "roe_target_monthly_views": roe, "roe_target_views_per_content": roe / a["days_per_month"]})
    return out


def run_all() -> dict:
    fin = load_policy("finance")
    a = fin["assumptions"]
    sims = {k: simulate(v, a) for k, v in fin["scenarios"].items()}
    return {"assumptions": a, "scenarios": sims, "breakeven": breakeven_table(a, fin["scenarios"])}


def to_markdown(result: dict) -> str:
    a = result["assumptions"]
    w = lambda x: f"{x:,.0f}"  # noqa: E731
    lines = ["# 12개월 수익 시뮬레이션 (가정 기반)", "",
             "> 모든 입력은 `config/finance.toml` 의 **가정**입니다. 업계 벤치마크가 아니며, 실측 30개 콘텐츠가 쌓이면 실측치로 교체합니다.",
             "> `python scf.py simulate` 로 다시 생성됩니다. 산식은 `services/analytics/finance.py`, 검산은 `tests/test_finance.py`.", "",
             "## 공통 가정", "", "| 항목 | 값 |", "|---|---|",
             f"| 초기 자기자본 | {w(a['initial_equity_krw'])}원 |", f"| 평균 인정 구매금액 | {w(a['avg_order_value_krw'])}원 |",
             f"| 실효 수수료율 | {a['effective_commission_rate']:.1%} (가상) |",
             f"| 초기 현금 구축비 | {w(a['initial_build_cost_krw'])}원 (1개월차) |",
             f"| 월 운영현금비 | {w(a['monthly_cash_opex_krw'])}원 |",
             f"| 창업자 노동 | {a['founder_hours_per_month']}시간/월 × {w(a['labor_rate_krw_per_hour'])}원 |",
             f"| 취소·반품 제외 | {a['cancel_rate']:.0%} (가정) |", f"| 세율 | {a['tax_rate']:.1%} (가정, 손실 시 0) |", "",
             "## 시나리오별 연간 결과", "",
             "| 시나리오 | 퍼널(랜딩×클릭×구매) | 콘텐츠당 조회 1→12월 | 연 조회 | 연 주문 | 연 제휴수익 | 현금이익(노동비 제외) | 조정이익 | 조정 ROE |",
             "|---|---|---|---|---|---|---|---|---|"]
    for sim in result["scenarios"].values():
        sc, an = sim["assumptions"], sim["annual"]
        lines.append(f"| {sim['label']} | {sc['landing_rate']:.1%}×{sc['link_ctr']:.0%}×{sc['purchase_cvr']:.0%} | "
                     f"{w(sc['views_start'])}→{w(sc['views_end'])} | {w(an['views'])} | {an['orders']:,.1f} | "
                     f"{w(an['revenue'])}원 | {w(an['cash_profit'])}원 | {w(an['adjusted_profit'])}원 | "
                     f"{an['adjusted_roe_pct']:.1f}% |")
    lines += ["", f"목표 조정 ROE {a['target_roe_pct']}% 대비 판정은 아래 손익분기 표로 봅니다. 가정을 바꿔 목표를 맞추지 않습니다.", "",
              "## 손익분기 — 1일 1콘텐츠 기준 필요한 조회수", "",
              "| 시나리오 퍼널 | 조회 1,000회당 수익 | 월 고정비(현금+노동) | 월 손익분기 조회 | 콘텐츠당 | ROE 목표 월 조회 | 콘텐츠당 |",
              "|---|---|---|---|---|---|---|"]
    for b in result["breakeven"]:
        lines.append(f"| {b['scenario']} {b['funnel']} | {b['revenue_per_1k_views']:,.1f}원 | {w(b['monthly_fixed_cost'])}원 | "
                     f"{w(b['breakeven_monthly_views'])} | {w(b['breakeven_views_per_content'])} | "
                     f"{w(b['roe_target_monthly_views'])} | {w(b['roe_target_views_per_content'])} |")
    for sim in result["scenarios"].values():
        lines += ["", f"### 월별 — {sim['label']}", "",
                  "| 월 | 하루 콘텐츠 | 콘텐츠당 조회 | 월 조회 | 주문 | 제휴수익 | 현금비 | 구축비 | 노동비 | 조정이익 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in sim["months"]:
            lines.append(f"| {r['month']} | {r['contents_per_day']} | {w(r['views_per_content'])} | {w(r['views'])} | "
                         f"{r['orders']:,.1f} | {w(r['revenue'])} | {w(r['cash_opex'])} | {w(r['build_cost'])} | "
                         f"{w(r['labor_cost'])} | {w(r['adjusted_profit'])} |")
    return "\n".join(lines) + "\n"
