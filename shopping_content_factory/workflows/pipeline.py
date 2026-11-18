"""일일 파이프라인 — DB 기반 작업 큐 (job_runs).

- (run_date, stage) 유니크 → 같은 날 같은 단계는 한 번만 성공 처리 (중복 실행 방지)
- 선행 단계가 성공하지 않았으면 후행은 skipped_upstream (상류 실패 → 하류 오염 표시)
- 실패 시 지수 백오프로 next_retry_at 설정, 최대 SCF_JOB_MAX_ATTEMPTS 회
- 정책상 진행 불가(기준 미달·비용 상한·한도·권리 미확인)는 blocked — 재시도하지 않음
- 프로세스 간 동시 실행은 파일 잠금 + 조건부 UPDATE 로 막는다
"""
from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import Content, ContentStatus, JobRun, JobStatus
from config.settings import get_settings
from services.common.cost_guard import CostCapExceeded, UnpricedProvider
from services.common.db import new_session, session_scope
from services.common.http import NotConfiguredError
from services.common.logging_utils import get_logger, redact
from services.common.timeutil import as_utc, now_utc

log = get_logger(__name__)


class PolicyBlock(RuntimeError):
    """정책상 진행하지 않음 (재시도 대상 아님)."""


@dataclass
class Stage:
    name: str
    at: str               # Asia/Seoul HH:MM
    deps: tuple[str, ...]
    fn: Callable[[date], dict]
    label: str


def _final_content_id(run_date: date) -> str:
    from services.product_scoring.selection import final_product_id

    pid = final_product_id(run_date)
    if not pid:
        raise PolicyBlock("최종 선정 상품 없음")
    with session_scope() as s:
        c = s.scalars(select(Content).where(Content.run_date == run_date, Content.product_id == pid)).first()
        if c is None:
            raise PolicyBlock("콘텐츠 없음")
        if c.status == ContentStatus.BLOCKED:
            raise PolicyBlock("콘텐츠 차단됨: " + "; ".join(c.block_reasons or []))
        return c.id


def st_collect_metrics(d: date) -> dict:
    from services.analytics.importers import collect_platform_metrics

    return collect_platform_metrics(d)


def st_daily_report(d: date) -> dict:
    from services.analytics.reports import build_daily_report

    return build_daily_report(d - timedelta(days=1))


def st_collect_trends(d: date) -> dict:
    from services.trend_collector.collector import collect_trends

    return collect_trends(d)


def st_score(d: date) -> dict:
    from services.product_discovery.discovery import discover_products
    from services.product_scoring.scoring import score_candidates

    disc = discover_products(d)
    score = score_candidates(d)
    if score["pass"] == 0:
        raise PolicyBlock("평가 통과 상품 0개")
    return {"discovery": disc, "scoring": score}


def st_select(d: date) -> dict:
    from services.product_scoring.selection import NothingToProduce, select_final

    try:
        return select_final(d)
    except NothingToProduce as exc:
        raise PolicyBlock(str(exc)) from exc


def st_script(d: date) -> dict:
    from services.product_scoring.selection import final_product_id
    from services.psychology_engine.engine import analyze
    from services.script_generator.generator import DailyLimitReached, generate_content

    pid = final_product_id(d)
    if not pid:
        raise PolicyBlock("최종 선정 상품 없음")
    try:
        psy = analyze(d, pid)
        res = generate_content(d, pid)
    except DailyLimitReached as exc:
        raise PolicyBlock(str(exc)) from exc
    if res["status"] == ContentStatus.BLOCKED:
        raise PolicyBlock("사실·표시 검사 실패: " + "; ".join(i["message"] for i in res["fact_check"]["issues"][:5]))
    return {"psychology": psy, "content": {k: v for k, v in res.items() if k != "fact_check"}}


def st_media(d: date) -> dict:
    from services.image_generator.composer import RightsBlocked, produce_images
    from services.video_renderer.renderer import render_content

    cid = _final_content_id(d)
    try:
        imgs = produce_images(cid)
    except RightsBlocked as exc:
        raise PolicyBlock(str(exc)) from exc
    vid = render_content(cid)
    return {"content_id": cid, "images": imgs, "video": vid["rendered"]}


def st_qa(d: date) -> dict:
    from services.video_renderer.qa import run_qa

    res = run_qa(_final_content_id(d))
    if res["errors"]:
        raise PolicyBlock(f"QA 실패: {res['errors']}")
    return res


def st_publish(d: date) -> dict:
    from services.social_publishers.publisher import publish_due

    return publish_due(d)


STAGES: list[Stage] = [
    Stage("collect_metrics", "07:00", (), st_collect_metrics, "전일 성과 집계"),
    Stage("daily_report", "07:05", ("collect_metrics",), st_daily_report, "전일 수익성 보고서"),
    Stage("collect_trends", "07:00", (), st_collect_trends, "트렌드 수집"),
    Stage("score_candidates", "07:20", ("collect_trends",), st_score, "후보 20개 발굴·평가"),
    Stage("select_verify", "07:35", ("score_candidates",), st_select, "상위 후보 검증·최종 선정"),
    Stage("generate_script", "07:45", ("select_verify",), st_script, "구매심리·대본"),
    Stage("produce_media", "08:00", ("generate_script",), st_media, "이미지·영상 제작"),
    Stage("qa_check", "09:00", ("produce_media",), st_qa, "자동 QA → 승인 대기"),
    Stage("publish_approved", "12:00", (), st_publish, "승인 콘텐츠 게시"),
]
STAGE_MAP = {s.name: s for s in STAGES}


class FileLock:
    """프로세스 간 단순 잠금. 오래된 잠금(2시간)은 회수."""

    def __init__(self, path: Path, stale_seconds: int = 7200):
        self.path = path
        self.stale = stale_seconds
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > self.stale:
            self.path.unlink(missing_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"다른 파이프라인 실행 중 (잠금 {self.path})") from exc
        os.write(self.fd, f"{os.getpid()}@{socket.gethostname()}".encode())
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
        self.path.unlink(missing_ok=True)


def _get_or_create(s, run_date: date, stage: str) -> JobRun:
    row = s.scalars(select(JobRun).where(JobRun.run_date == run_date, JobRun.stage == stage)).first()
    if row is None:
        row = JobRun(run_date=run_date, stage=stage, status=JobStatus.PENDING)
        s.add(row)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            row = s.scalars(select(JobRun).where(JobRun.run_date == run_date, JobRun.stage == stage)).first()
    return row


def run_stage(run_date: date, stage_name: str, force: bool = False) -> dict:
    settings = get_settings()
    stage = STAGE_MAP[stage_name]
    owner = f"{os.getpid()}@{socket.gethostname()}"
    s = new_session()
    try:
        row = _get_or_create(s, run_date, stage_name)
        if row.status == JobStatus.SUCCEEDED and not force:
            return {"stage": stage_name, "status": "already_succeeded"}
        if row.status == JobStatus.BLOCKED and not force:
            return {"stage": stage_name, "status": "blocked", "message": row.message}
        if row.status == JobStatus.FAILED and row.attempts >= settings.job_max_attempts and not force:
            return {"stage": stage_name, "status": "failed_max_attempts", "message": row.message}
        for dep in stage.deps:
            dep_row = s.scalars(select(JobRun).where(JobRun.run_date == run_date, JobRun.stage == dep)).first()
            if dep_row is None or dep_row.status != JobStatus.SUCCEEDED:
                row.status = JobStatus.SKIPPED_UPSTREAM
                row.message = f"선행 단계 {dep} = {dep_row.status if dep_row else '미실행'} → 결과 신뢰 불가로 건너뜀"
                row.finished_at = now_utc()
                s.commit()
                return {"stage": stage_name, "status": row.status, "message": row.message}
        res = s.execute(update(JobRun).where(JobRun.id == row.id, JobRun.status != JobStatus.RUNNING)
                        .values(status=JobStatus.RUNNING, attempts=JobRun.attempts + 1, started_at=now_utc(),
                                lock_owner=owner, message=None))
        s.commit()
        if res.rowcount != 1:
            return {"stage": stage_name, "status": "running_elsewhere"}
        job_id = row.id
    finally:
        s.close()

    log.info("단계 시작 %s %s", run_date, stage_name)
    status, message, detail = JobStatus.SUCCEEDED, "ok", None
    try:
        detail = stage.fn(run_date)
    except (PolicyBlock, CostCapExceeded, UnpricedProvider, NotConfiguredError) as exc:
        status, message = JobStatus.BLOCKED, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        status, message = JobStatus.FAILED, f"{type(exc).__name__}: {exc}"
        log.exception("단계 실패 %s", stage_name)
    with session_scope() as s2:
        row = s2.get(JobRun, job_id)
        row.status = status
        row.message = redact(message)[:4000]
        row.detail = _jsonable(detail)
        row.finished_at = now_utc()
        if status == JobStatus.FAILED:
            delay = min(3600, 120 * (2 ** (row.attempts - 1)))
            row.next_retry_at = now_utc() + timedelta(seconds=delay)
    log.info("단계 종료 %s %s → %s %s", run_date, stage_name, status, message[:200])
    return {"stage": stage_name, "status": status, "message": message, "detail": detail}


def _jsonable(obj):
    import json

    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return {"repr": str(obj)[:2000]}


def run_daily(run_date: date, until: str | None = None, include_publish: bool = True, force: bool = False) -> list[dict]:
    """모든 단계를 순서대로 1회 (수동 복구·데모용). 시간 조건은 보지 않는다."""
    settings = get_settings()
    out = []
    with FileLock(settings.output_dir / ".pipeline.lock"):
        for st in STAGES:
            if st.name == "publish_approved" and not include_publish:
                continue
            out.append(run_stage(run_date, st.name, force=force))
            if until and st.name == until:
                break
    return out


def due_stages(now_local: datetime) -> list[Stage]:
    hhmm = now_local.strftime("%H:%M")
    return [st for st in STAGES if st.at <= hhmm]


def retry_ready(run_date: date, stage: str) -> bool:
    with session_scope() as s:
        row = s.scalars(select(JobRun).where(JobRun.run_date == run_date, JobRun.stage == stage)).first()
        if row is None or row.status in (JobStatus.PENDING, JobStatus.SKIPPED_UPSTREAM):
            return True
        if row.status == JobStatus.FAILED:
            nra = as_utc(row.next_retry_at)
            return row.attempts < get_settings().job_max_attempts and (nra is None or nra <= now_utc())
        return False
