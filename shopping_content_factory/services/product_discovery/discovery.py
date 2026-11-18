"""후보 상품 발굴 → DB 반영.

- 키워드와 연결된 실제 제휴 가능 상품만 후보가 된다.
- 같은 상품(ID·정규화 이름) 중복 제거.
- 관리자가 손으로 고친 상품(signals.admin_edited)은 가격·재고만 갱신하고 사실 정보는 덮어쓰지 않는다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select

from adapters.base import ProductCandidate, set_source_state
from adapters.coupang.catalog import CoupangSearchCatalog, ManualCatalogAdapter, MockCatalogAdapter
from adapters.coupang.partners import CoupangPartnersAdapter
from app.models import (AffiliateLink, ImageRights, LinkStatus, PriceHistory, Product, ProductImage, SourceState,
                        SelectionLog)
from config.settings import get_settings
from services.affiliate_links.links import validate_affiliate_url
from services.common.db import session_scope
from services.common.facts import facts_hash
from services.common.logging_utils import get_logger
from services.common.timeutil import now_utc
from services.trend_collector.collector import active_keywords

log = get_logger(__name__)
RIGHTS_RANK = [ImageRights.OWN, ImageRights.LICENSED, ImageRights.AI_GENERATED, ImageRights.PARTNER_DISPLAY,
               ImageRights.REFERENCE_ONLY, ImageRights.UNKNOWN, ImageRights.DENIED]


def slugify(text: str, fallback: str) -> str:
    """프로필 링크·캡션에 쓰기 좋은 짧은 ASCII 슬러그 (상품 ID 기반)."""
    return re.sub(r"[^0-9a-z]+", "-", fallback.lower()).strip("-")


def _norm_name(name: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", name.lower())


def _catalog():
    settings = get_settings()
    provider = settings.product_provider
    if provider == "coupang":
        adapter = CoupangPartnersAdapter(settings)
        if adapter.is_configured():
            kw_cat = {t.keyword: t.category_key or "unknown" for t in active_keywords_today_cache}
            return CoupangSearchCatalog(adapter, kw_cat), SourceState.CONNECTED
        set_source_state("coupang_partners", "product", SourceState.NOT_CONFIGURED,
                         note="API 키 없음 — 최종 승인 후 발급. 수동 상품 입력(data/manual/products.json) 사용")
        return ManualCatalogAdapter(settings.data_dir / "manual" / "products.json"), SourceState.MANUAL
    if provider == "manual":
        return ManualCatalogAdapter(settings.data_dir / "manual" / "products.json"), SourceState.MANUAL
    return MockCatalogAdapter(settings.data_dir / "mock" / "products_demo.json"), SourceState.MOCK


active_keywords_today_cache: list = []


def _apply(p: Product, c: ProductCandidate, now) -> None:
    d = c.data
    hours_ago = d.get("price_checked_hours_ago")
    checked = now - timedelta(hours=hours_ago) if hours_ago is not None else now
    edited = bool((p.signals or {}).get("admin_edited"))
    p.base_price = c.price
    p.price_checked_at = checked if c.price is not None else None
    p.stock_status = d.get("stock_status", "unknown")
    p.stock_checked_at = checked
    if edited:
        return
    p.name = c.name
    p.category_key = c.category_key
    p.external_id = d.get("external_id")
    p.seller = d.get("seller")
    p.brand = d.get("brand")
    p.mall = d.get("mall", "coupang" if c.source_type == "coupang_api" else "DEMO" if c.is_demo else None)
    p.description = d.get("description")
    p.verified_specs = [dict(s, source=s.get("source", c.source_type), verified_at=checked.isoformat())
                        for s in d.get("verified_specs", [])]
    for f in ("pros", "cons", "recommended_for", "not_recommended_for", "cautions", "usage_steps"):
        setattr(p, f, list(d.get(f, [])))
    p.problem = dict(d.get("problem", {}))
    p.signals = dict(d.get("signals", {}))
    p.keywords = list(c.keywords)
    p.source_type = c.source_type
    p.source_url = c.source_url
    p.commission_rate = d.get("commission_rate")
    p.commission_rate_verified = bool(d.get("commission_rate_verified", False))
    p.is_demo = c.is_demo


def discover_products(run_date: date) -> dict:
    global active_keywords_today_cache
    settings = get_settings()
    snapshots = active_keywords(run_date)
    active_keywords_today_cache = snapshots
    keywords = [t.keyword for t in snapshots]
    catalog, state = _catalog()
    candidates = catalog.candidates(keywords)
    set_source_state(catalog.name, "product", state,
                     note="DEMO 상품(실재하지 않음)" if state == SourceState.MOCK else f"{len(candidates)}개")
    kw_set = set(keywords)
    seen_ids, seen_names, unique = set(), set(), []
    dup = unmatched = 0
    for c in candidates:
        n = _norm_name(c.name)
        if c.id in seen_ids or n in seen_names:
            dup += 1
            continue
        if not (set(c.keywords) & kw_set):
            unmatched += 1  # 오늘 트렌드와 연결 안 된 후보도 평가는 하되 관심도 근거 없음으로 처리
        seen_ids.add(c.id)
        seen_names.add(n)
        unique.append(c)

    now = now_utc()
    with session_scope() as s:
        for c in unique:
            p = s.get(Product, c.id)
            if p is None:
                p = Product(id=c.id, slug=slugify(c.name, c.id), name=c.name, category_key=c.category_key)
                s.add(p)
            _apply(p, c, now)
            s.flush()
            if c.price is not None:
                s.add(PriceHistory(product_id=p.id, price=c.price, checked_at=p.price_checked_at or now,
                                   source=c.source_type))
            img = c.data.get("image")
            if img and not any(i.role == "original" for i in p.images):
                p.images.append(ProductImage(role="original", source=img.get("source", "unknown"),
                                             url=img.get("url"), path=img.get("path"),
                                             rights_status=img.get("rights", ImageRights.UNKNOWN),
                                             rights_evidence=img.get("evidence") or (
                                                 "DEMO 일러스트 — 코드로 직접 그림" if img.get("source") ==
                                                 "demo_illustration" else None)))
            ranks = [RIGHTS_RANK.index(i.rights_status) if i.rights_status in RIGHTS_RANK else 99 for i in p.images]
            p.image_rights_status = RIGHTS_RANK[min(ranks)] if ranks and min(ranks) < 99 else ImageRights.UNKNOWN
            aff_url = c.data.get("affiliate_url")
            if aff_url and not p.links:
                ok, why = validate_affiliate_url(aff_url)
                p.links.append(AffiliateLink(program="coupang_partners", url=aff_url, source="api",
                                             status=LinkStatus.VERIFIED if ok else LinkStatus.INVALID, note=why,
                                             verified_at=now if ok else None, verified_by="coupang_api" if ok else None))
            if p.links:
                p.affiliate_link_status = max((l.status for l in p.links),
                                              key=lambda st: [LinkStatus.INVALID, LinkStatus.MISSING,
                                                              LinkStatus.REGISTERED, LinkStatus.VERIFIED].index(st))
            s.flush()
            p.facts_hash = facts_hash(p)
        s.add(SelectionLog(run_date=run_date, step="discover",
                           message=f"후보 {len(unique)}개 확보 (중복 {dup}개 제거, 트렌드 미연결 {unmatched}개)",
                           data={"provider": catalog.name, "ids": [c.id for c in unique]}))
    summary = {"candidates": len(unique), "duplicates_removed": dup, "unmatched_trend": unmatched,
               "provider": catalog.name, "insufficient": len(unique) < settings.min_candidates}
    if summary["insufficient"]:
        log.warning("후보가 최소 기준(%d) 미만: %d", settings.min_candidates, len(unique))
    return summary


def candidate_ids(run_date: date) -> list[str]:
    with session_scope() as s:
        row = s.scalars(select(SelectionLog).where(SelectionLog.run_date == run_date, SelectionLog.step == "discover")
                        .order_by(SelectionLog.id.desc())).first()
        return list((row.data or {}).get("ids", [])) if row else []
