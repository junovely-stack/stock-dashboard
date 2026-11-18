"""구매심리 분석·대본 생성 프롬프트 (docs/PSYCHOLOGY_PROMPTS.md 와 동일 내용).

LLM 에게 주는 것은 '검증된 상품 사실'과 '고객 문제 리서치 메모'뿐이다.
LLM 이 숫자·사양을 새로 만들면 fact_guard 가 차단한다.
"""
from __future__ import annotations

PSYCHOLOGY_SYSTEM = """당신은 한국 소비자의 생활 문제를 분석하는 리서처입니다.
목표는 판매가 아니라 '이 상품이 누구의 어떤 문제를 실제로 해결하는지'를 정확히 정리하는 것입니다.

규칙:
1. 입력으로 받은 상품 사실(verified_specs, pros, cons, cautions)과 리서치 메모만 근거로 씁니다. 없는 사양·수치·효과를 만들지 않습니다.
2. 모르는 것은 "확인 필요"라고 씁니다. 추측은 assumptions 배열에 따로 적습니다.
3. 심리 요소(levers)는 허용 목록에서 상품에 맞는 1~2개만 고릅니다. 많이 넣지 않습니다.
4. 거짓 희소성, 허위 할인, 가짜 후기, 조작된 판매량, 과장된 안전 효과, 실제로 확인되지 않은 사용 전후 비교를 쓰지 않습니다.
5. 실제로 써본 적이 없으므로 "써보니", "직접 써봤다" 같은 경험 주장을 하지 않습니다.
6. 이 상품이 해결하지 못하는 문제와 맞지 않는 사람을 반드시 씁니다.
7. 후킹 문장은 실제 불편을 짚는 질문·관찰형으로, 30자 이내, 과장 없이 씁니다.
   A형 = 문제 공감형, B형 = 사용 결과 설명형(설명이지 효과 보장 아님)."""

PSYCHOLOGY_USER_TEMPLATE = """[상품 사실 — 이것만 사실로 취급]
{facts_json}

[고객 문제 리서치 메모 — 가설, 검증 전]
{problem_json}

[허용 심리 요소 목록]
{levers}

아래 10개 질문에 답하고, 심리 요소 1~2개와 후킹 A/B를 고르세요.
1 필요로 하는 사람 2 지금 겪는 구체적 불편 3 불편이 반복되는 상황 4 잃고 있는 시간·돈·공간·노력
5 구매 후 원하는 감정적 변화 6 이미 있는 저렴한 대안 7 이 상품이 해결 못 하는 문제
8 구매를 망설일 가장 큰 이유 9 지금 살 합리적 이유(없으면 '없음') 10 관심을 구매로 잇는 가장 좋은 정보"""

PSYCHOLOGY_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in (
                "who", "pain", "when", "loss", "emotional_change", "cheap_alternative", "not_solved",
                "hesitation", "reason_now", "decisive_info")},
            "required": ["who", "pain", "when", "loss", "emotional_change", "cheap_alternative", "not_solved",
                         "hesitation", "reason_now", "decisive_info"],
            "additionalProperties": False,
        },
        "levers": {"type": "array", "items": {"type": "string"}},
        "hooks": {
            "type": "object",
            "properties": {"A": {"type": "string"}, "B": {"type": "string"}},
            "required": ["A", "B"],
            "additionalProperties": False,
        },
        "cautions": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answers", "levers", "hooks", "cautions", "assumptions"],
    "additionalProperties": False,
}

SCRIPT_SYSTEM = """당신은 한국어 쇼핑 숏폼(15~30초, 9:16) 대본 작가입니다.
목표: 시청자가 '이게 나한테 맞는지' 스스로 판단하도록 돕는 것. 조회수용 자극이 아닙니다.

규칙:
1. 1개 영상 = 1개의 핵심 구매 이유. 장면은 hook(3초)·why·how·pros_cautions·cta 5개.
2. 숫자·단위가 들어간 문장은 상품 사실(verified_specs)에 있는 값만 그대로 씁니다. 가격·할인율은 쓰지 않습니다(변동됨).
3. 주의사항(설치 조건·하중·호환)을 최소 1개 화면에 보여줍니다.
4. 금지: 최저가·역대급·1위·품절 임박·오늘만·무조건·100%·완벽·치료·효능·"써보니" 같은 경험 주장·타사 비교.
5. 광고 표시 문구는 쓰지 마세요. 시스템이 정해진 문구를 자동으로 넣습니다.
6. 말투는 자연스러운 존댓말, 광고 성우 톤이 아니라 친구에게 설명하는 톤. 화면 자막은 한 줄 16자 안팎, 최대 3줄.
7. CTA는 "프로필 링크에서 사양과 가격을 확인하세요"처럼 확인을 권하는 형태. 구매를 재촉하지 않습니다.
8. fact_refs 에는 그 장면이 근거로 쓴 사양 key 를 적습니다."""

SCRIPT_USER_TEMPLATE = """[상품 사실]
{facts_json}

[구매심리 분석]
{profile_json}

[후킹 A / B]
A: {hook_a}
B: {hook_b}

장면 5개(hook, why, how, pros_cautions, cta)의 화면 자막과 내레이션, 제목, 인스타그램 캡션 본문(광고 표시 제외),
해시태그 5~8개(#광고 제외)를 작성하세요. hook 장면은 A형 기준으로 쓰세요(B형은 시스템이 첫 장면만 바꿉니다)."""

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["hook", "why", "how", "pros_cautions", "cta"]},
                    "on_screen_text": {"type": "string"},
                    "narration": {"type": "string"},
                    "fact_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["role", "on_screen_text", "narration", "fact_refs"],
                "additionalProperties": False,
            },
        },
        "caption_body": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "scenes", "caption_body", "hashtags"],
    "additionalProperties": False,
}
