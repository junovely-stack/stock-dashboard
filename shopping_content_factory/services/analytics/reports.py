"""일일 수익성 보고서 (outputs/reports/report_YYYY-MM-DD.html / .md).

상단 고정: 데이터 기준일·생성 시각·연결 상태(mock/수동/연동 대기). 실측과 추정을 다른 열로.
학습 메모: 표본이 작으면 '판단 보류'로 쓴다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from jinja2 import Template
from sqlalchemy import select

from app.models import DataSource, JobRun
from config.settings import get_settings
from services.analytics.funnel import content_funnels, cost_summary, unattributed_affiliate
from services.analytics.learning import MIN_CONTENTS, category_stats
from services.common.db import session_scope
from services.common.timeutil import fmt_local, now_utc

TEMPLATE = Template("""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>일일 수익성 보고서 {{ day }}</title>
<style>
:root{--navy:#0A1A2F;--card:#16263D;--orange:#FF6B1A;--sub:#AAB7C4;--good:#2c8a5f;--warn:#c89010;--bad:#b3402a}
body{margin:0;background:var(--navy);color:#fff;font-family:"Pretendard Variable",Pretendard,"Malgun Gothic",sans-serif;
word-break:keep-all;overflow-wrap:break-word;padding:24px}
.fresh{background:var(--card);border-left:4px solid var(--orange);padding:12px 16px;margin-bottom:18px;color:var(--sub)}
h1{font-size:22px;margin:0 0 10px} h2{font-size:17px;margin:26px 0 8px;text-wrap:balance}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--card)}
th,td{border-bottom:1px solid #24395a;padding:7px 8px;text-align:right} th:first-child,td:first-child{text-align:left}
th{color:var(--sub);font-weight:600} .est{color:var(--warn)} .muted{color:var(--sub)} .demo{color:var(--orange);font-weight:700}
</style></head><body>
<h1>일일 수익성 보고서 — {{ day }}</h1>
<div class="fresh">데이터 기준: {{ day }} 까지 · 생성 {{ generated }} · 연결 상태:
{% for d in sources %}{{ d.name }}={{ d.state }}{% if not loop.last %}, {% endif %}{% endfor %}<br>
조회수·좋아요는 매출이 아닙니다. 구매·수수료는 쿠팡 리포트에서 sub_id 로 연결된 것만 '실측'입니다.</div>
<h2>콘텐츠별 퍼널 (실측)</h2>
<table><tr><th>콘텐츠</th><th>상태</th><th>조회</th><th>랜딩 방문</th><th>링크 클릭</th><th>귀속 수수료</th><th>RPM</th><th>비용</th><th>실측 손익</th></tr>
{% for r in rows %}<tr><td>{{ r.content_id }} {% if r.is_demo %}<span class="demo">DEMO</span>{% endif %}<br><span class="muted">{{ r.product }}</span></td>
<td>{{ r.status }}</td><td>{{ fmt(r.measured.views) }}</td><td>{{ r.measured.landing_visits }}</td><td>{{ r.measured.link_clicks }}</td>
<td>{{ fmt(r.measured.commission_krw) }}</td><td>{{ fmt(r.rpm_measured) }}</td><td>{{ fmt(r.cost_krw) }}</td><td>{{ fmt(r.profit_measured) }}</td></tr>
{% else %}<tr><td colspan="9" class="muted">콘텐츠 없음</td></tr>{% endfor %}</table>
<h2>추정 (실측 아님)</h2>
<table><tr><th>콘텐츠</th><th class="est">추정 구매건수 범위</th><th>근거</th></tr>
{% for r in rows %}<tr><td>{{ r.content_id }}</td><td class="est">약 {{ "%.0f"|format(r.estimated.orders_low) }}~{{ "%.0f"|format(r.estimated.orders_high) }}건</td><td class="muted">{{ r.estimated.basis }}</td></tr>{% endfor %}</table>
<h2>미귀속 제휴 실적 (콘텐츠에 연결 안 됨)</h2>
<p class="muted">주문 {{ un.orders }}건 · 구매액 {{ "{:,}".format(un.gmv_krw) }}원 · 수수료 {{ "{:,}".format(un.commission_krw) }}원 — 콘텐츠별로 나누지 않음</p>
<h2>비용·장애</h2>
<p class="muted">API 비용 누적 {{ "{:,.0f}".format(cost.api_cost_krw) }}원 · API 호출 {{ cost.api_calls }}회 · 실패 {{ cost.api_errors }}회 · 수동 비용 {{ cost.manual_costs }}</p>
<table><tr><th>단계</th><th>상태</th><th>시도</th><th>메시지</th></tr>
{% for j in jobs %}<tr><td>{{ j.stage }}</td><td>{{ j.status }}</td><td>{{ j.attempts }}</td><td class="muted">{{ (j.message or '')[:120] }}</td></tr>{% endfor %}</table>
<h2>다음 선정에 반영할 패턴</h2>
<ul>{% for n in learn %}<li>{{ n }}</li>{% endfor %}</ul>
</body></html>""")


def _fmt(v):
    if v is None:
        return "연동 대기"
    return f"{v:,.0f}"


def learning_notes(rows: list[dict]) -> list[str]:
    real = [r for r in rows if not r["is_demo"] and r["measured"]["views"]]
    notes = []
    if len(real) < MIN_CONTENTS:
        notes.append(f"실측 콘텐츠 {len(real)}개 — {MIN_CONTENTS}개 미만이라 패턴 판단 보류 (선정 점수는 가정값 사용)")
    by_hook = defaultdict(lambda: {"n": 0, "views": 0.0, "visits": 0, "comm": 0.0})
    for r in real:
        h = by_hook[r["hook_type"]]
        h["n"] += 1
        h["views"] += r["measured"]["views"] or 0
        h["visits"] += r["measured"]["landing_visits"]
        h["comm"] += r["measured"]["commission_krw"] or 0
    for hook, h in by_hook.items():
        lr = h["visits"] / h["views"] if h["views"] else 0
        notes.append(f"후킹 {hook}: {h['n']}개 · 랜딩 방문율 {lr:.2%} · 조회 1,000회당 수수료 "
                     f"{(h['comm'] / h['views'] * 1000 if h['views'] else 0):,.1f}원"
                     + (" (표본 부족)" if h["n"] < MIN_CONTENTS else ""))
    for cat, st in category_stats().items():
        notes.append(f"카테고리 {cat}: 콘텐츠 {st['contents']}개 · RPM {st['rpm']:,.1f}원 · "
                     + ("점수에 반영 중" if st["sufficient"] else "표본 부족 — 미반영"))
    if not notes:
        notes.append("반영할 실측 데이터 없음")
    return notes


def build_daily_report(report_day: date) -> dict:
    settings = get_settings()
    rows = content_funnels()
    with session_scope() as s:
        sources = [{"name": d.name, "state": d.state} for d in s.scalars(select(DataSource).order_by(DataSource.name))]
        jobs = [{"stage": j.stage, "status": j.status, "attempts": j.attempts, "message": j.message}
                for j in s.scalars(select(JobRun).where(JobRun.run_date == report_day).order_by(JobRun.id))]
    html = TEMPLATE.render(day=report_day.isoformat(), generated=fmt_local(now_utc()), sources=sources, rows=rows,
                           fmt=_fmt, un=unattributed_affiliate(), cost=cost_summary(), jobs=jobs,
                           learn=learning_notes(rows))
    out = settings.output_dir / "reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"report_{report_day.isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    return {"report": str(path), "contents": len(rows)}


def previous_day(d: date) -> date:
    return d - timedelta(days=1)
