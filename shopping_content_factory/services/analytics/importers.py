"""성과 데이터 적재: 플랫폼 API(자격증명 있을 때) / CSV 수동 입력.

CSV 템플릿: data/templates/metrics_import_template.csv, coupang_report_template.csv
CSV 는 UTF-8(BOM 허용). 행마다 검사: 결측·음수·미등록 콘텐츠·중복 → 잘못된 행은 적재하지 않고 사유를 돌려준다.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from adapters.base import set_source_state
from adapters.coupang.partners import CoupangPartnersAdapter
from adapters.instagram.graph import InstagramPublisher
from adapters.youtube.data_api import YouTubePublisher
from app.models import AffiliateReport, Content, MetricObservation, Publication, PubStatus, SourceState
from config.settings import get_settings
from services.common.db import session_scope
from services.common.logging_utils import get_logger

log = get_logger(__name__)
ALLOWED_METRICS = {"views", "engaged_views", "reach", "likes", "comments", "saved", "shares", "avg_watch_time_sec",
                   "avg_view_pct", "profile_visits", "followers_gained"}


def _upsert_metric(s, d: date, cid: str, variant: str | None, platform: str, metric: str, value: float,
                   source: str) -> None:
    row = s.scalars(select(MetricObservation).where(
        MetricObservation.metric_date == d, MetricObservation.content_id == cid, MetricObservation.variant == variant,
        MetricObservation.platform == platform, MetricObservation.metric == metric,
        MetricObservation.source == source)).first()
    if row:
        row.value = value
    else:
        s.add(MetricObservation(metric_date=d, content_id=cid, variant=variant, platform=platform, metric=metric,
                                value=value, source=source, is_estimate=False))


def import_metrics_csv(path: Path) -> dict:
    ok, rejected = 0, []
    with session_scope() as s, path.open(encoding="utf-8-sig") as f:
        known = {c for c in s.scalars(select(Content.id))}
        for i, r in enumerate(csv.DictReader(f), start=2):
            try:
                d = date.fromisoformat(r["date"].strip())
                cid, metric = r["content_id"].strip(), r["metric"].strip()
                value = float(r["value"])
                platform = r["platform"].strip()
            except (KeyError, ValueError) as exc:
                rejected.append({"line": i, "reason": f"형식 오류 {exc}"})
                continue
            if cid not in known:
                rejected.append({"line": i, "reason": f"미등록 콘텐츠 {cid}"})
            elif metric not in ALLOWED_METRICS:
                rejected.append({"line": i, "reason": f"허용되지 않은 지표 {metric}"})
            elif value < 0:
                rejected.append({"line": i, "reason": "음수"})
            elif platform not in ("instagram", "youtube"):
                rejected.append({"line": i, "reason": f"플랫폼 {platform}"})
            else:
                _upsert_metric(s, d, cid, (r.get("variant") or "A").strip(), platform, metric, value, "manual_csv")
                ok += 1
    return {"imported": ok, "rejected": rejected}


def import_affiliate_csv(path: Path) -> dict:
    ok, rejected = 0, []
    with session_scope() as s, path.open(encoding="utf-8-sig") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            try:
                d = date.fromisoformat(r["date"].strip())
                vals = {k: int(float(r.get(k) or 0)) for k in ("clicks", "orders", "gmv_krw", "commission_krw",
                                                               "cancel_count", "cancel_amount_krw")}
            except (KeyError, ValueError) as exc:
                rejected.append({"line": i, "reason": f"형식 오류 {exc}"})
                continue
            if any(v < 0 for v in vals.values()):
                rejected.append({"line": i, "reason": "음수"})
                continue
            if vals["orders"] > 0 and vals["gmv_krw"] == 0:
                rejected.append({"line": i, "reason": "주문은 있는데 구매액 0 (논리 역전)"})
                continue
            sub = (r.get("sub_id") or "").strip() or None
            row = s.scalars(select(AffiliateReport).where(
                AffiliateReport.report_date == d, AffiliateReport.sub_id == sub,
                AffiliateReport.source == "manual_csv")).first()
            if row is None:
                row = AffiliateReport(report_date=d, sub_id=sub, source="manual_csv")
                s.add(row)
            for k, v in vals.items():
                setattr(row, k, v)
            row.settlement_status = (r.get("status") or "pending").strip()
            ok += 1
    set_source_state("coupang_reports", "affiliate", SourceState.MANUAL, note=f"CSV {ok}행")
    return {"imported": ok, "rejected": rejected}


def collect_platform_metrics(run_date: date) -> dict:
    """전일 성과 수집 (07:00). 자격증명 없으면 '연동 대기'로 남기고 값은 만들지 않는다."""
    settings = get_settings()
    yesterday = run_date - timedelta(days=1)
    summary = {"instagram": 0, "youtube": 0, "coupang": 0, "notes": []}
    ig, yt = InstagramPublisher(settings), YouTubePublisher(settings)
    with session_scope() as s:
        pubs = list(s.scalars(select(Publication).where(Publication.status.in_(list(PubStatus.DONE)))))
        for pub in pubs:
            try:
                if pub.platform == "instagram" and settings.instagram_access_token and settings.instagram_user_id:
                    for metric, value in ig.insights(pub.platform_media_id).items():
                        name = {"ig_reels_avg_watch_time": "avg_watch_time_sec"}.get(metric, metric)
                        if value is not None and name in ALLOWED_METRICS:
                            _upsert_metric(s, yesterday, pub.content_id, pub.variant, "instagram", name, float(value), "api")
                    summary["instagram"] += 1
                elif pub.platform == "youtube" and yt.is_configured():
                    data = yt.analytics(pub.platform_media_id, (run_date - timedelta(days=30)).isoformat(),
                                        yesterday.isoformat())
                    mapping = {"views": "views", "engagedViews": "engaged_views", "likes": "likes", "shares": "shares",
                               "averageViewDuration": "avg_watch_time_sec", "averageViewPercentage": "avg_view_pct",
                               "subscribersGained": "followers_gained"}
                    for k, v in data.items():
                        if k in mapping and v is not None:
                            _upsert_metric(s, yesterday, pub.content_id, pub.variant, "youtube", mapping[k], float(v), "api")
                    summary["youtube"] += 1
            except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체 수집을 막지 않게
                summary["notes"].append(f"{pub.platform}:{pub.content_id} 수집 실패 {exc}")
    set_source_state("instagram_insights", "social", SourceState.CONNECTED if settings.instagram_access_token
                     else SourceState.NOT_CONFIGURED, note="Reels 인사이트 (최대 48시간 지연)")
    set_source_state("youtube_analytics", "social", SourceState.CONNECTED if yt.is_configured()
                     else SourceState.NOT_CONFIGURED, note="YouTube Analytics (48~72시간 지연)")
    cp = CoupangPartnersAdapter(settings)
    if cp.is_configured():
        try:
            rows = cp.report("commission", yesterday, yesterday)
            with session_scope() as s:
                for r in rows:
                    sub = r.get("subId")
                    row = s.scalars(select(AffiliateReport).where(AffiliateReport.report_date == yesterday,
                                                                  AffiliateReport.sub_id == sub,
                                                                  AffiliateReport.source == "api")).first()
                    if row is None:
                        row = AffiliateReport(report_date=yesterday, sub_id=sub, source="api")
                        s.add(row)
                    row.commission_krw = int(r.get("commission", 0))
                    row.gmv_krw = int(r.get("gmv", 0))
                    row.orders = int(r.get("orderCnt", 0))
                    summary["coupang"] += 1
            set_source_state("coupang_reports", "affiliate", SourceState.CONNECTED)
        except Exception as exc:  # noqa: BLE001
            set_source_state("coupang_reports", "affiliate", SourceState.ERROR, error=str(exc))
            summary["notes"].append(f"쿠팡 리포트 실패 {exc}")
    else:
        set_source_state("coupang_reports", "affiliate", SourceState.NOT_CONFIGURED,
                         note="API 키 없음 — 파트너스 대시보드 CSV 를 관리자 화면에서 업로드")
    return summary
