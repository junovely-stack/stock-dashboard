#!/usr/bin/env python3
"""Shopping Content Factory CLI.

    python scf.py init-db
    python scf.py run-daily [--date 2026-11-18] [--until qa_check] [--no-publish] [--force]
    python scf.py run-stage <stage> [--date ...] [--force]
    python scf.py retry-failed
    python scf.py scheduler                 # 상시 루프 (Asia/Seoul)
    python scf.py serve [--port 5000]
    python scf.py status
    python scf.py approve <content_id> --by <이름>
    python scf.py publish <content_id> --platform instagram|youtube --by <이름>
    python scf.py register-link <product_id> <url> [--sub-id ..] [--content ..] --by <이름>
    python scf.py import-metrics <csv> | import-coupang <csv>
    python scf.py report [--date ...]
    python scf.py simulate [--out docs/ROI_REPORT.md]
    python scf.py purge-events [--days 90] | delete-product <product_id> --by <이름>
    python scf.py resolve-publication <id> --status published_verified|failed [--media-id ..] --by <이름>
    python scf.py export-demo <content_id> [--out demo]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import get_settings  # noqa: E402
from services.common.db import init_db, session_scope  # noqa: E402
from services.common.logging_utils import setup_logging  # noqa: E402
from services.common.timeutil import parse_date, today_local  # noqa: E402


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def cmd_run_daily(a):
    from workflows.pipeline import run_daily

    res = run_daily(parse_date(a.date), until=a.until, include_publish=not a.no_publish, force=a.force)
    for r in res:
        print(f"{r['stage']:<18} {r['status']:<18} {str(r.get('message') or '')[:110]}")
    return 0 if all(r["status"] in ("succeeded", "already_succeeded") for r in res
                    if r["stage"] != "publish_approved") else 2


def cmd_run_stage(a):
    from workflows.pipeline import FileLock, run_stage

    with FileLock(get_settings().output_dir / ".pipeline.lock"):
        r = run_stage(parse_date(a.date), a.stage, force=a.force)
    print(f"{r['stage']} → {r['status']} {r.get('message') or ''}")
    return 0 if r["status"] in ("succeeded", "already_succeeded") else 2


def cmd_retry_failed(a):
    from workflows.pipeline import STAGES, FileLock, retry_ready, run_stage

    d = today_local()
    with FileLock(get_settings().output_dir / ".pipeline.lock"):
        for st in STAGES:
            from services.common.db import session_scope as ss
            from app.models import JobRun, JobStatus
            from sqlalchemy import select

            with ss() as s:
                row = s.scalars(select(JobRun).where(JobRun.run_date == d, JobRun.stage == st.name)).first()
                failed = row is not None and row.status in (JobStatus.FAILED, JobStatus.SKIPPED_UPSTREAM)
            if failed and retry_ready(d, st.name):
                r = run_stage(d, st.name)
                print(f"{st.name} → {r['status']}")
    return 0


def cmd_status(a):
    from sqlalchemy import select

    from app.models import Content, DataSource, JobRun

    d = parse_date(a.date)
    with session_scope() as s:
        print(f"[데이터 소스] ({d})")
        for ds in s.scalars(select(DataSource).order_by(DataSource.name)):
            print(f"  {ds.name:<20} {ds.state:<15} {ds.note or ''}")
        print("[작업]")
        for j in s.scalars(select(JobRun).where(JobRun.run_date == d).order_by(JobRun.id)):
            print(f"  {j.stage:<18} {j.status:<18} 시도 {j.attempts} {str(j.message or '')[:80]}")
        print("[콘텐츠]")
        for c in s.scalars(select(Content).order_by(Content.created_at.desc()).limit(10)):
            print(f"  {c.id} {c.status:<20} {c.title}")
    return 0


def cmd_approve(a):
    from app.models import Content
    from services.social_publishers.review import approve

    with session_scope() as s:
        approve(s, s.get(Content, a.content_id), a.by, a.notes)
    print(f"{a.content_id} 승인 ({a.by})")
    return 0


def cmd_publish(a):
    from services.social_publishers.publisher import publish_content

    _print(publish_content(a.content_id, a.platform, a.by, trigger="manual"))
    return 0


def cmd_register_link(a):
    from app.models import Product
    from services.affiliate_links.links import register_manual_link

    with session_scope() as s:
        link = register_manual_link(s, s.get(Product, a.product_id), a.url, a.by, sub_id=a.sub_id,
                                    content_id=a.content)
        s.flush()
        print(f"링크 {link.id}: {link.status} — {link.note} (사람이 직접 열어 확인한 뒤 관리자 화면에서 '확인함')")
    return 0


def cmd_import(a, kind):
    from services.analytics.importers import import_affiliate_csv, import_metrics_csv

    _print((import_metrics_csv if kind == "metrics" else import_affiliate_csv)(Path(a.csv)))
    return 0


def cmd_report(a):
    from services.analytics.reports import build_daily_report

    _print(build_daily_report(parse_date(a.date)))
    return 0


def cmd_simulate(a):
    from services.analytics.simulation import run_all, to_markdown

    md = to_markdown(run_all())
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"저장: {a.out}")
    else:
        print(md)
    return 0


def cmd_purge_events(a):
    from services.social_publishers.review import purge_events

    with session_scope() as s:
        n = purge_events(s, a.days)
    print(f"{a.days}일 지난 이벤트 {n}건 삭제")
    return 0


def cmd_delete_product(a):
    from services.social_publishers.review import delete_product

    with session_scope() as s:
        _print(delete_product(s, a.product_id, a.by))
    return 0


def cmd_resolve_publication(a):
    """응답 불확실(unknown) 게시를 사람이 플랫폼 앱에서 확인한 뒤 결과를 기록."""
    from app.models import AuditLog, Publication
    from services.common.timeutil import now_utc

    with session_scope() as s:
        pub = s.get(Publication, a.publication_id)
        before = pub.status
        pub.status = a.status
        if a.media_id:
            pub.platform_media_id = a.media_id
        if a.status == "published_verified":
            pub.verified_at = now_utc()
        s.add(AuditLog(actor=a.by, action="resolve_publication", target_type="publication",
                       target_id=str(pub.id), detail={"from": before, "to": a.status, "media_id": a.media_id}))
    print(f"publication {a.publication_id}: {before} → {a.status}")
    return 0


def cmd_export_demo(a):
    from app.models import Content

    with session_scope() as s:
        c = s.get(Content, a.content_id)
        src = Path(c.output_dir)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copyfile(f, out / f.name)
    print(f"{src} → {out}")
    return 0


def cmd_serve(a):
    from app import create_app

    app = create_app()
    app.run(host=a.host, port=a.port, debug=False)
    return 0


def cmd_scheduler(a):
    from workflows.scheduler import loop

    loop(a.interval)
    return 0


def main(argv=None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Shopping Content Factory")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    x = sub.add_parser("run-daily"); x.add_argument("--date"); x.add_argument("--until"); x.add_argument("--no-publish", action="store_true"); x.add_argument("--force", action="store_true")  # noqa: E702
    x = sub.add_parser("run-stage"); x.add_argument("stage"); x.add_argument("--date"); x.add_argument("--force", action="store_true")  # noqa: E702
    sub.add_parser("retry-failed")
    x = sub.add_parser("status"); x.add_argument("--date")  # noqa: E702
    x = sub.add_parser("approve"); x.add_argument("content_id"); x.add_argument("--by", required=True); x.add_argument("--notes")  # noqa: E702
    x = sub.add_parser("publish"); x.add_argument("content_id"); x.add_argument("--platform", required=True, choices=["instagram", "youtube"]); x.add_argument("--by", required=True)  # noqa: E702
    x = sub.add_parser("register-link"); x.add_argument("product_id"); x.add_argument("url"); x.add_argument("--sub-id"); x.add_argument("--content"); x.add_argument("--by", required=True)  # noqa: E702
    x = sub.add_parser("import-metrics"); x.add_argument("csv")  # noqa: E702
    x = sub.add_parser("import-coupang"); x.add_argument("csv")  # noqa: E702
    x = sub.add_parser("report"); x.add_argument("--date")  # noqa: E702
    x = sub.add_parser("simulate"); x.add_argument("--out")  # noqa: E702
    x = sub.add_parser("purge-events"); x.add_argument("--days", type=int, default=get_settings().event_retention_days)  # noqa: E702
    x = sub.add_parser("delete-product"); x.add_argument("product_id"); x.add_argument("--by", required=True)  # noqa: E702
    x = sub.add_parser("resolve-publication"); x.add_argument("publication_id", type=int); x.add_argument("--status", required=True, choices=["published_verified", "failed"]); x.add_argument("--media-id"); x.add_argument("--by", required=True)  # noqa: E702
    x = sub.add_parser("export-demo"); x.add_argument("content_id"); x.add_argument("--out", default="demo")  # noqa: E702
    x = sub.add_parser("serve"); x.add_argument("--port", type=int, default=5000); x.add_argument("--host", default="127.0.0.1")  # noqa: E702
    x = sub.add_parser("scheduler"); x.add_argument("--interval", type=int, default=30)  # noqa: E702
    a = p.parse_args(argv)
    init_db()
    handlers = {
        "init-db": lambda a: print("DB 준비 완료:", get_settings().database_url.split("@")[-1]) or 0,
        "run-daily": cmd_run_daily, "run-stage": cmd_run_stage, "retry-failed": cmd_retry_failed,
        "status": cmd_status, "approve": cmd_approve, "publish": cmd_publish, "register-link": cmd_register_link,
        "import-metrics": lambda a: cmd_import(a, "metrics"), "import-coupang": lambda a: cmd_import(a, "affiliate"),
        "report": cmd_report, "simulate": cmd_simulate, "purge-events": cmd_purge_events,
        "delete-product": cmd_delete_product, "export-demo": cmd_export_demo,
        "resolve-publication": cmd_resolve_publication, "serve": cmd_serve,
        "scheduler": cmd_scheduler,
    }
    return handlers[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
