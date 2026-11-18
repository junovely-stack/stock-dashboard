"""API 비용 상한.

- 유료 호출 전에 예상 비용 + 오늘/이번 달 누적이 상한을 넘으면 CostCapExceeded.
- 단가가 config/costs.toml 에 '미확인(-1)'이면 상한 판단이 불가하므로 실행을 막는다 (추측 금지).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config.settings import get_settings, load_policy
from services.common.timeutil import now_local


class CostCapExceeded(RuntimeError):
    pass


class UnpricedProvider(RuntimeError):
    pass


def anthropic_price(model: str) -> tuple[float, float]:
    table = load_policy("costs").get("anthropic", {})
    row = table.get(model)
    if not row or row.get("input_usd_per_mtok", -1) < 0:
        raise UnpricedProvider(f"{model} 단가가 config/costs.toml 에 없습니다. 공식 가격표 확인 후 입력하세요.")
    return float(row["input_usd_per_mtok"]), float(row["output_usd_per_mtok"])


def anthropic_cost_krw(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = anthropic_price(model)
    usd = input_tokens / 1_000_000 * inp + output_tokens / 1_000_000 * out
    return round(usd * get_settings().usd_krw, 2)


def _local_day_bounds_utc() -> tuple[datetime, datetime, datetime]:
    local_now = now_local()
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(day_start), to_utc(day_start + timedelta(days=1)), to_utc(month_start)


def spent_krw() -> tuple[float, float]:
    """(오늘 누적, 이번 달 누적) — api_usage + cost_entries(ai_api)."""
    from app.models import ApiUsage, CostEntry
    from services.common.db import session_scope

    day_start, day_end, month_start = _local_day_bounds_utc()
    with session_scope() as s:
        today = s.scalar(select(func.coalesce(func.sum(ApiUsage.cost_krw), 0.0)).where(
            ApiUsage.ts >= day_start, ApiUsage.ts < day_end)) or 0.0
        month = s.scalar(select(func.coalesce(func.sum(ApiUsage.cost_krw), 0.0)).where(
            ApiUsage.ts >= month_start)) or 0.0
        local_today = now_local().date()
        manual_today = s.scalar(select(func.coalesce(func.sum(CostEntry.amount_krw), 0)).where(
            CostEntry.cost_date == local_today, CostEntry.category == "ai_api")) or 0
        manual_month = s.scalar(select(func.coalesce(func.sum(CostEntry.amount_krw), 0)).where(
            CostEntry.cost_date >= local_today.replace(day=1), CostEntry.category == "ai_api")) or 0
    return float(today) + float(manual_today), float(month) + float(manual_month)


def check_budget(estimated_krw: float, what: str) -> None:
    settings = get_settings()
    today, month = spent_krw()
    if today + estimated_krw > settings.cost_cap_daily_krw:
        raise CostCapExceeded(
            f"{what}: 일일 비용 상한 초과 예상 (오늘 {today:,.0f}원 + 예상 {estimated_krw:,.0f}원 > "
            f"상한 {settings.cost_cap_daily_krw:,}원)")
    if month + estimated_krw > settings.cost_cap_monthly_krw:
        raise CostCapExceeded(
            f"{what}: 월 비용 상한 초과 예상 (이번 달 {month:,.0f}원 + 예상 {estimated_krw:,.0f}원 > "
            f"상한 {settings.cost_cap_monthly_krw:,}원)")
