"""환경설정 단일 진입점.

- 비밀값은 전부 환경변수(.env)로만 받는다. 코드에 기본값으로 키를 넣지 않는다.
- 경로는 하드코딩하지 않고 BASE_DIR 기준 + 환경변수 오버라이드.
- TOML 설정(config/*.toml)은 사람이 손보는 정책값(배점·금칙어·재무 가정·단가)이다.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"

load_dotenv(BASE_DIR / ".env", override=False)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value is not None else default


def _float(name: str, default: float) -> float:
    value = _env(name)
    return float(value) if value is not None else default


def _path(name: str, default: Path) -> Path:
    value = _env(name)
    return Path(value).expanduser().resolve() if value else default


@dataclass(frozen=True)
class Settings:
    env: str
    base_dir: Path
    data_dir: Path
    output_dir: Path
    database_url: str
    secret_key: str
    admin_password: str | None
    api_token: str | None
    timezone: str
    site_base_url: str
    public_media_base_url: str | None

    # 운영 안전장치
    auto_publish: bool
    daily_content_limit: int
    daily_publish_limit: int
    min_candidates: int
    min_final_score: float
    price_ttl_hours: int
    cost_cap_daily_krw: int
    cost_cap_monthly_krw: int
    usd_krw: float
    allow_partner_images_in_video: bool
    render_both_variants: bool
    render_fps: int
    event_retention_days: int
    job_max_attempts: int

    # 어댑터 선택 (mock | 실제)
    trend_provider: str
    product_provider: str
    llm_provider: str
    image_provider: str
    tts_provider: str
    anthropic_model: str
    anthropic_effort: str

    # 외부 자격증명 (없으면 None → mock/대기 상태로 동작)
    naver_client_id: str | None
    naver_client_secret: str | None
    coupang_access_key: str | None
    coupang_secret_key: str | None
    coupang_sub_id: str | None
    instagram_user_id: str | None
    instagram_access_token: str | None
    instagram_graph_version: str
    youtube_client_id: str | None
    youtube_client_secret: str | None
    youtube_refresh_token: str | None
    youtube_privacy_status: str
    anthropic_api_key_present: bool
    openai_api_key_present: bool

    extra: dict = field(default_factory=dict)

    @property
    def is_dev(self) -> bool:
        return self.env in {"dev", "test"}

    @property
    def media_base_url(self) -> str | None:
        """인스타그램이 영상을 가져갈 공개 URL. 명시값 우선, 없으면 공개 도메인일 때만 사이트 /media 사용."""
        if self.public_media_base_url:
            return self.public_media_base_url.rstrip("/")
        base = self.site_base_url.rstrip("/")
        if any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0")):
            return None
        return f"{base}/media"


def load_settings() -> Settings:
    data_dir = _path("SCF_DATA_DIR", BASE_DIR / "data")
    output_dir = _path("SCF_OUTPUT_DIR", BASE_DIR / "outputs")
    default_db = f"sqlite:///{(data_dir / 'scf.db').as_posix()}"
    env = _env("SCF_ENV", "dev")
    secret_key = _env("SCF_SECRET_KEY")
    if not secret_key:
        if env == "prod":
            raise RuntimeError("SCF_SECRET_KEY 가 설정되지 않았습니다(.env). prod 에서는 필수입니다.")
        secret_key = "dev-only-insecure-key-change-me"

    return Settings(
        env=env,
        base_dir=BASE_DIR,
        data_dir=data_dir,
        output_dir=output_dir,
        database_url=_env("SCF_DATABASE_URL", default_db),
        secret_key=secret_key,
        admin_password=_env("SCF_ADMIN_PASSWORD"),
        api_token=_env("SCF_API_TOKEN"),
        timezone=_env("SCF_TIMEZONE", "Asia/Seoul"),
        site_base_url=_env("SCF_SITE_BASE_URL", "http://localhost:5000"),
        public_media_base_url=_env("SCF_PUBLIC_MEDIA_BASE_URL"),
        auto_publish=_bool("AUTO_PUBLISH", False),
        daily_content_limit=_int("SCF_DAILY_CONTENT_LIMIT", 1),
        daily_publish_limit=_int("SCF_DAILY_PUBLISH_LIMIT", 2),
        min_candidates=_int("SCF_MIN_CANDIDATES", 20),
        min_final_score=_float("SCF_MIN_FINAL_SCORE", 55.0),
        price_ttl_hours=_int("SCF_PRICE_TTL_HOURS", 24),
        cost_cap_daily_krw=_int("SCF_COST_CAP_DAILY_KRW", 3000),
        cost_cap_monthly_krw=_int("SCF_COST_CAP_MONTHLY_KRW", 50000),
        usd_krw=_float("SCF_USD_KRW", 1400.0),
        allow_partner_images_in_video=_bool("SCF_ALLOW_PARTNER_IMAGES_IN_VIDEO", False),
        render_both_variants=_bool("SCF_RENDER_BOTH_VARIANTS", False),
        render_fps=_int("SCF_RENDER_FPS", 30),
        event_retention_days=_int("SCF_EVENT_RETENTION_DAYS", 90),
        job_max_attempts=_int("SCF_JOB_MAX_ATTEMPTS", 3),
        trend_provider=_env("SCF_TREND_PROVIDER", "mock"),
        product_provider=_env("SCF_PRODUCT_PROVIDER", "mock"),
        llm_provider=_env("SCF_LLM_PROVIDER", "mock"),
        image_provider=_env("SCF_IMAGE_PROVIDER", "local"),
        tts_provider=_env("SCF_TTS_PROVIDER", "none"),
        anthropic_model=_env("SCF_ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_effort=_env("SCF_ANTHROPIC_EFFORT", "medium"),
        naver_client_id=_env("NAVER_CLIENT_ID"),
        naver_client_secret=_env("NAVER_CLIENT_SECRET"),
        coupang_access_key=_env("COUPANG_ACCESS_KEY"),
        coupang_secret_key=_env("COUPANG_SECRET_KEY"),
        coupang_sub_id=_env("COUPANG_SUB_ID"),
        instagram_user_id=_env("INSTAGRAM_USER_ID"),
        instagram_access_token=_env("INSTAGRAM_ACCESS_TOKEN"),
        instagram_graph_version=_env("INSTAGRAM_GRAPH_VERSION", "v23.0"),
        youtube_client_id=_env("YOUTUBE_CLIENT_ID"),
        youtube_client_secret=_env("YOUTUBE_CLIENT_SECRET"),
        youtube_refresh_token=_env("YOUTUBE_REFRESH_TOKEN"),
        youtube_privacy_status=_env("YOUTUBE_PRIVACY_STATUS", "private"),
        anthropic_api_key_present=bool(_env("ANTHROPIC_API_KEY")),
        openai_api_key_present=bool(_env("OPENAI_API_KEY")),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reload_settings() -> Settings:
    """테스트·CLI 에서 환경변수를 바꾼 뒤 다시 읽을 때 사용."""
    get_settings.cache_clear()
    load_policy.cache_clear()
    return get_settings()


@lru_cache(maxsize=16)
def load_policy(name: str) -> dict:
    """config/<name>.toml 정책 파일 로드 (scoring, compliance, finance, costs, categories)."""
    path = CONFIG_DIR / f"{name}.toml"
    with path.open("rb") as f:
        return tomllib.load(f)
