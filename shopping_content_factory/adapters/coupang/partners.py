"""쿠팡파트너스 Open API 어댑터 (공식 API, 승인된 계정만).

- 인증: HMAC-SHA256 서명 (Authorization: CEA algorithm=HmacSHA256, access-key=…, signed-date=…, signature=…)
- API 키는 파트너스 계정이 API 사용 조건을 충족해야 발급된다 → 키가 없으면 NotConfiguredError,
  상위 로직은 '수동 링크 등록' 경로로 간다. 임의 URL 을 만들지 않는다.
- 경로·호출 한도는 운영 전 공식 가이드로 재확인 (docs/API_ACCESS_MATRIX.md).

주의: 제휴 링크의 '정상 여부'를 확인한다고 링크를 자동 요청하지 않는다. 자동 요청은 클릭으로
집계될 수 있어 부정 클릭 소지가 있다 → 형식 검증 + 사람 확인만 한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from config.settings import Settings
from services.common.http import HttpClient, HttpConfig, NotConfiguredError

DOMAIN = "https://api-gateway.coupang.com"
BASE_PATH = "/v2/providers/affiliate_open_api/apis/openapi"
PATHS = {
    "search": f"{BASE_PATH}/products/search",
    "deeplink": f"{BASE_PATH}/v1/deeplink",
    "report_clicks": f"{BASE_PATH}/v1/reports/clicks",
    "report_orders": f"{BASE_PATH}/v1/reports/orders",
    "report_cancels": f"{BASE_PATH}/v1/reports/cancels",
    "report_commission": f"{BASE_PATH}/v1/reports/commission",
}


def signed_date(now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.strftime("%y%m%dT%H%M%SZ")


def authorization_header(method: str, path: str, query: str, access_key: str, secret_key: str,
                         now: datetime | None = None) -> str:
    sd = signed_date(now)
    message = f"{sd}{method.upper()}{path}{query}"
    signature = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={sd}, signature={signature}"


class CoupangPartnersAdapter:
    name = "coupang_partners"

    def __init__(self, settings: Settings, http: HttpClient | None = None):
        self.settings = settings
        self.http = http or HttpClient("coupang", HttpConfig(per_minute=30))

    def is_configured(self) -> bool:
        return bool(self.settings.coupang_access_key and self.settings.coupang_secret_key)

    def _call(self, method: str, key: str, params: dict | None = None, body: dict | None = None,
              operation: str = "") -> dict:
        if not self.is_configured():
            raise NotConfiguredError("쿠팡파트너스 API 키 없음 — 수동 링크 등록을 사용하세요")
        path = PATHS[key]
        query = urlencode(params or {})
        auth = authorization_header(method, path, query, self.settings.coupang_access_key or "",
                                    self.settings.coupang_secret_key or "")
        url = f"{DOMAIN}{path}" + (f"?{query}" if query else "")
        headers = {"Authorization": auth, "Content-Type": "application/json;charset=UTF-8"}
        resp = self.http.request(method, url, operation=operation or f"coupang.{key}", headers=headers,
                                 data=json.dumps(body).encode("utf-8") if body is not None else None)
        resp.raise_for_status()
        payload = resp.json()
        if str(payload.get("rCode", "0")) not in {"0", "200"}:
            raise RuntimeError(f"쿠팡 API 오류 rCode={payload.get('rCode')} {payload.get('rMessage')}")
        return payload

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        params = {"keyword": keyword, "limit": limit}
        if self.settings.coupang_sub_id:
            params["subId"] = self.settings.coupang_sub_id
        payload = self._call("GET", "search", params=params, operation="coupang.search")
        data = payload.get("data") or {}
        return data.get("productData", []) if isinstance(data, dict) else []

    def create_deeplinks(self, urls: list[str], sub_id: str | None = None) -> list[dict]:
        body: dict = {"coupangUrls": urls}
        if sub_id or self.settings.coupang_sub_id:
            body["subId"] = sub_id or self.settings.coupang_sub_id
        payload = self._call("POST", "deeplink", body=body, operation="coupang.deeplink")
        return payload.get("data", [])

    def report(self, kind: str, start: date, end: date, sub_id: str | None = None) -> list[dict]:
        params = {"startDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d")}
        if sub_id:
            params["subId"] = sub_id
        payload = self._call("GET", f"report_{kind}", params=params, operation=f"coupang.report.{kind}")
        return payload.get("data", [])


def map_search_item(item: dict, keyword: str, category_key: str) -> dict:
    """검색 API 응답 1건 → 후보 상품 필드. 사양·장단점은 API 에 없으므로 '미확인'으로 남는다."""
    return {
        "id": f"CP-{item.get('productId')}",
        "external_id": str(item.get("productId")),
        "name": item.get("productName"),
        "category_key": category_key,
        "price": item.get("productPrice"),
        "keywords": [keyword],
        "image": {"url": item.get("productImage"), "source": "coupang_api",
                  "rights": "partner_display_only"},
        "source_url": item.get("productUrl"),
        "affiliate_url": item.get("productUrl"),
        "signals": {"is_rocket": item.get("isRocket"), "free_shipping": item.get("isFreeShipping"),
                    "category_name": item.get("categoryName")},
        "verified_specs": [],
        "stock_status": "unknown",
    }


def _now_ms() -> int:
    return int(time.time() * 1000)
