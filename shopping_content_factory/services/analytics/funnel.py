"""콘텐츠별 퍼널 — 실측과 추정을 분리.

조회(플랫폼 API/CSV) → 랜딩 방문(자체 로그) → 링크 클릭(자체 로그) → 구매·수수료(쿠팡 리포트)
- 구매·수수료는 sub_id 로 콘텐츠에 연결될 때만 '실측 귀속'. 연결 안 되면 '미귀속'으로 따로 둔다.
- 추정 구매는 클릭 × 가정 전환율(보수~낙관 범위)로만 표시하고 실측 칸에 넣지 않는다.
- 조회수는 매출이 아니다. RPM 은 실측 귀속 수수료가 있을 때만 계산.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select

from app.models import AffiliateReport, ApiUsage, Content, CostEntry, MetricObservation, Publication, SiteEvent
from config.settings import load_policy
from services.analytics.learning import attributed_commission_by_content


def _site_counts(s) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"page_view": 0, "link_click": 0, "video_play": 0})
    rows = s.execute(select(SiteEvent.content_id, SiteEvent.event_type, func.count()).group_by(
        SiteEvent.content_id, SiteEvent.event_type))
    for cid, et, n in rows:
        if cid:
            out[cid][et] = n
    return out


def _platform_metrics(s) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for m in s.scalars(select(MetricObservation).where(MetricObservation.is_estimate.is_(False))):
        if m.content_id:
            out[m.content_id][m.metric] += m.value
    return out


def content_funnels() -> list[dict]:
    from services.common.db import session_scope

    fin = load_policy("finance")["scenarios"]
    cvr_lo, cvr_hi = fin["conservative"]["purchase_cvr"], fin["optimistic"]["purchase_cvr"]
    with session_scope() as s:
        site = _site_counts(s)
        plat = _platform_metrics(s)
        comm = attributed_commission_by_content(s)
        manual_cost = defaultdict(float)
        for ce in s.scalars(select(CostEntry)):
            if ce.content_id:
                manual_cost[ce.content_id] += ce.amount_krw
        rows = []
        for c in s.scalars(select(Content).order_by(Content.run_date.desc())):
            pubs = list(s.scalars(select(Publication).where(Publication.content_id == c.id)))
            views = plat[c.id].get("views")
            visits = site[c.id]["page_view"]
            clicks = site[c.id]["link_click"]
            measured_comm = comm.get(c.id)
            cost = (c.cost_estimate_krw or 0) + manual_cost[c.id]
            rows.append({
                "content_id": c.id, "product": c.product.name, "category": c.product.category_key,
                "status": c.status, "is_demo": c.is_demo, "run_date": c.run_date.isoformat(),
                "hook_type": c.script["variants"][c.primary_variant]["hook_type"],
                "publications": {p.platform: p.status for p in pubs},
                "measured": {"views": views, "likes": plat[c.id].get("likes"), "saved": plat[c.id].get("saved"),
                             "shares": plat[c.id].get("shares"), "landing_visits": visits, "link_clicks": clicks,
                             "commission_krw": measured_comm},
                "rates": {"landing_rate": (visits / views) if views else None,
                          "link_ctr": (clicks / visits) if visits else None},
                "estimated": {"orders_low": clicks * cvr_lo, "orders_high": clicks * cvr_hi,
                              "basis": f"링크 클릭 {clicks} × 가정 전환율 {cvr_lo:.0%}~{cvr_hi:.0%}"},
                "cost_krw": cost,
                "rpm_measured": (measured_comm / views * 1000) if (measured_comm is not None and views) else None,
                "profit_measured": (measured_comm - cost) if measured_comm is not None else None,
            })
        return rows


def unattributed_affiliate() -> dict:
    from services.common.db import session_scope

    with session_scope() as s:
        mapped = set()
        from app.models import AffiliateLink

        for l in s.scalars(select(AffiliateLink)):
            if l.sub_id and l.content_id:
                mapped.add(l.sub_id)
        total = {"orders": 0, "gmv_krw": 0, "commission_krw": 0, "cancel_amount_krw": 0}
        for r in s.scalars(select(AffiliateReport)):
            if r.sub_id in mapped:
                continue
            total["orders"] += r.orders
            total["gmv_krw"] += r.gmv_krw
            total["commission_krw"] += r.commission_krw
            total["cancel_amount_krw"] += r.cancel_amount_krw
        return total


def cost_summary() -> dict:
    from services.common.db import session_scope

    with session_scope() as s:
        api = s.scalar(select(func.coalesce(func.sum(ApiUsage.cost_krw), 0.0))) or 0.0
        errors = s.scalar(select(func.count()).select_from(ApiUsage).where(ApiUsage.success.is_(False))) or 0
        calls = s.scalar(select(func.count()).select_from(ApiUsage)) or 0
        manual = defaultdict(int)
        for ce in s.scalars(select(CostEntry)):
            manual[ce.category] += ce.amount_krw
        return {"api_cost_krw": api, "api_calls": calls, "api_errors": errors, "manual_costs": dict(manual)}
