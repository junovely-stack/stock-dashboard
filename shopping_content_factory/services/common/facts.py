"""상품 '사실' 묶음과 해시. 콘텐츠 생성 시점의 해시와 게시 시점 해시가 다르면 게시를 막는다."""
from __future__ import annotations

import hashlib
import json
import re

from app.models import Product

_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(cm|mm|m|kg|g|W|V|mAh|L|ml|개입|단|칸|구|%|시간|분|초|원|매|인치)")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def product_facts(p: Product) -> dict:
    return {
        "name": p.name,
        "verified_specs": [{k: s.get(k) for k in ("key", "value", "unit")} for s in (p.verified_specs or [])],
        "pros": list(p.pros or []),
        "cons": list(p.cons or []),
        "cautions": list(p.cautions or []),
        "recommended_for": list(p.recommended_for or []),
        "not_recommended_for": list(p.not_recommended_for or []),
    }


def facts_hash(p: Product) -> str:
    payload = json.dumps(product_facts(p), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def allowed_number_units(p: Product) -> set[tuple[str, str]]:
    """검증 사양·주의사항에 등장하는 (숫자, 단위) 쌍. '15~40mm' 같은 범위는 양 끝 모두 포함."""
    allowed: set[tuple[str, str]] = set()
    texts = []
    for s in p.verified_specs or []:
        value, unit = str(s.get("value", "")), (s.get("unit") or "")
        texts.append(f"{value}{unit}")
        if unit:
            for n in _NUM.findall(value):
                allowed.add((_norm(n), unit))
    texts += list(p.cautions or []) + list(p.pros or []) + list(p.cons or [])
    for t in texts:
        # '15~40mm' → 15mm, 40mm
        for a, b, unit in re.findall(r"(\d+(?:\.\d+)?)\s*[~\-]\s*(\d+(?:\.\d+)?)\s*(cm|mm|kg|g|L|ml|인치)", t):
            allowed.add((_norm(a), unit))
            allowed.add((_norm(b), unit))
        for n, unit in _NUM_UNIT.findall(t):
            allowed.add((_norm(n), unit))
    return allowed


def extract_number_units(text: str) -> list[tuple[str, str]]:
    out = []
    for a, b, unit in re.findall(r"(\d+(?:\.\d+)?)\s*[~\-]\s*(\d+(?:\.\d+)?)\s*(cm|mm|kg|g|L|ml|인치)", text):
        out += [(_norm(a), unit), (_norm(b), unit)]
    stripped = re.sub(r"(\d+(?:\.\d+)?)\s*[~\-]\s*(\d+(?:\.\d+)?)\s*(cm|mm|kg|g|L|ml|인치)", " ", text)
    out += [(_norm(n), u) for n, u in _NUM_UNIT.findall(stripped)]
    return out


def _norm(n: str) -> str:
    f = float(n)
    return str(int(f)) if f.is_integer() else str(f)
