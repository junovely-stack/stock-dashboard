"""상시 루프 스케줄러 (Asia/Seoul). cron·n8n 없이 단독 실행용.

    python scf.py scheduler

- 30초마다 '예정 시각이 지난' 단계 중 아직 성공하지 않았고 재시도 시점이 된 것만 실행
- 같은 날 이미 성공한 단계는 다시 돌지 않음 (job_runs 유니크)
- 루프 본문 전체를 예외 처리 → 한 단계 오류로 스케줄러가 죽지 않음
- outputs/.scheduler_heartbeat 에 마지막 동작 시각 기록 (관리자 화면에서 확인)
"""
from __future__ import annotations

import time

from config.settings import get_settings
from services.common.logging_utils import get_logger
from services.common.timeutil import now_local
from workflows.pipeline import FileLock, due_stages, retry_ready, run_stage

log = get_logger(__name__)


def tick() -> list[dict]:
    settings = get_settings()
    now = now_local()
    run_date = now.date()
    results = []
    try:
        with FileLock(settings.output_dir / ".pipeline.lock"):
            for st in due_stages(now):
                if retry_ready(run_date, st.name):
                    results.append(run_stage(run_date, st.name))
    except RuntimeError as exc:  # 다른 실행이 잠금 보유
        log.info("이번 회차 건너뜀: %s", exc)
    (settings.output_dir / ".scheduler_heartbeat").write_text(now.isoformat(), encoding="utf-8")
    return results


def loop(poll_seconds: int = 30) -> None:
    log.info("스케줄러 시작 (Asia/Seoul, %d초 간격). 중지: Ctrl+C", poll_seconds)
    while True:
        try:
            for r in tick():
                log.info("%s → %s", r["stage"], r["status"])
        except KeyboardInterrupt:
            log.info("스케줄러 종료")
            return
        except Exception:  # noqa: BLE001
            log.exception("스케줄러 루프 오류 — 다음 회차에 계속")
        time.sleep(poll_seconds)
