"""어댑터 공통 타입.

모든 외부 연동은 '실제(공식 API)'와 'mock/수동' 구현을 갖고, 운영 화면에 어느 쪽으로
동작 중인지 data_sources 테이블로 노출한다. mock 결과는 confidence="mock" 으로 표시되어
실데이터와 섞이지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models import DataSource, SourceState
from services.common.db import session_scope
from services.common.logging_utils import redact
from services.common.timeutil import now_utc


@dataclass
class TrendRecord:
    keyword: str
    category_key: str | None
    series: list[dict]  # [{"period": "YYYY-MM-DD", "ratio": float}]
    source: str
    confidence: str
    source_url: str | None = None
    raw_ref: str | None = None


@dataclass
class ProductCandidate:
    id: str
    name: str
    category_key: str
    keywords: list[str]
    price: int | None
    data: dict[str, Any] = field(default_factory=dict)  # 원본 필드 전체
    source_type: str = "mock"
    source_url: str | None = None
    is_demo: bool = False


@dataclass
class PublishResult:
    status: str
    media_id: str | None = None
    url: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def set_source_state(name: str, kind: str, state: str, note: str | None = None, error: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(DataSource, name)
        if row is None:
            row = DataSource(name=name, kind=kind)
            s.add(row)
        row.state = state
        row.note = note
        if state in (SourceState.CONNECTED, SourceState.MOCK, SourceState.MANUAL):
            row.last_success_at = now_utc()
            row.last_error = None if state == SourceState.CONNECTED else row.last_error
        if error:
            row.last_error = redact(error)[:2000]


def date_str(d: date) -> str:
    return d.isoformat()
