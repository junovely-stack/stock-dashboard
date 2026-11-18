"""대본 생성 → script.json.

- 장면 구조 5개 고정(hook 3초 · why 5초 · how 8초 · pros_cautions 7초 · cta 5초 = 28초)
- A형(문제 공감) / B형(사용 결과 설명): 첫 장면 자막·내레이션만 다르고 나머지는 동일 (A/B 조건 통제)
- 광고 표시는 LLM 이 아니라 정책 파일 문구를 시스템이 삽입
- 생성 후 fact_guard 통과 못 하면 BLOCKED
"""
from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import func, select

from adapters.llm.anthropic_client import AnthropicJSONClient
from app.models import Content, ContentStatus, Product, PsychologyProfile
from config.settings import get_settings, load_policy
from services.common.db import session_scope
from services.common.facts import facts_hash, product_facts
from services.psychology_engine.prompts import SCRIPT_SCHEMA, SCRIPT_SYSTEM, SCRIPT_USER_TEMPLATE
from services.script_generator.fact_guard import check_script

DURATIONS = {"hook": 3.0, "why": 5.0, "how": 8.0, "pros_cautions": 7.0, "cta": 5.0}
VISUALS = {"hook": "problem_scene", "why": "problem_scene", "how": "usage_scene", "pros_cautions": "product_stage",
           "cta": "endcard"}
REUSABLE = {ContentStatus.GENERATED, ContentStatus.BLOCKED, ContentStatus.REVISION_REQUESTED}


class DailyLimitReached(RuntimeError):
    pass


def clean_name(name: str) -> str:
    return re.sub(r"\[DEMO\]\s*", "", name).strip()


def _spec_line(p: Product, keys: list[str]) -> tuple[str, list[str]]:
    parts, refs = [], []
    for s in p.verified_specs or []:
        if s.get("key") in keys:
            parts.append(f"{s['key']} {s['value']}{s.get('unit') or ''}")
            refs.append(s["key"])
    return " · ".join(parts), refs


def mock_scenes(p: Product, profile: PsychologyProfile) -> tuple[str, list[dict], str, list[str]]:
    pr, a = p.problem or {}, profile.answers
    name = clean_name(p.name)
    spec_line, spec_refs = _spec_line(p, ["크기", "최대 하중", "내하중", "부착 방식"])
    steps = list(p.usage_steps or [])
    pros, cautions = list(p.pros or []), list(p.cautions or [])
    rec = (p.recommended_for or ["확인 필요"])[0]
    nrec = (p.not_recommended_for or ["확인 필요"])[0]
    scenes = [
        {"role": "hook", "on_screen_text": profile.hooks["A"], "narration": profile.hooks["A"], "fact_refs": []},
        {"role": "why", "on_screen_text": a["pain"],
         "narration": f"{a['when']}. {a['pain']}.", "fact_refs": []},
        {"role": "how", "on_screen_text": "\n".join(steps[:2]) or p.description or name,
         "narration": f"{name}. " + " ".join(f"{x}." for x in steps[:2]) + (f" {spec_line}." if spec_line else ""),
         "fact_refs": spec_refs + (["설치 방식"] if any(s.get("key") == "설치 방식" for s in p.verified_specs) else [])},
        {"role": "pros_cautions",
         "on_screen_text": f"좋은 점  {pros[0] if pros else '-'}\n확인할 점  {cautions[0] if cautions else '-'}",
         "narration": f"{pros[0] if pros else ''}. 다만 {cautions[0] if cautions else '사양을 먼저 확인하세요'}.",
         "fact_refs": [k for k in ("최대 하중", "내하중", "설치 방식", "부착 방식")
                       if any(s.get("key") == k for s in p.verified_specs)][:2]},
        {"role": "cta", "on_screen_text": f"맞는 분  {rec}\n안 맞는 분  {nrec}\n사양·가격은 프로필 링크에서",
         "narration": f"{rec}라면 볼 만합니다. {nrec}라면 맞지 않아요. 정확한 사양과 가격은 프로필 링크에서 확인하세요.",
         "fact_refs": []},
    ]
    title = f"{name} — {pr.get('surface_problem') or '살 사람, 안 맞는 사람'}"
    caption_body = "\n".join(filter(None, [
        profile.hooks["A"], "", f"✔ {a['pain']}", f"✔ {name}: " + (steps[0] if steps else (p.description or "")),
        f"✔ 확인할 점: {cautions[0]}" if cautions else "", f"✔ 맞는 분: {rec} / 안 맞는 분: {nrec}", "",
        "사양·가격(확인 시각 표시)은 프로필 링크의 상품 페이지에서 확인하세요."]))
    cat = load_policy("categories").get(p.category_key, {}).get("label", "생활용품")
    hashtags = ["#" + re.sub(r"[^0-9A-Za-z가-힣]", "", t) for t in [cat, *(p.keywords or [])[:3], "자취템", "정리"]]
    return title, scenes, caption_body, list(dict.fromkeys(hashtags))


def llm_scenes(p: Product, profile: PsychologyProfile) -> tuple[str, list[dict], str, list[str], dict]:
    client = AnthropicJSONClient(get_settings())
    user = SCRIPT_USER_TEMPLATE.format(
        facts_json=json.dumps(product_facts(p), ensure_ascii=False, indent=1),
        profile_json=json.dumps({"answers": profile.answers, "levers": profile.levers}, ensure_ascii=False, indent=1),
        hook_a=profile.hooks["A"], hook_b=profile.hooks["B"])
    data, usage = client.generate("script", SCRIPT_SYSTEM, user, SCRIPT_SCHEMA)
    by_role = {s["role"]: s for s in data["scenes"]}
    missing = [r for r in DURATIONS if r not in by_role]
    if missing:
        raise ValueError(f"LLM 대본에 장면 누락: {missing}")
    scenes = [by_role[r] for r in DURATIONS]
    tags = [t if t.startswith("#") else f"#{t}" for t in data["hashtags"] if t.strip("#") != "광고"]
    return data["title"], scenes, data["caption_body"], tags, usage


def build_script(content_id: str, p: Product, profile: PsychologyProfile, settings) -> tuple[dict, dict]:
    disc = load_policy("compliance")["disclosure"]
    usage: dict = {}
    if settings.llm_provider == "anthropic":
        title, scenes, caption_body, tags, usage = llm_scenes(p, profile)
        generator = "anthropic"
    else:
        title, scenes, caption_body, tags = mock_scenes(p, profile)
        generator = "mock(rule-based)"
    t = 0.0
    for i, sc in enumerate(scenes):
        sc["id"] = f"s{i + 1}"
        sc["duration"] = DURATIONS[sc["role"]]
        sc["start"] = round(t, 2)
        sc["visual"] = VISUALS[sc["role"]]
        sc["show_disclosure"] = sc["role"] == "hook"
        sc["transition_in"] = "crossfade_0.35s" if i else "cut"
        t += sc["duration"]
    hashtags = [disc["first_hashtag"]] + [h for h in tags if h != disc["first_hashtag"]][:8]
    landing = f"{settings.site_base_url.rstrip('/')}/p/{p.slug}?c={content_id}"
    est = 0.0
    if settings.llm_provider == "anthropic":
        est = float((usage or {}).get("cost_krw", 0.0))
    yt_title = f"{disc['youtube_title_prefix']} {title}"[:100]
    script = {
        "content_id": content_id, "product_id": p.id, "title": title, "duration_sec": t,
        "variants": {"A": {"hook_type": "problem_empathy", "hook": profile.hooks["A"]},
                     "B": {"hook_type": "result_explain", "hook": profile.hooks["B"]}},
        "scenes": scenes,
        "narration_full": " ".join(sc["narration"] for sc in scenes),
        "product_description": p.description,
        "cautions": list(p.cautions or []),
        "disclosure": {"badge": disc["video_badge"], "opening": disc["video_opening"],
                       "endcard": disc["coupang_required"], "caption_first_line": disc["caption_first_line"],
                       "placement": "전 장면 좌상단 '광고' 배지 + 첫 장면 문구 + 마지막 장면 전체 문구 + 캡션 첫 줄 + 첫 해시태그"},
        "cta": "사양·가격은 프로필 링크에서 확인",
        "caption": {
            "instagram": "\n".join([disc["caption_first_line"], "", caption_body, "", disc["coupang_required"], "",
                                    " ".join(hashtags)]),
            "youtube_title": yt_title,
            "youtube_description": "\n".join([disc["coupang_required"], "", caption_body,
                                              "상품 페이지: 채널 프로필 링크 (Shorts 설명란 링크는 클릭되지 않음)"]),
        },
        "hashtags": hashtags,
        "landing_url": landing,
        "landing_urls": {"instagram": landing + "&src=ig", "youtube": landing + "&src=yt"},
        "levers": profile.levers,
        "generator": generator,
        "facts_hash": facts_hash(p),
        "cost_estimate_krw": {"llm": est, "image": 0, "tts": 0, "render": 0, "total_cash": est,
                              "note": "로컬 렌더링 기준. 월 운영현금비 배분·노동비 제외"},
    }
    return script, usage


def generate_content(run_date: date, product_id: str) -> dict:
    settings = get_settings()
    with session_scope() as s:
        p = s.get(Product, product_id)
        profile = s.scalars(select(PsychologyProfile).where(PsychologyProfile.run_date == run_date,
                                                            PsychologyProfile.product_id == product_id)).first()
        if profile is None:
            raise RuntimeError("구매심리 분석 결과 없음 — 선행 단계 확인")
        existing = s.scalars(select(Content).where(Content.run_date == run_date, Content.product_id == product_id)
                             ).first()
        if existing and existing.status not in REUSABLE:
            return {"content_id": existing.id, "status": existing.status, "reused": True}
        if existing is None:
            n_today = s.scalar(select(func.count()).select_from(Content).where(
                Content.run_date == run_date, Content.status != ContentStatus.REJECTED)) or 0
            if n_today >= settings.daily_content_limit:
                raise DailyLimitReached(f"일일 생성 한도 {settings.daily_content_limit}개 도달")
            seq = (s.scalar(select(func.count()).select_from(Content).where(Content.run_date == run_date)) or 0) + 1
            content_id = f"C{run_date:%Y%m%d}-{seq:02d}"
        else:
            content_id = existing.id
        script, _ = build_script(content_id, p, profile, settings)
        check = check_script(script, p)
        content = existing or Content(id=content_id, run_date=run_date, product_id=p.id, title=script["title"],
                                      script=script, facts_hash=script["facts_hash"])
        content.title = script["title"]
        content.script = script
        content.facts_hash = script["facts_hash"]
        content.caption = script["caption"]["instagram"]
        content.hashtags = script["hashtags"]
        content.landing_path = f"/p/{p.slug}?c={content_id}"
        content.fact_check = check
        content.cost_estimate_krw = script["cost_estimate_krw"]["total_cash"]
        content.is_demo = p.is_demo
        content.status = ContentStatus.GENERATED if check["passed"] else ContentStatus.BLOCKED
        content.block_reasons = [i["message"] for i in check["issues"] if i["severity"] == "error"]
        if existing is None:
            s.add(content)
        p.content_status = content.status
        out_dir = settings.output_dir / "contents" / content_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        content.output_dir = str(out_dir)
        return {"content_id": content_id, "status": content.status, "fact_check": check}
