"""관리자 검수 액션: 승인·거절·수정 요청·문구 수정·예약·삭제. 모든 액션은 감사 로그에 남는다."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.models import (AffiliateLink, AuditLog, Content, ContentStatus, MetricObservation, Product, ProductImage,
                        ProductScore, Publication, PubStatus, PsychologyProfile, SiteEvent)
from services.common.facts import facts_hash
from services.common.timeutil import now_utc
from services.script_generator.fact_guard import check_script


class ReviewError(RuntimeError):
    pass


def approve(s, c: Content, actor: str, notes: str | None = None) -> None:
    if c.status != ContentStatus.AWAITING_APPROVAL:
        raise ReviewError(f"승인 대기 상태가 아님 ({c.status})")
    if not (c.qa_result or {}).get("passed") or not (c.fact_check or {}).get("passed"):
        raise ReviewError("자동 검사 미통과 콘텐츠는 승인할 수 없음")
    if facts_hash(c.product) != c.facts_hash:
        raise ReviewError("상품 사실 정보가 생성 이후 바뀜 — 재생성 필요")
    c.status = ContentStatus.APPROVED
    c.approved_by = actor
    c.approved_at = now_utc()
    c.review_notes = notes
    c.product.content_status = c.status
    s.add(AuditLog(actor=actor, action="approve", target_type="content", target_id=c.id,
                   detail={"notes": notes, "facts_hash": c.facts_hash}))


def reject(s, c: Content, actor: str, reason: str) -> None:
    c.status = ContentStatus.REJECTED
    c.review_notes = reason
    s.add(AuditLog(actor=actor, action="reject", target_type="content", target_id=c.id, detail={"reason": reason}))


def request_revision(s, c: Content, actor: str, note: str) -> None:
    c.status = ContentStatus.REVISION_REQUESTED
    c.review_notes = note
    c.approved_by = None
    c.approved_at = None
    s.add(AuditLog(actor=actor, action="request_revision", target_type="content", target_id=c.id,
                   detail={"note": note}))


def edit_copy(s, c: Content, actor: str, title: str | None = None, caption_body: str | None = None,
              scene_texts: dict[str, str] | None = None) -> dict:
    """문구 수동 수정 → 사실·표시 검사 재실행 → 승인 상태 해제(재승인 필요). 영상 재렌더 필요 여부 표시."""
    script = json.loads(json.dumps(c.script, ensure_ascii=False))
    changed_video = False
    if title:
        script["title"] = title
        prefix = script["caption"]["youtube_title"].split(" ")[0]
        script["caption"]["youtube_title"] = f"{prefix} {title}"[:100]
    if caption_body is not None:
        disc = script["disclosure"]
        script["caption"]["instagram"] = "\n".join([disc["caption_first_line"], "", caption_body, "",
                                                     disc["endcard"], "", " ".join(script["hashtags"])])
    for sid, text in (scene_texts or {}).items():
        for sc in script["scenes"]:
            if sc["id"] == sid and sc["on_screen_text"] != text:
                sc["on_screen_text"] = text
                changed_video = True
    check = check_script(script, c.product)
    c.script = script
    c.title = script["title"]
    c.caption = script["caption"]["instagram"]
    c.fact_check = check
    c.approved_by = None
    c.approved_at = None
    if not check["passed"]:
        c.status = ContentStatus.BLOCKED
        c.block_reasons = [i["message"] for i in check["issues"] if i["severity"] == "error"]
    else:
        c.status = ContentStatus.REVISION_REQUESTED if changed_video else ContentStatus.AWAITING_APPROVAL
        c.block_reasons = []
    if c.output_dir:
        (Path(c.output_dir) / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    s.add(AuditLog(actor=actor, action="edit_copy", target_type="content", target_id=c.id,
                   detail={"passed": check["passed"], "rerender_needed": changed_video}))
    return {"passed": check["passed"], "rerender_needed": changed_video}


def schedule(s, c: Content, actor: str, when: datetime) -> None:
    if c.status != ContentStatus.APPROVED:
        raise ReviewError("승인된 콘텐츠만 예약 가능")
    c.scheduled_at = when
    s.add(AuditLog(actor=actor, action="schedule", target_type="content", target_id=c.id,
                   detail={"at": when.isoformat()}))


def delete_product(s, product_id: str, actor: str) -> dict:
    """상품과 관련 콘텐츠·파일·이벤트 삭제 (데이터 삭제 기능). 게시된 플랫폼 게시물은 각 플랫폼에서 직접 삭제해야 함."""
    p = s.get(Product, product_id)
    if p is None:
        raise ReviewError("상품 없음")
    contents = list(s.scalars(select(Content).where(Content.product_id == product_id)))
    live = [pub for c in contents for pub in s.scalars(select(Publication).where(Publication.content_id == c.id))
            if pub.status in PubStatus.DONE]
    for c in contents:
        if c.output_dir and Path(c.output_dir).exists():
            shutil.rmtree(c.output_dir, ignore_errors=True)
        s.execute(delete(MetricObservation).where(MetricObservation.content_id == c.id))
        s.execute(delete(SiteEvent).where(SiteEvent.content_id == c.id))
        s.execute(delete(Publication).where(Publication.content_id == c.id))
        s.delete(c)
    s.execute(delete(SiteEvent).where(SiteEvent.product_id == product_id))
    s.execute(delete(ProductScore).where(ProductScore.product_id == product_id))
    s.execute(delete(PsychologyProfile).where(PsychologyProfile.product_id == product_id))
    s.delete(p)
    s.add(AuditLog(actor=actor, action="delete_product", target_type="product", target_id=product_id,
                   detail={"contents": [c.id for c in contents], "live_platform_posts": [
                       {"platform": x.platform, "media_id": x.platform_media_id} for x in live]}))
    return {"deleted_contents": len(contents), "platform_posts_to_remove_manually": len(live)}


def purge_events(s, older_than_days: int) -> int:
    from datetime import timedelta

    cutoff = now_utc() - timedelta(days=older_than_days)
    res = s.execute(delete(SiteEvent).where(SiteEvent.ts < cutoff.replace(tzinfo=None)))
    return res.rowcount or 0
