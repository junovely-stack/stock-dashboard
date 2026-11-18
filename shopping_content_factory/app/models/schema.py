"""DB 스키마 (SQLAlchemy 2.0). SQLite(MVP) / PostgreSQL 공용.

테이블 구분
- 수집: data_sources, trend_snapshots
- 상품: products, product_images, affiliate_links, price_history
- 선정: product_scores, selection_logs, psychology_profiles
- 콘텐츠: contents, publications
- 성과: site_events, metric_observations, affiliate_reports
- 운영: job_runs, api_usage, cost_entries, audit_logs
docs/DB_SCHEMA.md 에 컬럼 설명이 있다.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from services.common.timeutil import now_utc


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- 상태 상수
class SourceState:
    CONNECTED = "connected"      # 공식 API 정상 응답
    MOCK = "mock"                # 모의 데이터 (실데이터 아님)
    MANUAL = "manual"            # CSV 수동 입력
    NOT_CONFIGURED = "not_configured"  # 자격증명 없음
    ERROR = "error"


class Confidence:
    OFFICIAL_API = "official_api"
    MANUAL = "manual"
    MOCK = "mock"
    ESTIMATE = "estimate"


class ImageRights:
    OWN = "own"                          # 직접 촬영·제작
    LICENSED = "licensed"                # 라이선스 확보(증빙 필요)
    AI_GENERATED = "ai_generated"        # 생성형 도구 결과물 (도구 약관 범위 내, 상품 아닌 배경·장면만)
    PARTNER_DISPLAY = "partner_display_only"  # 제휴 프로그램 제공 이미지: 원본 그대로 표시만
    REFERENCE_ONLY = "reference_only"    # 참고용(검색 API 등) — 게시 불가
    UNKNOWN = "unknown"
    DENIED = "denied"

    VIDEO_OK = {OWN, LICENSED, AI_GENERATED}
    LANDING_OK = {OWN, LICENSED, AI_GENERATED, PARTNER_DISPLAY}


class LinkStatus:
    MISSING = "missing"
    REGISTERED = "registered"   # 수동 등록, 사람 확인 전
    VERIFIED = "verified"       # 형식 검증 + 사람 확인(또는 공식 API 생성)
    INVALID = "invalid"


class StockStatus:
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"
    UNKNOWN = "unknown"


class ContentStatus:
    GENERATED = "generated"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PubStatus:
    QUEUED = "queued"
    BLOCKED = "blocked"                      # 게시 게이트 실패
    PENDING_CREDENTIALS = "pending_credentials"  # 권한 없음 → 게시하지 않음
    WAITING_MANUAL = "waiting_manual"        # AUTO_PUBLISH=false → 사람이 게시 버튼 눌러야 함
    IN_PROGRESS = "in_progress"
    API_ACCEPTED = "api_accepted"            # 플랫폼 API 가 ID 를 돌려줌 (게시 완료 아님)
    PUBLISHED_VERIFIED = "published_verified"  # 플랫폼 조회로 공개 게시 확인
    FAILED = "failed"
    UNKNOWN = "unknown"                      # 진행 중 끊김 → 중복 방지 위해 자동 재시도 안 함

    RETRYABLE = {QUEUED, BLOCKED, PENDING_CREDENTIALS, WAITING_MANUAL, FAILED}
    DONE = {API_ACCEPTED, PUBLISHED_VERIFIED}


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"              # 정책상 진행 불가 (예: 기준 미달, 비용 상한)
    SKIPPED_UPSTREAM = "skipped_upstream"


# ---------------------------------------------------------------- 수집
class DataSource(Base):
    __tablename__ = "data_sources"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # trend / product / affiliate / social / llm
    state: Mapped[str] = mapped_column(String(32), default=SourceState.NOT_CONFIGURED)
    note: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class TrendSnapshot(Base):
    __tablename__ = "trend_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(64))
    keyword: Mapped[str] = mapped_column(String(128))
    category_key: Mapped[str | None] = mapped_column(String(64))
    intent: Mapped[str | None] = mapped_column(String(16))  # purchase / problem / buzz
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    series: Mapped[list | None] = mapped_column(JSON)       # [{"period": "2026-11-01", "ratio": 42.1}]
    latest_ratio: Mapped[float | None] = mapped_column(Float)  # 상대지수 (검색량·판매량 아님)
    growth_7d: Mapped[float | None] = mapped_column(Float)
    growth_30d: Mapped[float | None] = mapped_column(Float)
    is_surging: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(String(128))
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_ref: Mapped[str | None] = mapped_column(Text)        # 원본 응답 파일 경로(마스킹 후 저장)
    confidence: Mapped[str] = mapped_column(String(16), default=Confidence.MOCK)
    __table_args__ = (UniqueConstraint("run_date", "source", "keyword", name="uq_trend_day_kw"),)


# ---------------------------------------------------------------- 상품
class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(64))  # 쿠팡 productId 등
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    category_key: Mapped[str] = mapped_column(String(64), index=True)
    seller: Mapped[str | None] = mapped_column(String(128))
    mall: Mapped[str | None] = mapped_column(String(64))
    brand: Mapped[str | None] = mapped_column(String(128))
    base_price: Mapped[int | None] = mapped_column(Integer)
    price_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    stock_status: Mapped[str] = mapped_column(String(16), default=StockStatus.UNKNOWN)
    stock_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    description: Mapped[str | None] = mapped_column(Text)
    verified_specs: Mapped[list] = mapped_column(JSON, default=list)  # [{"key","value","unit","source","verified_at"}]
    pros: Mapped[list] = mapped_column(JSON, default=list)
    cons: Mapped[list] = mapped_column(JSON, default=list)
    recommended_for: Mapped[list] = mapped_column(JSON, default=list)
    not_recommended_for: Mapped[list] = mapped_column(JSON, default=list)
    cautions: Mapped[list] = mapped_column(JSON, default=list)
    usage_steps: Mapped[list] = mapped_column(JSON, default=list)
    problem: Mapped[dict] = mapped_column(JSON, default=dict)      # 고객 문제 리서치 메모(가설)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)      # 리뷰 신호·시각화 태그·위험 플래그 등
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    source_type: Mapped[str] = mapped_column(String(32), default="mock")  # mock / coupang_api / manual
    source_url: Mapped[str | None] = mapped_column(Text)
    commission_rate: Mapped[float | None] = mapped_column(Float)  # 실효 수수료율(가정 또는 확인값)
    commission_rate_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    image_rights_status: Mapped[str] = mapped_column(String(32), default=ImageRights.UNKNOWN)
    affiliate_link_status: Mapped[str] = mapped_column(String(16), default=LinkStatus.MISSING)
    total_score: Mapped[float | None] = mapped_column(Float)
    selection_reason: Mapped[str | None] = mapped_column(Text)
    expected_revenue: Mapped[dict | None] = mapped_column(JSON)
    content_status: Mapped[str | None] = mapped_column(String(32))
    facts_hash: Mapped[str | None] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    images: Mapped[list["ProductImage"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    links: Mapped[list["AffiliateLink"]] = relationship(back_populates="product", cascade="all, delete-orphan")

    def spec_value(self, key: str) -> str | None:
        for s in self.verified_specs or []:
            if s.get("key") == key:
                return f"{s.get('value')}{s.get('unit') or ''}"
        return None


class ProductImage(Base):
    __tablename__ = "product_images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    path: Mapped[str | None] = mapped_column(Text)          # 로컬 파일
    url: Mapped[str | None] = mapped_column(Text)           # 원 출처 URL
    role: Mapped[str] = mapped_column(String(32), default="original")
    source: Mapped[str] = mapped_column(String(64))        # demo_illustration / own_photo / coupang_api / ...
    rights_status: Mapped[str] = mapped_column(String(32), default=ImageRights.UNKNOWN)
    rights_evidence: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    product: Mapped[Product] = relationship(back_populates="images")


class AffiliateLink(Base):
    __tablename__ = "affiliate_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    program: Mapped[str] = mapped_column(String(32), default="coupang_partners")
    url: Mapped[str] = mapped_column(Text)
    sub_id: Mapped[str | None] = mapped_column(String(64))
    content_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=LinkStatus.REGISTERED)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual / api
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[Product] = relationship(back_populates="links")


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    price: Mapped[int] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    source: Mapped[str] = mapped_column(String(32))


# ---------------------------------------------------------------- 선정
class ProductScore(Base):
    __tablename__ = "product_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    total: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict] = mapped_column(JSON)   # criterion → {score, max, evidence, conservative}
    filter_result: Mapped[str] = mapped_column(String(16))  # pass / hold / exclude
    filter_reasons: Mapped[list] = mapped_column(JSON, default=list)
    penalties: Mapped[list] = mapped_column(JSON, default=list)
    rank: Mapped[int | None] = mapped_column(Integer)
    selection: Mapped[str | None] = mapped_column(String(16))  # top5 / final
    selection_reason: Mapped[str | None] = mapped_column(Text)
    expected_revenue: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    __table_args__ = (UniqueConstraint("run_date", "product_id", name="uq_score_day_product"),)


class SelectionLog(Base):
    __tablename__ = "selection_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    step: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class PsychologyProfile(Base):
    __tablename__ = "psychology_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    answers: Mapped[dict] = mapped_column(JSON)
    levers: Mapped[list] = mapped_column(JSON)
    hooks: Mapped[dict] = mapped_column(JSON)
    cautions: Mapped[list] = mapped_column(JSON)
    generator: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    validation: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    __table_args__ = (UniqueConstraint("run_date", "product_id", name="uq_psy_day_product"),)


# ---------------------------------------------------------------- 콘텐츠
class Content(Base):
    __tablename__ = "contents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # C20261118-01
    run_date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default=ContentStatus.GENERATED, index=True)
    title: Mapped[str] = mapped_column(String(256))
    primary_variant: Mapped[str] = mapped_column(String(4), default="A")
    script: Mapped[dict] = mapped_column(JSON)
    facts_hash: Mapped[str] = mapped_column(String(64))
    caption: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    landing_path: Mapped[str | None] = mapped_column(String(256))
    output_dir: Mapped[str | None] = mapped_column(Text)
    assets: Mapped[dict] = mapped_column(JSON, default=dict)   # 생성 파일 경로·권리
    fact_check: Mapped[dict | None] = mapped_column(JSON)
    qa_result: Mapped[dict | None] = mapped_column(JSON)
    block_reasons: Mapped[list] = mapped_column(JSON, default=list)
    cost_estimate_krw: Mapped[float | None] = mapped_column(Float)
    ai_generated_media: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_notes: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
    product: Mapped[Product] = relationship()


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), index=True)
    variant: Mapped[str] = mapped_column(String(4), default="A")
    platform: Mapped[str] = mapped_column(String(16))  # instagram / youtube
    status: Mapped[str] = mapped_column(String(32), default=PubStatus.QUEUED)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    platform_media_id: Mapped[str | None] = mapped_column(String(128))
    platform_url: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON)       # 마스킹된 응답·차단 사유
    confounders: Mapped[dict | None] = mapped_column(JSON)  # A/B 교란요인 (게시 시각·요일·계정)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    api_accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
    __table_args__ = (UniqueConstraint("content_id", "variant", "platform", name="uq_pub_once"),)


# ---------------------------------------------------------------- 성과
class SiteEvent(Base):
    """랜딩 이벤트. IP·UA·쿠키 등 개인 식별 정보는 저장하지 않는다."""

    __tablename__ = "site_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    event_type: Mapped[str] = mapped_column(String(16))  # page_view / link_click / video_play
    product_id: Mapped[str | None] = mapped_column(String(64), index=True)
    content_id: Mapped[str | None] = mapped_column(String(64), index=True)
    src: Mapped[str | None] = mapped_column(String(32))    # ig / yt / direct ...
    link_id: Mapped[int | None] = mapped_column(Integer)
    ref_domain: Mapped[str | None] = mapped_column(String(128))


class MetricObservation(Base):
    __tablename__ = "metric_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    content_id: Mapped[str | None] = mapped_column(String(64), index=True)
    variant: Mapped[str | None] = mapped_column(String(4))
    platform: Mapped[str] = mapped_column(String(16))
    metric: Mapped[str] = mapped_column(String(48))
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(24))   # api / manual_csv / site_log
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    __table_args__ = (
        UniqueConstraint("metric_date", "content_id", "variant", "platform", "metric", "source", name="uq_metric"),
    )


class AffiliateReport(Base):
    """쿠팡파트너스 실적 (공식 리포트 API 또는 대시보드 CSV). sub_id 로만 콘텐츠에 귀속한다."""

    __tablename__ = "affiliate_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    program: Mapped[str] = mapped_column(String(32), default="coupang_partners")
    sub_id: Mapped[str | None] = mapped_column(String(64))
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    gmv_krw: Mapped[int] = mapped_column(Integer, default=0)
    commission_krw: Mapped[int] = mapped_column(Integer, default=0)
    cancel_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_amount_krw: Mapped[int] = mapped_column(Integer, default=0)
    settlement_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / confirmed / settled
    source: Mapped[str] = mapped_column(String(16))  # api / manual_csv
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    __table_args__ = (UniqueConstraint("report_date", "program", "sub_id", "source", name="uq_aff_report"),)


# ---------------------------------------------------------------- 운영
class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    stage: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24), default=JobStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    message: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON)
    lock_owner: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("run_date", "stage", name="uq_job_day_stage"),)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    units: Mapped[float | None] = mapped_column(Float)          # 토큰·쿼터 단위
    cost_krw: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)


class CostEntry(Base):
    """API 외 비용(상품 구매·크레딧·서버) 수동 입력."""

    __tablename__ = "cost_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cost_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(32))  # ai_api / video / server / product_sample / other
    amount_krw: Mapped[int] = mapped_column(Integer)
    content_id: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)


Index("ix_site_events_day", SiteEvent.ts, SiteEvent.event_type)
