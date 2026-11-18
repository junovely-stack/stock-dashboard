"""게시 안전장치: 미승인 차단, 자격증명 없음 ≠ 성공, 중복 업로드 방지, 상태 분리."""
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from adapters.base import PublishResult
from tests.conftest import RUN_DATE, register_verified_link

CID = "C20261118-01"


def _approve():
    from app.models import Content
    from services.common.db import session_scope
    from services.social_publishers.review import approve

    with session_scope() as s:
        approve(s, s.get(Content, CID), "tester")


class FakePublisher:
    """플랫폼 API 대역. 호출 횟수를 센다."""

    def __init__(self, verify_status="published_verified"):
        self.calls = 0
        self.verify_status = verify_status

    def is_configured(self):
        return True

    def missing_requirements(self):
        return []

    def publish(self, *a, **kw):
        self.calls += 1
        return PublishResult("api_accepted", media_id=f"M{self.calls}")

    def verify(self, media_id):
        return PublishResult(self.verify_status, media_id=media_id, url=f"https://example.invalid/{media_id}")


def test_unapproved_content_is_not_published(pipeline):
    from services.social_publishers.publisher import publish_content

    register_verified_link()
    fake = FakePublisher()
    res = publish_content(CID, "youtube", "tester", publisher=fake)
    assert res["status"] == "blocked"
    assert any("승인 없음" in r for r in res["reasons"])
    assert fake.calls == 0


def test_missing_link_blocks(pipeline):
    from services.social_publishers.publisher import publish_content

    _approve()
    fake = FakePublisher()
    res = publish_content(CID, "youtube", "tester", publisher=fake)
    assert res["status"] == "blocked" and fake.calls == 0
    assert any("제휴 링크" in r for r in res["reasons"])


def test_no_credentials_is_pending_not_success(pipeline):
    from app.models import Publication
    from services.common.db import session_scope
    from services.social_publishers.publisher import publish_content

    _approve()
    register_verified_link()
    for platform in ("instagram", "youtube"):
        res = publish_content(CID, platform, "tester")
        assert res["status"] == "pending_credentials", res
    with session_scope() as s:
        statuses = {p.platform: p.status for p in s.scalars(select(Publication))}
        assert statuses == {"instagram": "pending_credentials", "youtube": "pending_credentials"}
        assert all(p.platform_media_id is None for p in s.scalars(select(Publication)))


def test_duplicate_runs_upload_once_and_states_are_separate(pipeline):
    from app.models import Content, Publication
    from services.common.db import session_scope
    from services.social_publishers.publisher import publish_content

    _approve()
    register_verified_link()
    fake = FakePublisher(verify_status="api_accepted")
    r1 = publish_content(CID, "youtube", "tester", publisher=fake)
    r2 = publish_content(CID, "youtube", "tester", publisher=fake)
    r3 = publish_content(CID, "youtube", "scheduler", trigger="scheduler", publisher=fake)
    assert r1["status"] == "api_accepted"           # 플랫폼 수락 ≠ 공개 확인
    assert r2.get("duplicate_prevented") and r3.get("duplicate_prevented")
    assert fake.calls == 1
    with session_scope() as s:
        n = s.scalar(select(func.count()).select_from(Publication).where(Publication.platform == "youtube"))
        assert n == 1
        assert s.get(Content, CID).status == "approved"  # 공개 확인 전에는 published 아님


def test_verified_publish_marks_content_published(pipeline):
    from app.models import Content
    from services.common.db import session_scope
    from services.social_publishers.publisher import publish_content

    _approve()
    register_verified_link()
    res = publish_content(CID, "youtube", "tester", publisher=FakePublisher())
    assert res["status"] == "published_verified"
    with session_scope() as s:
        assert s.get(Content, CID).status == "published"


def test_auto_publish_false_waits_for_human(pipeline):
    from services.social_publishers.publisher import publish_content

    _approve()
    register_verified_link()
    fake = FakePublisher()
    res = publish_content(CID, "instagram", "scheduler", trigger="scheduler", publisher=fake)
    assert res["status"] == "waiting_manual" and fake.calls == 0
    res2 = publish_content(CID, "instagram", "tester", trigger="manual", publisher=fake)
    assert res2["status"] == "published_verified" and fake.calls == 1


def test_stale_price_and_soldout_block(pipeline):
    from app.models import Product
    from services.common.db import session_scope
    from services.common.timeutil import now_utc
    from services.social_publishers.publisher import publish_content

    _approve()
    register_verified_link()
    with session_scope() as s:
        p = s.get(Product, "DEMO-001")
        p.price_checked_at = now_utc() - timedelta(hours=30)
        p.stock_status = "out_of_stock"
    res = publish_content(CID, "youtube", "tester", publisher=FakePublisher())
    assert res["status"] == "blocked"
    joined = " ".join(res["reasons"])
    assert "가격 확인 만료" in joined and "품절" in joined


def test_video_changed_after_approval_blocks(pipeline):
    from services.social_publishers.publisher import publish_content

    _approve()
    register_verified_link()
    video = Path(pipeline / "out" / "contents" / CID / "shorts_final.mp4")
    video.write_bytes(video.read_bytes() + b"tampered")
    res = publish_content(CID, "youtube", "tester", publisher=FakePublisher())
    assert res["status"] == "blocked" and any("영상 파일이 바뀜" in r for r in res["reasons"])


def test_blocked_attempt_can_retry_after_fix(pipeline):
    from services.social_publishers.publisher import publish_content

    _approve()
    fake = FakePublisher()
    assert publish_content(CID, "youtube", "tester", publisher=fake)["status"] == "blocked"
    register_verified_link()
    assert publish_content(CID, "youtube", "tester", publisher=fake)["status"] == "published_verified"
    assert fake.calls == 1


def test_link_validation_rejects_non_partner_urls():
    from services.affiliate_links.links import validate_affiliate_url

    assert validate_affiliate_url("https://link.coupang.com/a/abc123")[0]
    assert not validate_affiliate_url("http://link.coupang.com/a/abc123")[0]
    assert not validate_affiliate_url("https://www.coupang.com/vp/products/1")[0]
    assert not validate_affiliate_url("https://bit.ly/xyz")[0]
