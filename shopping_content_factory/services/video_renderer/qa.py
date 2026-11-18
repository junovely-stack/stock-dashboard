"""자동 QA (09:00) — 사람 승인 전 기계가 걸러내는 단계.

error 가 하나라도 있으면 BLOCKED, 없으면 AWAITING_APPROVAL.
warning 은 승인 화면에 노출(예: 제휴 링크 미등록 → 게시 전 등록 필요).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.models import Content, ContentStatus, ImageRights, LinkStatus, StockStatus
from config.settings import get_settings
from services.common.db import session_scope
from services.common.facts import facts_hash
from services.common.timeutil import hours_since, now_utc
from services.video_renderer.renderer import probe


def _check(name: str, passed: bool, detail: str, severity: str = "error") -> dict:
    return {"name": name, "passed": bool(passed), "severity": severity, "detail": detail}


def run_qa(content_id: str) -> dict:
    settings = get_settings()
    with session_scope() as s:
        c = s.get(Content, content_id)
        p = c.product
        out = Path(c.output_dir)
        checks = [_check("fact_guard", (c.fact_check or {}).get("passed", False),
                         f"사실·표시 검사 문제 {len((c.fact_check or {}).get('issues', []))}건")]
        for name in ("reel_final", "shorts_final"):
            f = out / f"{name}.mp4"
            if not f.exists():
                checks.append(_check(f"{name}.exists", False, "영상 파일 없음"))
                continue
            info = probe(f)
            ok = (info.get("width") == 1080 and info.get("height") == 1920 and 15 <= info.get("duration", 0) <= 30
                  and info.get("codec") == "h264" and info.get("pix_fmt") == "yuv420p" and info.get("has_audio"))
            checks.append(_check(f"{name}.spec", ok,
                                 f"{info.get('width')}x{info.get('height')} {info.get('duration')}s "
                                 f"{info.get('codec')}/{info.get('pix_fmt')} audio={info.get('has_audio')}"))
        man_path = out / "image_manifest.json"
        if man_path.exists():
            man = json.loads(man_path.read_text(encoding="utf-8"))
            checks.append(_check("image_rights", man.get("all_rights_cleared"), "모든 이미지 권리 확인"))
            checks.append(_check("product_preserved", man.get("all_preserved"), "상품 원형 보존 검수"))
        else:
            checks.append(_check("image_manifest", False, "image_manifest.json 없음"))
        checks.append(_check("facts_unchanged", facts_hash(p) == c.facts_hash, "생성 이후 상품 사실 정보 변경 여부"))
        checks.append(_check("stock", p.stock_status in (StockStatus.IN_STOCK, StockStatus.LOW_STOCK),
                             f"재고 {p.stock_status}"))
        age = hours_since(p.price_checked_at)
        checks.append(_check("price_fresh", age is not None and age <= settings.price_ttl_hours,
                             f"가격 확인 {age:.0f}시간 전" if age is not None else "가격 미확인", "warning"))
        checks.append(_check("affiliate_link", p.affiliate_link_status == LinkStatus.VERIFIED,
                             f"제휴 링크 {p.affiliate_link_status} — 게시 전 '확인 완료' 필요", "warning"))
        checks.append(_check("image_rights_product", p.image_rights_status in ImageRights.VIDEO_OK,
                             f"상품 이미지 권리 {p.image_rights_status}"))
        errors = [ch for ch in checks if not ch["passed"] and ch["severity"] == "error"]
        result = {"passed": not errors, "checked_at": now_utc().isoformat(), "checks": checks}
        c.qa_result = result
        if errors:
            c.status = ContentStatus.BLOCKED
            c.block_reasons = list(dict.fromkeys((c.block_reasons or []) + [f"QA: {e['name']} — {e['detail']}"
                                                                             for e in errors]))
        elif c.status in (ContentStatus.GENERATED, ContentStatus.REVISION_REQUESTED):
            c.status = ContentStatus.AWAITING_APPROVAL
        p.content_status = c.status
        return {"content_id": content_id, "status": c.status, "errors": [e["name"] for e in errors],
                "warnings": [ch["name"] for ch in checks if not ch["passed"] and ch["severity"] == "warning"]}
