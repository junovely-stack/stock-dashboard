"""공개 쇼핑 큐레이션 페이지.

- 승인(또는 게시)된 콘텐츠가 있는 상품만 노출. 승인 전 상품은 404.
- 쿠팡으로 자동 이동하지 않는다. 버튼은 일반 링크(rel="sponsored nofollow noopener"), 방문자가 직접 누른다.
- 이벤트 로그에는 IP·브라우저 정보·쿠키를 저장하지 않는다.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory
from sqlalchemy import func, select

from app.models import Content, ContentStatus, ImageRights, Product, SiteEvent
from config.settings import get_settings, load_policy
from services.affiliate_links.links import best_link
from services.common.db import session_scope
from services.common.timeutil import hours_since

bp = Blueprint("public", __name__)
LIVE = (ContentStatus.APPROVED, ContentStatus.PUBLISHED)
PUBLIC_FILES = {"landing_card.png", "product_hero.png", "thumbnail.png", "reel_final.mp4", "shorts_final.mp4"}
EVENT_TYPES = {"page_view", "link_click", "video_play"}
_rate: dict[str, deque] = defaultdict(deque)  # 메모리만, 저장 안 함


def _live_contents(s, product_id: str | None = None):
    q = select(Content).where(Content.status.in_(LIVE))
    if product_id:
        q = q.where(Content.product_id == product_id)
    return list(s.scalars(q.order_by(Content.approved_at.desc())))


def _card(c: Content) -> dict:
    p = c.product
    return {"content_id": c.id, "slug": p.slug, "name": p.name, "category": p.category_key,
            "hook": c.script["variants"][c.primary_variant]["hook"], "is_demo": p.is_demo,
            "image": f"/media/{c.id}/landing_card.png" if (c.assets or {}).get("images", {}).get("landing") else None}


@bp.get("/")
def index():
    cats = load_policy("categories")
    with session_scope() as s:
        live = _live_contents(s)
        views = dict(s.execute(select(SiteEvent.content_id, func.count()).where(SiteEvent.event_type == "page_view")
                               .group_by(SiteEvent.content_id)).all())
        cards = [_card(c) for c in live]
        seen, unique = set(), []
        for c in cards:
            if c["slug"] not in seen:
                seen.add(c["slug"])
                unique.append(c)
        popular = sorted(unique, key=lambda c: -views.get(c["content_id"], 0))[:6] if views else []
        cat_counts = defaultdict(int)
        for c in unique:
            cat_counts[c["category"]] += 1
        any_demo = any(c["is_demo"] for c in unique)
    return render_template("public/index.html", today=unique[0] if unique else None, latest=unique[:9],
                           popular=popular, cats=cats, cat_counts=cat_counts, any_demo=any_demo)


@bp.get("/category/<key>")
def category(key: str):
    cats = load_policy("categories")
    if key not in cats:
        abort(404)
    with session_scope() as s:
        cards = [_card(c) for c in _live_contents(s) if c.product.category_key == key]
    return render_template("public/category.html", key=key, label=cats[key]["label"], cards=cards,
                           any_demo=any(c["is_demo"] for c in cards))


@bp.get("/p/<slug>")
def product(slug: str):
    settings = get_settings()
    with session_scope() as s:
        p = s.scalars(select(Product).where(Product.slug == slug)).first()
        if p is None:
            abort(404)
        contents = _live_contents(s, p.id)
        if not contents:
            abort(404)
        req_cid = request.args.get("c")
        c = next((x for x in contents if x.id == req_cid), contents[0])
        link = best_link(p)
        age = hours_since(p.price_checked_at)
        img_ok = p.image_rights_status in ImageRights.LANDING_OK
        files = (c.assets or {}).get("videos", {})
        ctx = {
            "p": p, "c": c, "link": link, "price_fresh": age is not None and age <= settings.price_ttl_hours,
            "price_age": age, "image": f"/media/{c.id}/landing_card.png" if img_ok else None,
            "video": f"/media/{c.id}/reel_final.mp4" if files.get("reel_final") and img_ok else None,
            "poster": f"/media/{c.id}/thumbnail.png" if img_ok else None,
            "src": (request.args.get("src") or "direct")[:16], "any_demo": p.is_demo,
            "problem": p.problem or {}, "cat_label": load_policy("categories").get(p.category_key, {}).get("label"),
            "sold_out": p.stock_status in ("out_of_stock", "discontinued"),
        }
        return render_template("public/product.html", **ctx)


@bp.get("/media/<content_id>/<filename>")
def media(content_id: str, filename: str):
    if filename not in PUBLIC_FILES:
        abort(404)
    with session_scope() as s:
        c = s.get(Content, content_id)
        if c is None or c.status not in LIVE or c.product.image_rights_status not in ImageRights.LANDING_OK:
            abort(404)
        directory = Path(c.output_dir or "")
    if not (directory / filename).exists():
        abort(404)
    return send_from_directory(directory, filename, max_age=3600)


@bp.get("/disclosure")
def disclosure_page():
    return render_template("public/disclosure.html")


@bp.get("/privacy")
def privacy():
    return render_template("public/privacy.html")


@bp.post("/api/event")
def event():
    key = request.remote_addr or "-"
    q = _rate[key]
    now = time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= 60:
        return jsonify({"ok": False}), 429
    q.append(now)
    data = request.get_json(silent=True, force=True) or {}
    et = data.get("type")
    if et not in EVENT_TYPES:
        return jsonify({"ok": False}), 400
    ref = request.headers.get("Referer") or data.get("ref") or ""
    ref_domain = (urlparse(ref).hostname or "")[:128] if ref else None
    with session_scope() as s:
        pid = str(data.get("product_id") or "")[:64] or None
        cid = str(data.get("content_id") or "")[:64] or None
        if pid and s.get(Product, pid) is None:
            return jsonify({"ok": False}), 400
        if cid and s.get(Content, cid) is None:
            cid = None
        link_id = data.get("link_id")
        s.add(SiteEvent(event_type=et, product_id=pid, content_id=cid, src=str(data.get("src") or "direct")[:32],
                        link_id=int(link_id) if str(link_id or "").isdigit() else None, ref_domain=ref_domain))
    return ("", 204)
