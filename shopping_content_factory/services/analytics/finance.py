"""재무 산식 (순수 함수). 단위: 원(KRW). 비율은 0~1 소수.

제휴수익 = 인정 구매액 × 실효 수수료율
예상 구매건수 = 조회수 × 랜딩방문율 × 제휴링크클릭률 × 구매전환율
조정이익 = 제휴수익 - 현금운영비 - 초기 구축비 - 창업자 노동 기회비용
조정 ROE = 세후 조정이익 ÷ 초기 자기자본 × 100   (손실이면 세금 0)
"""
from __future__ import annotations


def affiliate_revenue(recognized_gmv: float, commission_rate: float) -> float:
    return recognized_gmv * commission_rate


def expected_orders(views: float, landing_rate: float, link_ctr: float, purchase_cvr: float) -> float:
    return views * landing_rate * link_ctr * purchase_cvr


def labor_cost(hours: float, rate_per_hour: float) -> float:
    return hours * rate_per_hour


def adjusted_profit(revenue: float, cash_opex: float, build_cost: float, labor: float) -> float:
    return revenue - cash_opex - build_cost - labor


def after_tax(profit: float, tax_rate: float) -> float:
    return profit * (1 - tax_rate) if profit > 0 else profit


def adjusted_roe(after_tax_profit: float, equity: float) -> float:
    if equity <= 0:
        raise ValueError("초기 자기자본은 0보다 커야 합니다")
    return after_tax_profit / equity * 100


def rpm(revenue: float, views: float) -> float | None:
    return revenue / views * 1000 if views > 0 else None


def revenue_per_view_chain(aov: float, rate: float, landing_rate: float, link_ctr: float, cvr: float,
                           cancel_rate: float = 0.0) -> float:
    """조회 1회당 기대 제휴수익."""
    return landing_rate * link_ctr * cvr * aov * (1 - cancel_rate) * rate


def required_monthly_views(target_monthly_revenue: float, aov: float, rate: float, landing_rate: float,
                           link_ctr: float, cvr: float, cancel_rate: float = 0.0) -> float | None:
    per_view = revenue_per_view_chain(aov, rate, landing_rate, link_ctr, cvr, cancel_rate)
    return target_monthly_revenue / per_view if per_view > 0 else None
