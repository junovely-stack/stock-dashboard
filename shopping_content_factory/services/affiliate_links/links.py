"""제휴 링크 등록·검증·콘텐츠 매핑, 광고 고지 문구.

- 링크를 만들 수 없으면 임의 URL 을 만들지 않는다 → 수동 등록(사람이 파트너스 화면에서 생성한 링크).
- 정상 여부 확인을 위해 링크를 자동으로 열지 않는다(클릭 집계 오염·부정 클릭 소지).
  형식 검증 후, 사람이 직접 열어 상품 페이지가 맞는지 확인하면 VERIFIED.
- 자동 리디렉션·숨은 iframe·쿠키 삽입은 구현하지 않는다. 랜딩의 버튼은 쿠팡 링크로 가는 일반 <a> 태그.
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.models import AffiliateLink, AuditLog, LinkStatus, Product
from config.settings import load_policy
from services.common.timeutil import now_utc

ALLOWED_HOSTS = {"link.coupang.com", "coupa.ng"}


def validate_affiliate_url(url: str) -> tuple[bool, str]:
    try:
        u = urlparse(url.strip())
    except ValueError:
        return False, "URL 파싱 실패"
    if u.scheme != "https":
        return False, "https 링크가 아님"
    if u.hostname not in ALLOWED_HOSTS:
        return False, f"쿠팡파트너스 링크 도메인이 아님 ({u.hostname}) — 허용: {', '.join(sorted(ALLOWED_HOSTS))}"
    if len(u.path.strip("/")) < 3:
        return False, "링크 경로가 비어 있음"
    if any(ch.isspace() for ch in url.strip()):
        return False, "공백 포함"
    return True, "형식 정상 (사람 확인 전)"


def register_manual_link(session, product: Product, url: str, actor: str, sub_id: str | None = None,
                         content_id: str | None = None) -> AffiliateLink:
    ok, why = validate_affiliate_url(url)
    link = AffiliateLink(product_id=product.id, program="coupang_partners", url=url.strip(), sub_id=sub_id,
                         content_id=content_id, source="manual",
                         status=LinkStatus.REGISTERED if ok else LinkStatus.INVALID, note=why)
    session.add(link)
    product.affiliate_link_status = link.status if ok or not product.links else product.affiliate_link_status
    session.add(AuditLog(actor=actor, action="link_register", target_type="product", target_id=product.id,
                         detail={"ok": ok, "note": why, "sub_id": sub_id}))
    return link


def confirm_link(session, link: AffiliateLink, actor: str) -> None:
    """사람이 직접 링크를 열어 해당 상품 페이지로 가는 것을 확인했을 때만 호출."""
    if link.status == LinkStatus.INVALID:
        raise ValueError("형식이 잘못된 링크는 확인 처리할 수 없습니다")
    link.status = LinkStatus.VERIFIED
    link.verified_at = now_utc()
    link.verified_by = actor
    link.product.affiliate_link_status = LinkStatus.VERIFIED
    session.add(AuditLog(actor=actor, action="link_verify", target_type="affiliate_link", target_id=str(link.id)))


def best_link(product: Product) -> AffiliateLink | None:
    verified = [l for l in product.links if l.status == LinkStatus.VERIFIED]
    return sorted(verified, key=lambda l: l.verified_at or l.created_at)[-1] if verified else None


def disclosure() -> dict:
    return dict(load_policy("compliance")["disclosure"])


def check_disclosure_text(text: str) -> list[str]:
    """표시 문구에 조건부 표현·외국어 약어가 들어갔는지."""
    forbidden = load_policy("compliance")["disclosure"]["disclosure_forbidden"]
    issues = []
    for word in forbidden:
        if word.isascii():
            import re

            if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text):
                issues.append(f"광고 표시에 외국어 약어 '{word}' 사용 — 한글 '광고'로 표기")
        elif word in text:
            issues.append(f"광고 표시에 조건부 표현 '{word}' — '제공받습니다'처럼 확정형으로")
    return issues
