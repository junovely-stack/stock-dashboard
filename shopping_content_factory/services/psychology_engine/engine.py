"""구매심리 분석 엔진.

- mock(기본): 상품의 고객 문제 리서치 메모를 규칙으로 정리 (비용 0)
- anthropic: Claude 구조화 출력 → 검증(허용 심리요소 1~2개, 금칙어) 통과해야 저장
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import delete

from adapters.llm.anthropic_client import AnthropicJSONClient
from app.models import Product, PsychologyProfile
from config.settings import get_settings, load_policy
from services.common.db import session_scope
from services.common.facts import product_facts
from services.psychology_engine.prompts import (PSYCHOLOGY_SCHEMA, PSYCHOLOGY_SYSTEM, PSYCHOLOGY_USER_TEMPLATE)

LOSS_LEVER = {"space": "공간 확보 욕구", "time": "시간 절약 욕구", "effort": "생활의 통제감", "money": "손실 회피"}


def mock_profile(p: Product) -> dict:
    pr = p.problem or {}
    loss = pr.get("loss") or {}
    levers: list[str] = []
    if "통제" in (pr.get("desired_change") or ""):
        levers.append("생활의 통제감")
    for k in ("space", "time", "effort", "money"):
        lv = LOSS_LEVER[k]
        if loss.get(k) and lv not in levers:
            levers.append(lv)
    levers = levers[:2] or ["안전하고 합리적인 선택"]
    hooks = pr.get("hooks") or {}
    return {
        "answers": {
            "who": pr.get("persona") or "확인 필요",
            "pain": pr.get("real_pain") or "확인 필요",
            "when": pr.get("situation") or "확인 필요",
            "loss": ", ".join(f"{k}: {v}" for k, v in loss.items() if v) or "확인 필요",
            "emotional_change": pr.get("desired_change") or "확인 필요",
            "cheap_alternative": pr.get("cheap_alternative") or "확인 필요",
            "not_solved": pr.get("not_solved") or "; ".join(p.cons or []) or "확인 필요",
            "hesitation": pr.get("hesitation") or "확인 필요",
            "reason_now": pr.get("reason_now") or "없음",
            "decisive_info": pr.get("decisive_info") or "확인 필요",
        },
        "levers": levers,
        "hooks": {"A": hooks.get("A") or f"{pr.get('surface_problem') or p.name}, 그대로 두고 계신가요?",
                  "B": hooks.get("B") or f"{p.name}, 설치 조건부터 확인하세요"},
        "cautions": list(p.cautions or []),
        "assumptions": ["고객 문제 메모는 리서치 가설이며 실사용자 인터뷰·후기로 검증되지 않음"],
    }


def validate_profile(profile: dict) -> list[str]:
    comp = load_policy("compliance")
    allowed = set(comp["psychology"]["allowed_levers"])
    issues = []
    levers = profile.get("levers", [])
    if not 1 <= len(levers) <= comp["psychology"]["max_levers"]:
        issues.append(f"심리 요소는 1~{comp['psychology']['max_levers']}개 — 현재 {len(levers)}개")
    bad = [lv for lv in levers if lv not in allowed]
    if bad:
        issues.append(f"허용 목록 밖 심리 요소: {bad}")
    for key, hook in (profile.get("hooks") or {}).items():
        if len(hook) > 40:
            issues.append(f"후킹 {key} 40자 초과")
        for cat, words in comp["banned_phrases"].items():
            if cat == "experience_claims":
                continue
            hits = [w for w in words if w in hook]
            if hits:
                issues.append(f"후킹 {key} 금칙어({cat}): {hits}")
    return issues


def analyze(run_date: date, product_id: str) -> dict:
    settings = get_settings()
    with session_scope() as s:
        p = s.get(Product, product_id)
        meta: dict = {"generator": "mock", "model": None}
        if settings.llm_provider == "anthropic":
            client = AnthropicJSONClient(settings)
            user = PSYCHOLOGY_USER_TEMPLATE.format(
                facts_json=json.dumps(product_facts(p), ensure_ascii=False, indent=1),
                problem_json=json.dumps(p.problem or {}, ensure_ascii=False, indent=1),
                levers=", ".join(load_policy("compliance")["psychology"]["allowed_levers"]))
            profile, usage = client.generate("psychology", PSYCHOLOGY_SYSTEM, user, PSYCHOLOGY_SCHEMA)
            meta = {"generator": "anthropic", "model": usage["model"], "usage": usage}
        else:
            profile = mock_profile(p)
        issues = validate_profile(profile)
        if issues:
            raise ValueError("구매심리 분석 검증 실패: " + "; ".join(issues))
        s.execute(delete(PsychologyProfile).where(PsychologyProfile.run_date == run_date,
                                                  PsychologyProfile.product_id == product_id))
        s.add(PsychologyProfile(run_date=run_date, product_id=product_id, answers=profile["answers"],
                                levers=profile["levers"], hooks=profile["hooks"], cautions=profile["cautions"],
                                generator=meta["generator"], model=meta.get("model"),
                                validation={"issues": issues, "assumptions": profile.get("assumptions", []),
                                            "usage": meta.get("usage")}))
    return {"product_id": product_id, "levers": profile["levers"], "hooks": profile["hooks"],
            "generator": meta["generator"]}
