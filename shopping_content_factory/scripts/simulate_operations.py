#!/usr/bin/env python3
"""가상 운영 시뮬레이터 — N일 동안 mock 데이터로 매일 파이프라인을 돌리고 사람 역할을 흉내 내어
어디서 막히는지(방해 요소)와 사람이 몇 번 손대야 하는지(개입 지점)를 기록한다.

    python scripts/simulate_operations.py --days 30 [--with-links] [--provider mock|manual] [--fps 6] [--out <폴더>]

- 실제 DB·산출물은 건드리지 않는다: 임시 폴더에 별도 DB·outputs 를 만든다.
- 외부 API 호출 없음(mock). 게시는 하지 않고 게시 게이트(gate)만 검사한다.
- --with-links: 사람이 매일 새 상품의 제휴 링크를 등록·확인했다고 가정(시뮬레이션 전용 가짜 링크, 임시 DB 에만 존재).
- 결과: <out>/virtual_ops_report.md, <out>/virtual_ops.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def setup_env(work: Path, fps: int, provider: str = "mock") -> None:
    for k in ["ANTHROPIC_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "COUPANG_ACCESS_KEY", "COUPANG_SECRET_KEY",
              "INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
              "YOUTUBE_REFRESH_TOKEN", "SCF_PUBLIC_MEDIA_BASE_URL"]:
        os.environ.pop(k, None)
    os.environ.update({
        "SCF_ENV": "test", "SCF_DATABASE_URL": f"sqlite:///{work / 'sim.db'}", "SCF_OUTPUT_DIR": str(work / "out"),
        "SCF_DATA_DIR": str(ROOT / "data"), "SCF_RENDER_FPS": str(fps), "SCF_LLM_PROVIDER": "mock",
        "SCF_TREND_PROVIDER": "mock", "SCF_PRODUCT_PROVIDER": provider, "SCF_LOG_LEVEL": "ERROR", "AUTO_PUBLISH": "false",
    })
    (work / "out").mkdir(parents=True, exist_ok=True)


def run(days: int, start: date, with_links: bool, work: Path) -> list[dict]:
    from sqlalchemy import select

    from app.models import Content, Product, ProductScore
    from config.settings import get_settings
    from services.affiliate_links.links import confirm_link, register_manual_link
    from services.common.db import init_db, session_scope
    from services.social_publishers.publisher import gate
    from services.social_publishers.review import approve
    from workflows.pipeline import run_daily

    init_db()
    settings = get_settings()
    rows = []
    linked: set[str] = set()
    for i in range(days):
        d = start + timedelta(days=i)
        res = {r["stage"]: r for r in run_daily(d, include_publish=False)}
        day = {"day": i + 1, "date": d.isoformat(), "stages": {k: v["status"] for k, v in res.items()},
               "blocked_stage": next((f"{k}: {str(v.get('message') or '')[:90]}" for k, v in res.items()
                                      if v["status"] not in ("succeeded", "already_succeeded")), None),
               "human": []}
        with session_scope() as s:
            scores = list(s.scalars(select(ProductScore).where(ProductScore.run_date == d)))
            day["pass"] = sum(1 for x in scores if x.filter_result == "pass")
            day["hold"] = sum(1 for x in scores if x.filter_result == "hold")
            day["exclude"] = sum(1 for x in scores if x.filter_result == "exclude")
            day["eligible"] = sum(1 for x in scores if x.filter_result == "pass" and x.total >= settings.min_final_score)
            final = next((x for x in scores if x.selection == "final"), None)
            day["final"] = final.product_id if final else None
            day["final_score"] = round(final.total, 1) if final else None
            c = s.scalars(select(Content).where(Content.run_date == d)).first()
            day["content"] = c.id if c else None
            day["content_status"] = c.status if c else None
            if c is not None:
                p = s.get(Product, c.product_id)
                day["category"] = p.category_key
                day["custom_visual"] = (p.signals or {}).get("illustration") == "cable_tray"
                if c.status == "awaiting_approval":
                    approve(s, c, "sim-operator", "가상 운영 승인")
                    day["human"].append("승인")
                if with_links and p.id not in linked:
                    link = register_manual_link(s, p, f"https://link.coupang.com/a/SIMULATION{i:03d}", "sim-operator",
                                                sub_id=f"sim-{c.id}", content_id=c.id)
                    s.flush()
                    confirm_link(s, link, "sim-operator")
                    linked.add(p.id)
                    day["human"].append("링크 등록·확인")
        with session_scope() as s:
            c = s.scalars(select(Content).where(Content.run_date == d)).first()
            day["publish_blockers"] = gate(c, "youtube", settings) if c is not None else []
        rows.append(day)
        print(f"D{i + 1:02d} {d} 최종={day['final']} 점수={day['final_score']} 통과={day['pass']} "
              f"선정가능={day['eligible']} 콘텐츠={day['content_status']} 게시차단={len(day['publish_blockers'])}",
              flush=True)
    return rows


def report(rows: list[dict], with_links: bool) -> str:
    made = [r for r in rows if r["content"]]
    first_gap = next((r["day"] for r in rows if not r["content"]), None)
    publishable = [r for r in rows if r["content"] and not r["publish_blockers"]]
    cats = {}
    for r in made:
        cats[r.get("category")] = cats.get(r.get("category"), 0) + 1
    custom = sum(1 for r in made if r.get("custom_visual"))
    lines = [
        "# 가상 운영 시뮬레이션 결과", "",
        f"- 기간: {rows[0]['date']} ~ {rows[-1]['date']} ({len(rows)}일), mock 상품 24개·트렌드 28개, 1일 1개, 사람 역할은 스크립트가 대신함",
        f"- 제휴 링크: {'매일 새 상품마다 사람이 등록·확인했다고 가정' if with_links else '등록 안 함(현재 상태 그대로)'}",
        f"- 콘텐츠 생성일: {len(made)}일 / {len(rows)}일 · 처음 만들지 못한 날: {f'D{first_gap}' if first_gap else '없음'}",
        f"- 게이트 통과(게시 가능) 콘텐츠: {len(publishable)}개",
        f"- 카테고리 분포: " + ", ".join(f"{k} {v}" for k, v in cats.items()),
        f"- 전용 연출 이미지가 있는 콘텐츠: {custom}개 / 나머지 {len(made) - custom}개는 범용 그라디언트 배경",
        "", "| 일 | 날짜 | 최종 상품 | 점수 | 통과 | 기준 이상 | 콘텐츠 | 사람 개입 | 게시 차단 사유 | 멈춘 단계 |",
        "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| D{r['day']} | {r['date']} | {r['final'] or '—'} | {r['final_score'] or '—'} | {r['pass']} | "
                     f"{r['eligible']} | {r['content_status'] or '—'} | {', '.join(r['human']) or '—'} | "
                     f"{'; '.join(r['publish_blockers']) or '—'} | {r['blocked_stage'] or '—'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start", default="2026-11-18")
    ap.add_argument("--with-links", action="store_true")
    ap.add_argument("--fps", type=int, default=6)
    ap.add_argument("--out", default=None)
    ap.add_argument("--provider", choices=["mock", "manual"], default="mock",
                    help="manual = data/manual/products.json 의 실제 후보로 고갈일 확인 (수동 가격 결함 수정 후 사용)")
    a = ap.parse_args()
    work = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="scf_sim_"))
    work.mkdir(parents=True, exist_ok=True)
    setup_env(work, a.fps, a.provider)
    rows = run(a.days, date.fromisoformat(a.start), a.with_links, work)
    (work / "virtual_ops.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (work / "virtual_ops_report.md").write_text(report(rows, a.with_links), encoding="utf-8")
    print(f"결과: {work / 'virtual_ops_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
