"""게시 오케스트레이션 — 승인 게이트, 중복 방지, 상태 분리.

상태 흐름 (publications.status)
  queued → in_progress → api_accepted(플랫폼이 ID 반환) → published_verified(조회로 공개 확인)
  게이트 실패 → blocked / 자격증명 없음 → pending_credentials / AUTO_PUBLISH=false 예약 실행 → waiting_manual
  응답 불확실 → unknown (중복 업로드 위험이 있어 자동 재시도하지 않음)

중복 방지: (content_id, variant, platform) 유니크 + idempotency_key 유니크 + 조건부 UPDATE 로 선점.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from adapters.base import PublishResult
from adapters.instagram.graph import InstagramPublisher
from adapters.youtube.data_api import YouTubePublisher
from app.models import (AuditLog, Content, ContentStatus, ImageRights, LinkStatus, Publication, PubStatus,
                        StockStatus)
from config.settings import get_settings
from services.common.db import new_session, session_scope
from services.common.facts import facts_hash
from services.common.http import NotConfiguredError
from services.common.logging_utils import get_logger, redact_obj
from services.common.timeutil import hours_since, now_local, now_utc

log = get_logger(__name__)
PLATFORMS = ("instagram", "youtube")
VIDEO_FILE = {"instagram": "reel_final.mp4", "youtube": "shorts_final.mp4"}


def gate(c: Content, platform: str, settings) -> list[str]:
    """게시 직전 차단 사유 목록. 비어 있어야 게시."""
    p = c.product
    reasons = []
    if c.status not in (ContentStatus.APPROVED, ContentStatus.PUBLISHED) or not c.approved_by:
        reasons.append(f"사람 승인 없음 (상태 {c.status})")
    if not (c.qa_result or {}).get("passed"):
        reasons.append("자동 QA 미통과")
    if not (c.fact_check or {}).get("passed"):
        reasons.append("사실·표시 검사 미통과")
    if facts_hash(p) != c.facts_hash:
        reasons.append("승인 후 상품 사실 정보가 바뀜 — 재생성·재승인 필요")
    age = hours_since(p.price_checked_at)
    if age is None or age > settings.price_ttl_hours:
        reasons.append("가격 확인 만료 — 가격 재확인 필요")
    if p.stock_status not in (StockStatus.IN_STOCK, StockStatus.LOW_STOCK):
        reasons.append(f"재고 {p.stock_status} — 품절 상품 게시 차단")
    if p.affiliate_link_status != LinkStatus.VERIFIED:
        reasons.append(f"제휴 링크 {p.affiliate_link_status} — 확인된 링크 필요")
    if p.image_rights_status not in ImageRights.VIDEO_OK:
        reasons.append("이미지 권리 미확인")
    out = Path(c.output_dir or "")
    video = out / VIDEO_FILE[platform]
    if not video.exists():
        reasons.append("영상 파일 없음")
    else:
        man = out / "content_manifest.json"
        if man.exists():
            files = json.loads(man.read_text(encoding="utf-8")).get("files", {})
            expected = files.get(VIDEO_FILE[platform].replace(".mp4", ""), {}).get("sha256_16")
            actual = hashlib.sha256(video.read_bytes()).hexdigest()[:16]
            if expected and expected != actual:
                reasons.append("승인 후 영상 파일이 바뀜 — 재승인 필요")
    return reasons


def _publisher(platform: str, settings):
    return InstagramPublisher(settings) if platform == "instagram" else YouTubePublisher(settings)


def _claim(content_id: str, variant: str, platform: str) -> tuple[int | None, str | None]:
    """게시 행 선점. (pub_id, None) 이면 진행, (pub_id, 상태) 면 이미 처리됨 → 중단."""
    key = f"{content_id}:{variant}:{platform}"
    s = new_session()
    try:
        row = s.scalars(select(Publication).where(Publication.idempotency_key == key)).first()
        if row is None:
            row = Publication(content_id=content_id, variant=variant, platform=platform, idempotency_key=key,
                              status=PubStatus.IN_PROGRESS, attempts=1, requested_at=now_utc())
            s.add(row)
            try:
                s.commit()
                return row.id, None
            except IntegrityError:
                s.rollback()
                row = s.scalars(select(Publication).where(Publication.idempotency_key == key)).first()
        if row.status == PubStatus.IN_PROGRESS and row.updated_at and hours_since(row.updated_at) > 0.5:
            s.execute(update(Publication).where(Publication.id == row.id, Publication.status == PubStatus.IN_PROGRESS)
                      .values(status=PubStatus.UNKNOWN, error="진행 중 중단 — 플랫폼에서 직접 확인 후 수동 처리"))
            s.commit()
            return row.id, PubStatus.UNKNOWN
        res = s.execute(update(Publication).where(Publication.id == row.id,
                                                  Publication.status.in_(list(PubStatus.RETRYABLE)))
                        .values(status=PubStatus.IN_PROGRESS, attempts=Publication.attempts + 1,
                                requested_at=now_utc(), error=None))
        s.commit()
        if res.rowcount == 1:
            return row.id, None
        return row.id, row.status
    finally:
        s.close()


def _finish(pub_id: int, status: str, **fields) -> None:
    with session_scope() as s:
        row = s.get(Publication, pub_id)
        row.status = status
        for k, v in fields.items():
            setattr(row, k, v)


def publish_content(content_id: str, platform: str, actor: str, trigger: str = "manual",
                    publisher=None) -> dict:
    settings = get_settings()
    if platform not in PLATFORMS:
        raise ValueError(platform)
    with session_scope() as s:
        c = s.get(Content, content_id)
        variant = c.primary_variant
        if trigger != "manual":
            day_start = now_utc() - timedelta(hours=24)
            n = s.scalar(select(func.count()).select_from(Publication).where(
                Publication.status.in_(list(PubStatus.DONE)), Publication.api_accepted_at >= day_start)) or 0
            if n >= settings.daily_publish_limit:
                return {"status": PubStatus.BLOCKED, "reasons": [f"24시간 게시 한도 {settings.daily_publish_limit}건"]}
    pub_id, existing = _claim(content_id, variant, platform)
    if existing:
        return {"status": existing, "publication_id": pub_id, "duplicate_prevented": True}

    with session_scope() as s:
        c = s.get(Content, content_id)
        reasons = gate(c, platform, settings)
        if reasons:
            _finish(pub_id, PubStatus.BLOCKED, detail={"reasons": reasons})
            s.add(AuditLog(actor=actor, action="publish_blocked", target_type="content", target_id=content_id,
                           detail={"platform": platform, "reasons": reasons}))
            return {"status": PubStatus.BLOCKED, "reasons": reasons, "publication_id": pub_id}
        if trigger != "manual" and not settings.auto_publish:
            _finish(pub_id, PubStatus.WAITING_MANUAL, detail={"reasons": ["AUTO_PUBLISH=false — 관리자 '게시' 버튼 필요"]})
            return {"status": PubStatus.WAITING_MANUAL, "publication_id": pub_id}
        out = Path(c.output_dir)
        script = c.script
        local = now_local()
        confounders = {"published_hour_kst": local.hour, "weekday": local.strftime("%a"), "variant": c.primary_variant,
                       "hook_type": script["variants"][c.primary_variant]["hook_type"], "trigger": trigger}
        pub = publisher or _publisher(platform, settings)
        try:
            if platform == "instagram":
                if not pub.is_configured():
                    raise NotConfiguredError(", ".join(pub.missing_requirements()))
                url = f"{settings.media_base_url or ''}/{content_id}/{VIDEO_FILE[platform]}"
                result: PublishResult = pub.publish(url, script["caption"]["instagram"], c.ai_generated_media)
            else:
                result = pub.publish(out / VIDEO_FILE[platform], script["caption"]["youtube_title"],
                                     script["caption"]["youtube_description"],
                                     [h.lstrip("#") for h in script["hashtags"]], c.ai_generated_media)
        except NotConfiguredError as exc:
            _finish(pub_id, PubStatus.PENDING_CREDENTIALS, confounders=confounders,
                    detail={"missing": str(exc), "note": "권한·자격증명 없음 — 실제로 게시하지 않았음"})
            s.add(AuditLog(actor=actor, action="publish_pending_credentials", target_type="content",
                           target_id=content_id, detail={"platform": platform, "missing": str(exc)}))
            return {"status": PubStatus.PENDING_CREDENTIALS, "missing": str(exc), "publication_id": pub_id}
        except Exception as exc:  # noqa: BLE001
            _finish(pub_id, PubStatus.FAILED, error=str(exc)[:1000], confounders=confounders)
            s.add(AuditLog(actor=actor, action="publish_failed", target_type="content", target_id=content_id,
                           detail={"platform": platform, "error": str(exc)[:300]}))
            return {"status": PubStatus.FAILED, "error": str(exc), "publication_id": pub_id}

        fields = {"platform_media_id": result.media_id, "platform_url": result.url, "error": result.error,
                  "detail": redact_obj(result.detail), "confounders": confounders}
        status = result.status
        if status == PubStatus.API_ACCEPTED:
            fields["api_accepted_at"] = now_utc()
            try:
                v = pub.verify(result.media_id)
                if v.status == PubStatus.PUBLISHED_VERIFIED:
                    status = PubStatus.PUBLISHED_VERIFIED
                    fields["verified_at"] = now_utc()
                    fields["platform_url"] = v.url or result.url
                else:
                    fields["error"] = v.error
            except Exception as exc:  # noqa: BLE001 — 확인 실패해도 게시 자체는 유지, 다음 집계 때 재확인
                fields["error"] = f"게시 확인 실패: {exc}"
        _finish(pub_id, status, **fields)
        if status == PubStatus.PUBLISHED_VERIFIED:
            c.status = ContentStatus.PUBLISHED
        s.add(AuditLog(actor=actor, action=f"publish_{status}", target_type="content", target_id=content_id,
                       detail={"platform": platform, "media_id": result.media_id}))
        return {"status": status, "media_id": result.media_id, "publication_id": pub_id}


def publish_due(run_date) -> dict:
    """12:00 예약 단계: 승인되었고 예약 시각이 지난 콘텐츠만."""
    out = []
    with session_scope() as s:
        ids = [c.id for c in s.scalars(select(Content).where(Content.status == ContentStatus.APPROVED))
               if c.scheduled_at is None or hours_since(c.scheduled_at) >= 0]
    for cid in ids:
        for platform in PLATFORMS:
            out.append({"content_id": cid, "platform": platform,
                        **publish_content(cid, platform, actor="scheduler", trigger="scheduler")})
    return {"attempted": len(out), "results": out}
