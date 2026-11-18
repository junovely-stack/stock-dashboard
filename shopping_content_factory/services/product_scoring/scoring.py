"""100점 상품 평가 + 필수 필터 + 상위 5개 선정.

원칙
- 근거가 없으면 보수적으로(만점의 30%까지만), mock 근거는 80%까지만.
- 점수는 파이썬 규칙으로만 계산한다(LLM 미사용). 항목별 근거 문자열을 함께 저장한다.
- 필터 결과: pass / hold(사람이 보완하면 재평가) / exclude(제외).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, select

from app.models import (Confidence, Content, ImageRights, Product, ProductScore, SelectionLog, StockStatus,
                        TrendSnapshot)
from config.settings import get_settings, load_policy
from services.analytics.learning import category_profit_multiplier
from services.common.db import session_scope
from services.common.facts import facts_hash
from services.common.logging_utils import get_logger
from services.common.timeutil import hours_since
from services.product_discovery.discovery import candidate_ids

log = get_logger(__name__)
REVIEW_POINTS = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class Criterion:
    score: float
    max: float
    evidence: str
    conservative: bool = False

    def as_dict(self) -> dict:
        return {"score": round(self.score, 2), "max": self.max, "evidence": self.evidence,
                "conservative": self.conservative}


@dataclass
class ScoreResult:
    product_id: str
    total: float
    breakdown: dict[str, dict]
    filter_result: str
    filter_reasons: list[str] = field(default_factory=list)
    penalties: list[dict] = field(default_factory=list)
    expected_revenue: dict = field(default_factory=dict)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _trend_for(product: Product, trends: dict[str, TrendSnapshot]) -> list[TrendSnapshot]:
    return [trends[k] for k in product.keywords or [] if k in trends]


def score_interest(p: Product, ts: list[TrendSnapshot], w: float, rules: dict) -> Criterion:
    if not ts or all(t.latest_ratio is None for t in ts):
        return Criterion(w * rules["conservative_cap"] * 0.5, w, "연결된 트렌드 데이터 없음 → 보수적 부여", True)
    level = max(t.latest_ratio or 0 for t in ts)
    raw = w * _clamp(level / 60.0)
    mock = all(t.confidence == Confidence.MOCK for t in ts)
    if mock:
        raw = min(raw, w * rules["mock_evidence_cap"])
    kw = ", ".join(f"{t.keyword}({t.latest_ratio:.0f})" for t in ts if t.latest_ratio is not None)
    return Criterion(raw, w, f"최근7일 상대지수 {kw}{' [MOCK]' if mock else ''} — 검색량 아님", mock)


def score_momentum(p: Product, ts: list[TrendSnapshot], w: float, rules: dict) -> Criterion:
    growths = [t.growth_7d for t in ts if t.growth_7d is not None]
    if not growths:
        return Criterion(0.0, w, "추이 데이터 없음", True)
    g = max(growths)
    raw = w * _clamp(g / rules["momentum_full_growth"])
    mock = all(t.confidence == Confidence.MOCK for t in ts)
    if mock:
        raw = min(raw, w * rules["mock_evidence_cap"])
    surge = any(t.is_surging for t in ts)
    return Criterion(raw, w, f"직전 3주 대비 최근 1주 {g:+.0%}{' · 급상승' if surge else ''}{' [MOCK]' if mock else ''}",
                     mock)


def score_problem(p: Product, w: float, rules: dict) -> Criterion:
    pr = p.problem or {}
    if not pr.get("real_pain"):
        return Criterion(w * rules["conservative_cap"] * 0.5, w, "고객 문제 리서치 없음 → 보수적", True)
    pts, notes = 0.0, []
    if len(pr.get("real_pain", "")) >= 10:
        pts += 6
        notes.append("구체 불편")
    if pr.get("situation"):
        pts += 4
        notes.append("반복 상황")
    loss = [k for k, v in (pr.get("loss") or {}).items() if v]
    pts += min(3, len(loss)) * 1.5
    if loss:
        notes.append(f"손실 {len(loss)}종({'/'.join(loss)})")
    if pr.get("hesitation") and pr.get("decisive_info"):
        pts += 3.5
        notes.append("망설임-해소정보 짝")
    if pr.get("persona"):
        pts += 2
        notes.append("대상 명확")
    return Criterion(min(pts, w), w, " · ".join(notes) + " (가설 — 실사용자 확인 전)")


def score_intent(p: Product, ts: list[TrendSnapshot], w: float, policy: dict) -> Criterion:
    intent_w = policy["intent"]
    weights = [intent_w.get(t.intent or "problem", 0.7) for t in ts]
    kw_part = 8 * (max(weights) if weights else intent_w["problem"] * 0.5)
    band = 1
    for lo, hi, pts in policy["price_band"]["bands"]:
        if p.base_price is not None and lo <= p.base_price < hi:
            band = pts
    pr = p.problem or {}
    reason_now = 2 if pr.get("reason_now") else 0
    fit = 2 if (p.recommended_for and p.not_recommended_for) else 0
    total = min(w, kw_part + band + reason_now + fit)
    best_intent = max(ts, key=lambda t: intent_w.get(t.intent or "problem", 0)).intent if ts else "없음"
    return Criterion(total, w, f"키워드 의도 {best_intent} · 가격대 {band}점 · 지금 살 이유 {'있음' if reason_now else '없음'}"
                               f" · 추천/비추천 대상 {'명시' if fit else '없음'}", not ts)


def score_credibility(p: Product, w: float, required: list[str], ttl: int) -> Criterion:
    specs = p.verified_specs or []
    spec_pts = 6 * min(5, len(specs)) / 5
    keys = {s.get("key") for s in specs}
    req_pts = 3 * (sum(1 for r in required if r in keys) / len(required)) if required else 3
    review = (p.signals or {}).get("review_signal", "none")
    review_pts = REVIEW_POINTS.get(review, 0)
    seller_pts = 1 if p.seller else 0
    age = hours_since(p.price_checked_at)
    price_pts = 2 if age is not None and age <= ttl else 0
    total = spec_pts + req_pts + review_pts + seller_pts + price_pts
    mock = p.is_demo
    return Criterion(min(total, w), w, f"검증 사양 {len(specs)}개 · 필수 사양 {req_pts / 3:.0%} · 리뷰 신호 {review}"
                                        f"{' [DEMO]' if mock else ''} · 가격 확인 {'유효' if price_pts else '만료'}", mock)


def score_visual(p: Product, w: float, rules: dict) -> Criterion:
    v = (p.signals or {}).get("visual_fit")
    if v is None:
        return Criterion(w * rules["conservative_cap"], w, "시각화 적합성 미평가 → 보수적", True)
    return Criterion(w * _clamp(float(v) / 5), w, f"시각화 태그 {v}/5 (사용 전후가 눈에 보이는 정도)")


def expected_revenue(p: Product, multiplier: float | None) -> dict:
    fin = load_policy("finance")
    a, base = fin["assumptions"], fin["scenarios"]["base"]
    rate = p.commission_rate if p.commission_rate is not None else a["effective_commission_rate"]
    views = base["views_start"]
    orders = views * base["landing_rate"] * base["link_ctr"] * base["purchase_cvr"]
    rev = orders * (p.base_price or 0) * rate
    return {"basis": "가정(기준 시나리오 1개월차)" if multiplier is None else "가정 × 카테고리 실측 보정",
            "views": views, "orders": round(orders, 3), "commission_per_order_krw": round((p.base_price or 0) * rate),
            "revenue_krw": round(rev * (multiplier or 1.0)), "rate": rate,
            "rate_verified": bool(p.commission_rate_verified)}


def score_profit(p: Product, w: float, rules: dict, exp: dict, multiplier: float | None) -> Criterion:
    cpo = exp["commission_per_order_krw"]
    raw = w * _clamp(cpo / rules["target_commission_krw"])
    if multiplier is not None:
        raw = w * _clamp(raw / w * multiplier)
    note = f"주문 1건 수수료 약 {cpo:,}원(가격×{exp['rate']:.0%}{'' if exp['rate_verified'] else ' 가정'})"
    if multiplier is not None:
        note += f" · 카테고리 실측 보정 ×{multiplier:.2f}"
    return Criterion(raw, w, note, not exp["rate_verified"])


def score_differentiation(p: Product, w: float, recent_categories: set[str]) -> Criterion:
    if p.category_key in recent_categories:
        return Criterion(w * 0.6, w, "최근 3일 내 같은 카테고리 콘텐츠 있음")
    return Criterion(w, w, "최근 같은 카테고리 콘텐츠 없음")


def hard_filters(p: Product, settings, policy: dict, comp: dict, required: list[str],
                 featured_days: int | None, prior_hash: str | None) -> tuple[str, list[str]]:
    excludes, holds = [], []
    sig = p.signals or {}
    if p.stock_status in (StockStatus.OUT_OF_STOCK, StockStatus.DISCONTINUED):
        excludes.append(f"재고: {p.stock_status}")
    if sig.get("claims_unverifiable"):
        excludes.append("검증되지 않은 효과를 주장해야 팔리는 상품")
    if sig.get("safety_risk"):
        excludes.append("안전 위험이 큰 상품(낙하·화재 등)")
    text = " ".join([p.name or "", p.description or "", " ".join(p.keywords or [])])
    risky = [k for k in comp["excluded"]["risk_keywords"] if k in text]
    if risky or p.category_key in comp["excluded"]["categories"]:
        excludes.append(f"규제·위험 영역 ({', '.join(risky) or p.category_key})")
    rules = policy["rules"]
    if featured_days is not None and featured_days <= rules["duplicate_product_days"]:
        excludes.append(f"최근 {featured_days}일 전 같은 상품 콘텐츠 — {rules['duplicate_product_days']}일 내 재선정 금지")
    elif prior_hash is not None and prior_hash == facts_hash(p):
        excludes.append("이전 콘텐츠 대비 새로운 정보 없음")
    if p.image_rights_status not in ImageRights.VIDEO_OK:
        holds.append(f"이미지 사용권 미확인 ({p.image_rights_status}) — 권리 확인 후 재평가")
    specs = p.verified_specs or []
    if len(specs) < rules["min_verified_specs"]:
        holds.append(f"검증 사양 {len(specs)}개 < {rules['min_verified_specs']}개")
    keys = {s.get("key") for s in specs}
    missing = [r for r in required if r not in keys]
    if missing:
        holds.append(f"필수 사양 누락: {', '.join(missing)}")
    age = hours_since(p.price_checked_at)
    if p.base_price is None or age is None:
        holds.append("가격 미확인")
    elif age > settings.price_ttl_hours:
        holds.append(f"가격 확인 {age:.0f}시간 경과 (유효 {settings.price_ttl_hours}시간)")
    if not p.seller:
        holds.append("판매자 정보 없음")
    if excludes:
        return "exclude", excludes + holds
    if holds:
        return "hold", holds
    return "pass", []


def penalties_for(p: Product, policy: dict, exp: dict) -> list[dict]:
    out, rules, pen = [], policy["rules"], policy["penalties"]
    change = abs((p.signals or {}).get("price_7d_change_pct", 0) or 0)
    if change > rules["price_volatility_pct"]:
        out.append({"reason": f"7일 내 가격 변동 {change}%", "points": pen["price_volatility"]})
    if p.stock_status == StockStatus.LOW_STOCK:
        out.append({"reason": "재고 부족 — 품절 가능성", "points": pen["low_stock"]})
    if exp["commission_per_order_krw"] < rules["low_profit_commission_krw"]:
        out.append({"reason": f"주문 1건 수수료 {exp['commission_per_order_krw']}원 — 제작비 회수 어려움",
                    "points": pen["low_profit"]})
    return out


def score_product(p: Product, trends: dict[str, TrendSnapshot], settings, recent_categories: set[str],
                  featured_days: int | None, prior_hash: str | None) -> ScoreResult:
    policy, comp, cats = load_policy("scoring"), load_policy("compliance"), load_policy("categories")
    w, rules = policy["weights"], policy["rules"]
    required = cats.get(p.category_key, {}).get("required_specs", [])
    ts = _trend_for(p, trends)
    mult = category_profit_multiplier(p.category_key)
    exp = expected_revenue(p, mult)
    crit = {
        "interest": score_interest(p, ts, w["interest"], rules),
        "momentum": score_momentum(p, ts, w["momentum"], rules),
        "problem_strength": score_problem(p, w["problem_strength"], rules),
        "purchase_intent": score_intent(p, ts, w["purchase_intent"], policy),
        "credibility": score_credibility(p, w["credibility"], required, settings.price_ttl_hours),
        "visual_fit": score_visual(p, w["visual_fit"], rules),
        "expected_profit": score_profit(p, w["expected_profit"], rules, exp, mult),
        "differentiation": score_differentiation(p, w["differentiation"], recent_categories),
    }
    pens = penalties_for(p, policy, exp)
    subtotal = sum(c.score for c in crit.values())
    total = max(0.0, round(subtotal - sum(x["points"] for x in pens), 2))
    result, reasons = hard_filters(p, settings, policy, comp, required, featured_days, prior_hash)
    return ScoreResult(p.id, total, {k: v.as_dict() for k, v in crit.items()}, result, reasons, pens, exp)


def _history(session, run_date: date) -> tuple[set[str], dict[str, int], dict[str, str]]:
    rules = load_policy("scoring")["rules"]
    recent_cats: set[str] = set()
    featured: dict[str, int] = {}
    prior_hash: dict[str, str] = {}
    since = run_date - timedelta(days=365)
    for c in session.scalars(select(Content).where(Content.run_date < run_date, Content.run_date >= since)):
        days = (run_date - c.run_date).days
        if days <= rules["same_category_recent_days"]:
            recent_cats.add(c.product.category_key)
        featured[c.product_id] = min(days, featured.get(c.product_id, 10 ** 6))
        prior_hash[c.product_id] = c.facts_hash
    return recent_cats, featured, prior_hash


def score_candidates(run_date: date) -> dict:
    settings = get_settings()
    ids = candidate_ids(run_date)
    with session_scope() as s:
        trends = {t.keyword: t for t in s.scalars(select(TrendSnapshot).where(
            TrendSnapshot.run_date == run_date, TrendSnapshot.excluded_reason.is_(None)))}
        recent_cats, featured, prior_hash = _history(s, run_date)
        s.execute(delete(ProductScore).where(ProductScore.run_date == run_date))
        results = []
        for pid in ids:
            p = s.get(Product, pid)
            if p is None:
                continue
            days = featured.get(pid)
            demo_days = (p.signals or {}).get("recently_featured_days")
            if demo_days is not None:
                days = min(days, demo_days) if days is not None else demo_days
            r = score_product(p, trends, settings, recent_cats, days, prior_hash.get(pid))
            results.append(r)
        passing = sorted([r for r in results if r.filter_result == "pass"],
                         key=lambda r: (-r.total, -r.breakdown["problem_strength"]["score"],
                                        -r.breakdown["purchase_intent"]["score"]))
        rank = {r.product_id: i + 1 for i, r in enumerate(passing)}
        for r in results:
            sel = "top5" if rank.get(r.product_id, 99) <= 5 else None
            reason = None
            if sel:
                top = sorted(r.breakdown.items(), key=lambda kv: -kv[1]["score"] / kv[1]["max"])[:2]
                reason = f"{rank[r.product_id]}위 {r.total:.1f}점 — 강점: " + ", ".join(
                    f"{k}({v['score']:.1f}/{v['max']:.0f})" for k, v in top)
            s.add(ProductScore(run_date=run_date, product_id=r.product_id, total=r.total, breakdown=r.breakdown,
                               filter_result=r.filter_result, filter_reasons=r.filter_reasons, penalties=r.penalties,
                               rank=rank.get(r.product_id), selection=sel, selection_reason=reason,
                               expected_revenue=r.expected_revenue))
            p = s.get(Product, r.product_id)
            p.total_score = r.total
            p.expected_revenue = r.expected_revenue
            p.selection_reason = reason or "; ".join(r.filter_reasons) or None
        counts = {k: sum(1 for r in results if r.filter_result == k) for k in ("pass", "hold", "exclude")}
        s.add(SelectionLog(run_date=run_date, step="score",
                           message=f"평가 {len(results)}개 — 통과 {counts['pass']} · 보류 {counts['hold']} · 제외 {counts['exclude']}",
                           data={"counts": counts, "top5": [r.product_id for r in passing[:5]],
                                 "totals": {r.product_id: r.total for r in results}}))
    return {"scored": len(results), **counts, "top5": [r.product_id for r in passing[:5]]}
