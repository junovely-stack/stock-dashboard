"""트렌드 수집 → 정규화 → 중복 제거 → 급상승 탐지 → 화제성 키워드 제외 → 저장.

저장 항목: 수집 시각, 출처 URL, 원본 응답 파일(raw_ref), 신뢰 수준(confidence).
상대지수(ratio)는 검색량·판매량이 아니다. 화면·보고서에도 '상대지수'로만 표기한다.
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select

from adapters.base import TrendRecord, set_source_state
from adapters.naver.datalab import NaverDataLabAdapter
from adapters.naver.mock import MockTrendAdapter
from app.models import Confidence, SourceState, TrendSnapshot
from config.settings import get_settings, load_policy
from services.common.db import session_scope
from services.common.http import NotConfiguredError
from services.common.logging_utils import get_logger

log = get_logger(__name__)
CONF_RANK = {Confidence.OFFICIAL_API: 3, Confidence.MANUAL: 2, Confidence.MOCK: 1}


def normalize_keyword(kw: str) -> str:
    return re.sub(r"\s+", " ", kw.strip()).lower()


def classify_intent(keyword: str) -> str:
    rules = load_policy("scoring")["intent"]
    if any(m in keyword for m in rules["buzz_markers"]):
        return "buzz"
    if any(m in keyword for m in rules["purchase_markers"]):
        return "purchase"
    if any(m in keyword for m in rules["problem_markers"]):
        return "problem"
    return "problem"  # 상품군 일반명은 '문제 탐색' 단계로 본다 (구매 의도 가중치 0.7)


def series_features(series: list[dict]) -> dict:
    values = [float(p["ratio"]) for p in series]
    if len(values) < 14:
        return {"latest": None, "growth_7d": None, "growth_30d": None}
    last7 = sum(values[-7:]) / 7
    prior = values[-28:-7] if len(values) >= 28 else values[:-7]
    prior_mean = sum(prior) / len(prior) if prior else 0
    first7 = sum(values[:7]) / 7
    return {
        "latest": round(last7, 3),
        "growth_7d": round(last7 / prior_mean - 1, 4) if prior_mean > 0 else None,
        "growth_30d": round(last7 / first7 - 1, 4) if first7 > 0 else None,
    }


def _manual_records(path: Path) -> list[TrendRecord]:
    """data/manual/trends.csv (keyword,category,period,ratio) — 공식 API 가 없는 소스를 사람이 옮겨 적은 값."""
    if not path.exists():
        return []
    rows: dict[tuple[str, str], list[dict]] = {}
    with path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.setdefault((r["keyword"], r.get("category") or ""), []).append(
                {"period": r["period"], "ratio": float(r["ratio"])})
    return [TrendRecord(keyword=k, category_key=c or None, series=sorted(v, key=lambda x: x["period"]),
                        source="manual_csv", confidence=Confidence.MANUAL, source_url=f"file://{path}",
                        raw_ref=str(path)) for (k, c), v in rows.items()]


def gather_records(run_date: date) -> tuple[list[TrendRecord], list[str]]:
    settings = get_settings()
    raw_dir = settings.output_dir / "raw" / run_date.isoformat()
    notes: list[str] = []
    records: list[TrendRecord] = []
    if settings.trend_provider == "naver":
        adapter = NaverDataLabAdapter(settings)
        if not adapter.is_configured():
            set_source_state("naver_datalab", "trend", SourceState.NOT_CONFIGURED,
                             note="NAVER 자격증명 없음 (신규 신청은 NCP API HUB)")
            raise NotConfiguredError("SCF_TREND_PROVIDER=naver 인데 자격증명이 없습니다")
        try:
            for key, cat in load_policy("categories").items():
                records += adapter.collect(run_date, key, cat["naver_category"], cat["anchor"],
                                           cat["seed_keywords"], raw_dir)
            set_source_state("naver_datalab", "trend", SourceState.CONNECTED, note=f"{len(records)}개 키워드")
        except Exception as exc:
            set_source_state("naver_datalab", "trend", SourceState.ERROR, error=str(exc))
            raise
    else:
        adapter = MockTrendAdapter(settings.data_dir / "mock" / "trend_keywords.json")
        records += adapter.collect(run_date, raw_dir)
        set_source_state("naver_datalab", "trend", SourceState.MOCK, note="모의 데이터 사용 중 (실데이터 아님)")
        notes.append("트렌드: MOCK")
    manual = _manual_records(settings.data_dir / "manual" / "trends.csv")
    if manual:
        set_source_state("manual_trends", "trend", SourceState.MANUAL, note=f"{len(manual)}개 키워드 CSV")
        records += manual
    set_source_state("google_trends", "trend", SourceState.NOT_CONFIGURED,
                     note="공식 API 알파(허용 계정만) — 미연동, 필요 시 manual CSV")
    return records, notes


def collect_trends(run_date: date) -> dict:
    records, notes = gather_records(run_date)
    surge_threshold = load_policy("scoring")["rules"]["surge_threshold"]
    # 중복 제거: 같은 키워드는 신뢰 수준이 높은 출처 하나만
    best: dict[str, TrendRecord] = {}
    for r in records:
        k = normalize_keyword(r.keyword)
        if k not in best or CONF_RANK.get(r.confidence, 0) > CONF_RANK.get(best[k].confidence, 0):
            best[k] = r
    saved = excluded = surging = 0
    with session_scope() as s:
        s.execute(delete(TrendSnapshot).where(TrendSnapshot.run_date == run_date))
        for r in best.values():
            feats = series_features(r.series)
            intent = classify_intent(r.keyword)
            reason = "단순 화제성 키워드(구매 의도 낮음)" if intent == "buzz" else None
            is_surging = bool(feats["growth_7d"] is not None and feats["growth_7d"] >= surge_threshold)
            s.add(TrendSnapshot(
                run_date=run_date, source=r.source, keyword=r.keyword, category_key=r.category_key,
                intent=intent, period_start=date.fromisoformat(r.series[0]["period"]) if r.series else None,
                period_end=date.fromisoformat(r.series[-1]["period"]) if r.series else None,
                series=r.series, latest_ratio=feats["latest"], growth_7d=feats["growth_7d"],
                growth_30d=feats["growth_30d"], is_surging=is_surging and not reason, excluded_reason=reason,
                source_url=r.source_url, raw_ref=r.raw_ref, confidence=r.confidence))
            saved += 1
            excluded += 1 if reason else 0
            surging += 1 if (is_surging and not reason) else 0
    summary = {"keywords": saved, "duplicates_removed": len(records) - len(best), "excluded_buzz": excluded,
               "surging": surging, "notes": notes}
    log.info("트렌드 수집 %s: %s", run_date, summary)
    return summary


def active_keywords(run_date: date) -> list[TrendSnapshot]:
    with session_scope() as s:
        return list(s.scalars(select(TrendSnapshot).where(TrendSnapshot.run_date == run_date,
                                                          TrendSnapshot.excluded_reason.is_(None))))
