from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config.settings import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    return datetime.now(tz())


def today_local() -> date:
    return now_local().date()


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite 는 tz 정보를 버리므로, naive 값은 UTC 로 저장된 것으로 간주한다."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime | None) -> datetime | None:
    dt = as_utc(dt)
    return dt.astimezone(tz()) if dt else None


def fmt_local(dt: datetime | None, pattern: str = "%Y-%m-%d %H:%M") -> str:
    local = to_local(dt)
    return local.strftime(pattern) if local else "-"


def hours_since(dt: datetime | None) -> float | None:
    dt = as_utc(dt)
    if dt is None:
        return None
    return (now_utc() - dt).total_seconds() / 3600.0


def parse_date(value: str | date | None) -> date:
    if value is None:
        return today_local()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
