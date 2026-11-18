"""랜딩·관리자 화면 (Flask test client)."""
from sqlalchemy import select

from tests.conftest import admin_login, register_verified_link

CID = "C20261118-01"


def _approve():
    from app.models import Content
    from services.common.db import session_scope
    from services.social_publishers.review import approve

    with session_scope() as s:
        approve(s, s.get(Content, CID), "tester")


def test_unapproved_product_not_public(app_client):
    assert app_client.get("/p/demo-001").status_code == 404
    assert app_client.get(f"/media/{CID}/reel_final.mp4").status_code == 404
    assert "아직 공개된 추천이 없습니다" in app_client.get("/").get_data(as_text=True)


def test_landing_shows_product_info_after_approval(app_client):
    _approve()
    html = app_client.get(f"/p/demo-001?c={CID}&src=ig").get_data(as_text=True)
    for text in ["책상 하단 케이블 정리 트레이", "19,900원", "확인 기준", "좋은 점", "아쉬운 점", "이런 분께 맞아요",
                 "구매 전 꼭 확인하세요", "확인된 사양", "최대 하중", "광고", "쿠팡 파트너스", "DEMO 데이터",
                 "제휴 링크 등록 대기", f"/media/{CID}/reel_final.mp4"]:
        assert text in html, text
    assert 'http-equiv="refresh"' not in html and "location.href" not in html  # 자동 이동 없음
    assert app_client.get(f"/media/{CID}/reel_final.mp4").status_code == 200
    assert app_client.get(f"/media/{CID}/script.json").status_code == 404     # 공개 목록 밖


def test_buy_link_is_explicit_and_sponsored(app_client):
    _approve()
    register_verified_link()
    html = app_client.get("/p/demo-001").get_data(as_text=True)
    assert 'href="https://link.coupang.com/a/TESTONLY1"' in html
    assert 'rel="sponsored nofollow noopener"' in html and 'target="_blank"' in html
    r = app_client.get("/p/demo-001")
    assert r.status_code == 200 and "Location" not in r.headers


def test_stale_price_hidden(app_client):
    from datetime import timedelta

    from app.models import Product
    from services.common.db import session_scope
    from services.common.timeutil import now_utc

    _approve()
    with session_scope() as s:
        s.get(Product, "DEMO-001").price_checked_at = now_utc() - timedelta(hours=40)
    html = app_client.get("/p/demo-001").get_data(as_text=True)
    assert "19,900원" not in html and "표시하지 않습니다" in html


def test_event_endpoint_stores_no_personal_data(app_client):
    from app.models import SiteEvent
    from services.common.db import session_scope

    r = app_client.post("/api/event", json={"type": "link_click", "product_id": "DEMO-001", "content_id": CID,
                                            "src": "ig", "link_id": "1"},
                        headers={"Referer": "https://www.instagram.com/some/path?x=1", "User-Agent": "UA-SECRET"},
                        environ_base={"REMOTE_ADDR": "203.0.113.9"})
    assert r.status_code == 204
    assert app_client.post("/api/event", json={"type": "evil"}).status_code == 400
    with session_scope() as s:
        ev = s.scalars(select(SiteEvent)).one()
        cols = {c.name for c in SiteEvent.__table__.columns}
        assert not cols & {"ip", "user_agent", "cookie", "session_id"}
        assert ev.ref_domain == "www.instagram.com"
        assert "203.0.113.9" not in str(ev.__dict__) and "UA-SECRET" not in str(ev.__dict__)


def test_security_headers(app_client):
    r = app_client.get("/")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"


def test_admin_requires_login_and_csrf(app_client):
    assert app_client.get("/admin/").status_code == 302
    assert app_client.post("/admin/login", data={"password": "pw-test-123"}).status_code == 400  # CSRF 없음
    token = admin_login(app_client)
    for path in ["/admin/", "/admin/candidates?date=2026-11-18", "/admin/contents", f"/admin/contents/{CID}",
                 "/admin/products/DEMO-001", "/admin/publications", "/admin/analytics", "/admin/finance", "/admin/logs"]:
        r = app_client.get(path)
        assert r.status_code == 200, path
    r = app_client.post(f"/admin/contents/{CID}/action", data={"action": "approve"})
    assert r.status_code == 400  # 토큰 없음
    r = app_client.post(f"/admin/contents/{CID}/action", data={"action": "approve", "csrf_token": token})
    assert r.status_code == 302
    from app.models import AuditLog, Content
    from services.common.db import session_scope

    with session_scope() as s:
        assert s.get(Content, CID).status == "approved"
        assert s.scalars(select(AuditLog).where(AuditLog.action == "approve")).first().actor == "tester"


def test_admin_publish_without_credentials_is_pending(app_client):
    token = admin_login(app_client)
    _approve()
    register_verified_link()
    r = app_client.post(f"/admin/contents/{CID}/action",
                        data={"action": "publish", "platform": "youtube", "csrf_token": token}, follow_redirects=True)
    assert "pending_credentials" in r.get_data(as_text=True)


def test_admin_edit_copy_reruns_fact_check(app_client):
    from app.models import Content
    from services.common.db import session_scope

    token = admin_login(app_client)
    app_client.post(f"/admin/contents/{CID}/action",
                    data={"action": "edit", "scene_s4": "최대 하중 50kg 무조건 튼튼", "csrf_token": token})
    with session_scope() as s:
        c = s.get(Content, CID)
        assert c.status == "blocked" and c.fact_check["passed"] is False


def test_api_jobs_requires_token(app_client):
    assert app_client.post("/api/jobs/run", json={"stage": "qa_check"}).status_code == 401
    r = app_client.post("/api/jobs/run", json={"stage": "qa_check", "date": "2026-11-18"},
                        headers={"X-SCF-Token": "tok-test-123456"})
    assert r.status_code == 200 and r.get_json()["status"] == "already_succeeded"
    assert app_client.get("/api/health").get_json()["ok"] is True


def test_delete_product_removes_everything(app_client):
    from app.models import Content, Product, SiteEvent
    from services.common.db import session_scope
    from services.social_publishers.review import delete_product

    with session_scope() as s:
        s.add(SiteEvent(event_type="page_view", product_id="DEMO-001", content_id=CID))
    with session_scope() as s:
        out_dir = s.get(Content, CID).output_dir
        res = delete_product(s, "DEMO-001", "tester")
    assert res["deleted_contents"] == 1
    import os

    assert not os.path.exists(out_dir)
    with session_scope() as s:
        assert s.get(Product, "DEMO-001") is None and s.get(Content, CID) is None
        assert not list(s.scalars(select(SiteEvent).where(SiteEvent.product_id == "DEMO-001")))
