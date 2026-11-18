"""외부 어댑터 — 실제 네트워크 없이 요청 형식·재시도·미설정 처리를 검증."""
from datetime import datetime, timezone

import pytest
import requests


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = str(self._body)
        self.ok = 200 <= status < 300

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


class SeqSession:
    def __init__(self, items):
        self.items = list(items)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_retry_on_429_then_success_respects_retry_after():
    from services.common.http import HttpClient, HttpConfig

    sleeps = []
    sess = SeqSession([Resp(429, headers={"Retry-After": "2"}), requests.ConnectionError("x"), Resp(200, {"a": 1})])
    c = HttpClient("t", HttpConfig(max_retries=3, backoff_base=0.01), session=sess, sleep=sleeps.append, recorder=None)
    assert c.get("https://example.invalid").json() == {"a": 1}
    assert sleeps[0] == 2.0 and len(sess.calls) == 3
    assert sess.calls[0][2]["timeout"] == (5.0, 20.0)


def test_4xx_not_retried():
    from services.common.http import HttpClient, HttpConfig

    sess = SeqSession([Resp(400)])
    c = HttpClient("t", HttpConfig(max_retries=3), session=sess, sleep=lambda s: None, recorder=None)
    assert c.get("https://example.invalid").status_code == 400 and len(sess.calls) == 1


def test_coupang_hmac_signature_format():
    import hashlib
    import hmac

    from adapters.coupang.partners import authorization_header, signed_date

    now = datetime(2026, 11, 18, 3, 4, 5, tzinfo=timezone.utc)
    assert signed_date(now) == "261118T030405Z"
    h = authorization_header("GET", "/v2/providers/affiliate_open_api/apis/openapi/products/search",
                             "keyword=a&limit=5", "AK", "SK", now)
    msg = "261118T030405ZGET/v2/providers/affiliate_open_api/apis/openapi/products/searchkeyword=a&limit=5"
    sig = hmac.new(b"SK", msg.encode(), hashlib.sha256).hexdigest()
    assert h == f"CEA algorithm=HmacSHA256, access-key=AK, signed-date=261118T030405Z, signature={sig}"


def test_unconfigured_adapters_raise_not_configured(env):
    from adapters.coupang.partners import CoupangPartnersAdapter
    from adapters.instagram.graph import InstagramPublisher
    from adapters.naver.datalab import NaverDataLabAdapter
    from adapters.youtube.data_api import YouTubePublisher
    from config.settings import get_settings
    from services.common.http import NotConfiguredError

    s = get_settings()
    with pytest.raises(NotConfiguredError):
        CoupangPartnersAdapter(s).search_products("x")
    with pytest.raises(NotConfiguredError):
        NaverDataLabAdapter(s).shopping_keyword_trends("1", "a", ["b"], None, None)
    assert "SCF_PUBLIC_MEDIA_BASE_URL (Meta 가 영상을 가져갈 공개 URL)" in InstagramPublisher(s).missing_requirements()
    assert not YouTubePublisher(s).is_configured()


def test_instagram_flow_separates_accepted_and_verified(env, monkeypatch):
    from adapters.instagram.graph import InstagramPublisher
    from config.settings import get_settings, reload_settings
    from services.common.http import HttpClient, HttpConfig

    monkeypatch.setenv("INSTAGRAM_USER_ID", "123")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("SCF_PUBLIC_MEDIA_BASE_URL", "https://media.example.invalid")
    s = reload_settings()
    sess = SeqSession([Resp(200, {"id": "C1"}), Resp(200, {"status_code": "IN_PROGRESS"}),
                       Resp(200, {"status_code": "FINISHED"}), Resp(200, {"id": "M1"}),
                       Resp(200, {"id": "M1", "permalink": "https://instagram.com/reel/x"})])
    http = HttpClient("instagram", HttpConfig(max_retries=0), session=sess, recorder=None)
    pub = InstagramPublisher(s, http=http, sleep=lambda x: None)
    res = pub.publish("https://media.example.invalid/C/reel_final.mp4", "[광고] caption", ai_generated=True)
    assert res.status == "api_accepted" and res.media_id == "M1"
    first = sess.calls[0][2]["data"]
    assert first["media_type"] == "REELS" and first["is_ai_generated"] == "true"
    assert pub.verify("M1").status == "published_verified"


def test_youtube_metadata_declares_paid_promotion_and_synthetic():
    from adapters.youtube.data_api import YouTubePublisher

    meta = YouTubePublisher.build_metadata("[광고] t", "d", ["a"], synthetic=True, privacy="private")
    assert meta["paidProductPlacementDetails"]["hasPaidProductPlacement"] is True
    assert meta["status"]["containsSyntheticMedia"] is True and meta["status"]["selfDeclaredMadeForKids"] is False


def test_tts_none_and_user_file(tmp_path):
    from adapters.tts.providers import get_narration

    assert get_narration("none", tmp_path).path is None
    (tmp_path / "narration.wav").write_bytes(b"RIFF")
    r = get_narration("user_file", tmp_path)
    assert r.path.name == "narration.wav" and r.ai_voice is False
