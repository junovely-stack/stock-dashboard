"""네이버 데이터랩 쇼핑인사이트 / 검색어트렌드 (공식 API).

확인 사항 (docs/API_ACCESS_MATRIX.md, 2026-11-18 조사):
- 반환값 ratio 는 '구간 내 최댓값=100' 상대지수. 검색량·판매량이 아니다.
- /category/keywords 는 요청당 키워드 그룹 최대 5개, 일 1,000회.
- 네이버 개발자센터의 신규 신청은 2026-07-30 종료 → NCP NAVER API HUB 로 이관.
  기존 이용자는 2027-06-30 까지 개발자센터 키 사용 가능.
  → NAVER_API_MODE=developers(기존 키) | apihub(NCP 키). API HUB 의 정확한 경로는
    콘솔에서 확인한 값을 NAVER_APIHUB_BASE_URL 로 넣는다(추측하지 않음).

요청 묶음마다 상대지수가 다시 100으로 정규화되므로, 각 묶음에 같은 기준(anchor) 키워드를
넣고 기준 평균 대비 비율로 다시 맞춘다 → 같은 카테고리 안에서는 묶음 간 비교가 가능해진다.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from adapters.base import TrendRecord
from app.models import Confidence
from config.settings import Settings
from services.common.http import HttpClient, HttpConfig, NotConfiguredError
from services.common.logging_utils import redact_obj

LEGACY_BASE = "https://openapi.naver.com/v1/datalab"
DOC_URL = "https://developers.naver.com/docs/serviceapi/datalab/shopping/shopping.md"
MAX_GROUPS = 5


def rescale_by_anchor(results: list[dict], anchor: str) -> dict[str, list[dict]]:
    """DataLab results[] → {keyword: series}, anchor 평균을 50 으로 맞춘 값."""
    by_name = {r["title"]: r.get("data", []) for r in results}
    anchor_series = by_name.get(anchor) or []
    anchor_mean = sum(p["ratio"] for p in anchor_series) / len(anchor_series) if anchor_series else 0.0
    out: dict[str, list[dict]] = {}
    for name, series in by_name.items():
        if name == anchor:
            continue
        if anchor_mean > 0:
            out[name] = [{"period": p["period"], "ratio": round(p["ratio"] / anchor_mean * 50, 3)} for p in series]
        else:
            out[name] = [{"period": p["period"], "ratio": p["ratio"]} for p in series]
    return out


class NaverDataLabAdapter:
    name = "naver_datalab"

    def __init__(self, settings: Settings, http: HttpClient | None = None):
        self.settings = settings
        self.mode = os.environ.get("NAVER_API_MODE", "developers")
        self.base = LEGACY_BASE if self.mode == "developers" else os.environ.get("NAVER_APIHUB_BASE_URL", "")
        self.http = http or HttpClient("naver", HttpConfig(per_minute=60))

    def is_configured(self) -> bool:
        if self.mode == "developers":
            return bool(self.settings.naver_client_id and self.settings.naver_client_secret)
        return bool(self.base and os.environ.get("NCP_APIGW_API_KEY_ID") and os.environ.get("NCP_APIGW_API_KEY"))

    def _headers(self) -> dict:
        if self.mode == "developers":
            return {
                "X-Naver-Client-Id": self.settings.naver_client_id or "",
                "X-Naver-Client-Secret": self.settings.naver_client_secret or "",
                "Content-Type": "application/json",
            }
        return {
            "X-NCP-APIGW-API-KEY-ID": os.environ.get("NCP_APIGW_API_KEY_ID", ""),
            "X-NCP-APIGW-API-KEY": os.environ.get("NCP_APIGW_API_KEY", ""),
            "Content-Type": "application/json",
        }

    @staticmethod
    def build_keyword_body(category_code: str, anchor: str, keywords: list[str], start: date, end: date,
                           time_unit: str = "date") -> dict:
        names = [anchor] + [k for k in keywords if k != anchor][: MAX_GROUPS - 1]
        return {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "timeUnit": time_unit,
            "category": category_code,
            "keyword": [{"name": n, "param": [n]} for n in names],
        }

    def shopping_keyword_trends(self, category_code: str, anchor: str, keywords: list[str], start: date,
                                end: date) -> dict:
        if not self.is_configured():
            raise NotConfiguredError("네이버 데이터랩 자격증명 없음")
        body = self.build_keyword_body(category_code, anchor, keywords, start, end)
        resp = self.http.post(f"{self.base}/shopping/category/keywords", operation="datalab.shopping.keywords",
                              headers=self._headers(), data=json.dumps(body, ensure_ascii=False).encode("utf-8"))
        resp.raise_for_status()
        return resp.json()

    def collect(self, run_date: date, category_key: str, category_code: str, anchor: str,
                keywords: list[str], raw_dir: Path) -> list[TrendRecord]:
        end = run_date - timedelta(days=1)          # 당일 데이터는 집계 전
        start = end - timedelta(days=34)
        records: list[TrendRecord] = []
        for i in range(0, len(keywords), MAX_GROUPS - 1):
            batch = keywords[i : i + MAX_GROUPS - 1]
            raw = self.shopping_keyword_trends(category_code, anchor, batch, start, end)
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"naver_{category_key}_{i // (MAX_GROUPS - 1)}.json"
            raw_path.write_text(json.dumps(redact_obj(raw), ensure_ascii=False, indent=1), encoding="utf-8")
            for kw, series in rescale_by_anchor(raw.get("results", []), anchor).items():
                records.append(TrendRecord(keyword=kw, category_key=category_key, series=series,
                                           source=self.name, confidence=Confidence.OFFICIAL_API,
                                           source_url=DOC_URL, raw_ref=str(raw_path)))
        return records
