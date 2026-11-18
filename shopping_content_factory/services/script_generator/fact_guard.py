"""사실 확인·표시광고 규칙 검사. 하나라도 error 가 있으면 콘텐츠는 BLOCKED.

검사 항목
1. 숫자+단위 주장 → 검증 사양과 일치해야 함 (예: 사양 5kg 인데 자막 10kg → 차단)
2. 금액·할인율 표기 금지 (가격은 변동 → 랜딩에서 확인 시각과 함께만)
3. 금칙어 (절대·최상급·거짓 희소성·재촉·의학적 효능·가짜 사회적 증거·근거 없는 비교·경험 주장)
4. 광고 표시: 첫 장면 문구, 캡션 첫 줄, 첫 해시태그 #광고, 유튜브 제목 접두어, 조건부 표현 금지
5. 주의사항 최소 1개 화면 노출
6. fact_refs 가 실제 사양 key 인지
"""
from __future__ import annotations

from app.models import Product
from config.settings import load_policy
from services.affiliate_links.links import check_disclosure_text
from services.common.facts import allowed_number_units, extract_number_units


def _texts(script: dict) -> list[tuple[str, str]]:
    out = [("title", script.get("title", ""))]
    for v, hv in (script.get("variants") or {}).items():
        out.append((f"hook_{v}", hv.get("hook", "")))
    for sc in script.get("scenes", []):
        out.append((f"{sc['id']}.on_screen", sc.get("on_screen_text", "")))
        out.append((f"{sc['id']}.narration", sc.get("narration", "")))
    cap = script.get("caption") or {}
    for k in ("instagram", "youtube_title", "youtube_description"):
        if cap.get(k):
            out.append((f"caption.{k}", cap[k]))
    return out


def _strip_disclosures(text: str, disclosure: dict) -> str:
    for key in ("coupang_required", "caption_first_line", "video_opening", "landing_notice", "ai_notice"):
        if disclosure.get(key):
            text = text.replace(disclosure[key], " ")
    return text


def check_script(script: dict, p: Product) -> dict:
    comp = load_policy("compliance")
    disclosure = comp["disclosure"]
    issues: list[dict] = []

    def err(where: str, rule: str, msg: str):
        issues.append({"severity": "error", "where": where, "rule": rule, "message": msg})

    allowed = allowed_number_units(p)
    forbid_units = set(comp["claim_units"]["forbid_in_video"])
    own_usage = bool((p.signals or {}).get("own_usage_verified"))
    for where, raw in _texts(script):
        text = _strip_disclosures(raw, disclosure)
        for n, unit in extract_number_units(text):
            if unit in forbid_units:
                err(where, "no_price_in_video", f"'{n}{unit}' — 영상·캡션에 금액·할인율 표기 금지")
            elif (n, unit) not in allowed:
                err(where, "spec_mismatch", f"'{n}{unit}' 가 검증 사양에 없음")
        for cat, words in comp["banned_phrases"].items():
            if cat == "experience_claims" and own_usage:
                continue
            for w in words:
                if w in text:
                    err(where, f"banned.{cat}", f"금칙어 '{w}'")

    scenes = script.get("scenes", [])
    disc = script.get("disclosure") or {}
    if not disc.get("opening") or not scenes or not scenes[0].get("show_disclosure"):
        err("s1", "disclosure_opening", "첫 장면 광고 표시 누락")
    if not disc.get("endcard"):
        err("cta", "disclosure_end", "마지막 장면 광고 표시 누락")
    for k in ("opening", "endcard", "caption_first_line"):
        for msg in check_disclosure_text(disc.get(k, "")):
            err(f"disclosure.{k}", "disclosure_wording", msg)
    cap = script.get("caption") or {}
    ig = cap.get("instagram", "")
    if not ig.startswith(disclosure["caption_first_line"]):
        err("caption.instagram", "disclosure_caption", "캡션 첫 줄이 광고 표시가 아님 ('더보기' 뒤에 숨으면 안 됨)")
    tags = script.get("hashtags") or []
    if tags and tags[0] != disclosure["first_hashtag"]:
        err("hashtags", "disclosure_hashtag", f"첫 해시태그가 {disclosure['first_hashtag']} 이 아님")
    if not cap.get("youtube_title", "").startswith(disclosure["youtube_title_prefix"]):
        err("caption.youtube_title", "disclosure_title", "유튜브 제목 앞 광고 표시 누락")

    cautions = list(p.cautions or [])
    if cautions:
        pc = [sc for sc in scenes if sc.get("role") == "pros_cautions"]
        shown = " ".join(sc.get("on_screen_text", "") + " " + sc.get("narration", "") for sc in pc)
        markers = ("확인할 점", "주의", "다만", "확인하세요")
        if not pc or not (any(c[:8] in shown for c in cautions) or any(m in shown for m in markers)):
            err("pros_cautions", "caution_missing", "장점·주의 장면에 주의사항(설치 조건·하중·호환)이 없음")
    keys = {s.get("key") for s in p.verified_specs or []}
    for sc in scenes:
        unknown = [r for r in sc.get("fact_refs", []) if r not in keys]
        if unknown:
            err(sc["id"], "fact_ref_unknown", f"존재하지 않는 사양 참조: {unknown}")
    dur = sum(sc.get("duration", 0) for sc in scenes)
    if not 15 <= dur <= 30:
        err("scenes", "duration", f"총 길이 {dur}초 — 15~30초 범위 밖")
    return {"passed": not any(i["severity"] == "error" for i in issues), "issues": issues}
