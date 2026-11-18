"""성과 → 다음 선정 반영.

표본이 충분할 때만 반영한다. 기준: 카테고리별 실측 콘텐츠 5개 이상 + 누적 조회 5,000 이상.
그 전에는 None(가정값 사용)을 돌려주고, 점수 근거에도 '가정'으로 남는다.
조회수가 아니라 '조회 1,000회당 실측 제휴수익(RPM)'으로 비교한다.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

MIN_CONTENTS = 5
MIN_VIEWS = 5000


def attributed_commission_by_content(session) -> dict[str, float]:
    from app.models import AffiliateLink, AffiliateReport

    sub_to_content = {l.sub_id: l.content_id for l in session.scalars(select(AffiliateLink)) if l.sub_id and l.content_id}
    out: dict[str, float] = defaultdict(float)
    for r in session.scalars(select(AffiliateReport)):
        cid = sub_to_content.get(r.sub_id)
        if cid:
            out[cid] += r.commission_krw  # 리포트 수수료(취소분은 cancels 리포트로 별도 차감)
    return dict(out)


def views_by_content(session) -> dict[str, float]:
    from app.models import MetricObservation

    out: dict[str, float] = defaultdict(float)
    for m in session.scalars(select(MetricObservation).where(MetricObservation.metric == "views",
                                                             MetricObservation.is_estimate.is_(False))):
        if m.content_id:
            out[m.content_id] += m.value
    return dict(out)


def category_stats() -> dict[str, dict]:
    from app.models import Content
    from services.common.db import session_scope

    with session_scope() as s:
        views = views_by_content(s)
        comm = attributed_commission_by_content(s)
        stats: dict[str, dict] = defaultdict(lambda: {"contents": 0, "views": 0.0, "commission": 0.0})
        for c in s.scalars(select(Content).where(Content.is_demo.is_(False))):
            if c.id not in views:
                continue
            st = stats[c.product.category_key]
            st["contents"] += 1
            st["views"] += views[c.id]
            st["commission"] += comm.get(c.id, 0.0)
    for st in stats.values():
        st["rpm"] = st["commission"] / st["views"] * 1000 if st["views"] else 0.0
        st["sufficient"] = st["contents"] >= MIN_CONTENTS and st["views"] >= MIN_VIEWS
    return dict(stats)


def category_profit_multiplier(category_key: str) -> float | None:
    try:
        stats = category_stats()
    except Exception:  # noqa: BLE001 — 성과 데이터가 없거나 DB 초기화 전
        return None
    ok = {k: v for k, v in stats.items() if v["sufficient"]}
    if category_key not in ok or len(ok) < 2:
        return None
    total_views = sum(v["views"] for v in ok.values())
    overall = sum(v["commission"] for v in ok.values()) / total_views * 1000 if total_views else 0
    if overall <= 0:
        return None
    return max(0.7, min(1.3, ok[category_key]["rpm"] / overall))
