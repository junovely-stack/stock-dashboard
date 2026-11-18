#!/usr/bin/env python3
"""온톨로지 HTML + md 자동 생성 구간 갱신.

    python scripts/build_ontology.py --rev 01

- 원본: scripts/ontology_data.py (개념·관계·자동화 액션·결정·수정안)
- 출력: docs/SCF_온톨로지_REV<NN>.html (오프라인 단일 파일)
- md: docs/ONTOLOGY.md · DECISIONS.md · AUTOMATION_REVIEW.md 의 <!-- AUTO:...:START/END --> 구간만 교체
  (손으로 쓴 구간·결정 기록은 그대로 둔다)
- 참조 무결성 검사: 관계 끝점, 액션 대상, 결정 번호, 좌표 중복
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ontology_data as O  # noqa: E402

DOCS = ROOT / "docs"
INPUT = {"system": "시스템 데이터", "field": "현장 실측", "human": "사람 확정"}
STAGE = {"done": "구현 완료", "now": "즉시", "short": "단기", "mid": "중기", "out": "대상 외"}
STATE = {"mock": "mock", "manual": "수동 입력", "pending": "연동 대기", "internal": "내부 계산", "connected": "연동됨"}
MLV = {"M0": "수작업", "M1": "도구화", "M2": "자동실행", "M3": "자동판정", "M4": "예측"}


def validate() -> list[str]:
    errs = []
    ids = {n["id"] for n in O.NODES}
    lanes = {l["id"] for l in O.LANES} | {"control"}
    decs = {d["id"] for d in O.DECISIONS}
    acts = {a["id"] for a in O.ACTIONS}
    pos = set()
    for n in O.NODES:
        if n["lane"] not in lanes:
            errs.append(f"노드 {n['id']} lane 오류")
        key = (n["lane"], n.get("row", n.get("col")))
        if key in pos:
            errs.append(f"노드 좌표 중복 {key}")
        pos.add(key)
        for d in n["decisions"]:
            if d not in decs:
                errs.append(f"노드 {n['id']} → 없는 결정 {d}")
        for f in ("input", "stage", "state", "m"):
            if n[f] not in {**INPUT, **STAGE, **STATE, **MLV}:
                errs.append(f"노드 {n['id']} {f}={n[f]}")
    for s, p, o, _ in O.EDGES:
        if s not in ids or o not in ids:
            errs.append(f"관계 끝점 없음 {s}-{p}-{o}")
    for a in O.ACTIONS:
        if a["node"] not in ids:
            errs.append(f"액션 {a['id']} 대상 없음 {a['node']}")
        if a["layer"] not in O.LAYERS:
            errs.append(f"액션 {a['id']} 계층 오류")
        for d in a["dec"]:
            if d not in decs:
                errs.append(f"액션 {a['id']} → 없는 결정 {d}")
    for d in O.DECISIONS:
        for nid in d["nodes"]:
            if nid not in ids:
                errs.append(f"결정 {d['id']} → 없는 노드 {nid}")
        if not 0 <= d["rec"] < len(d["options"]):
            errs.append(f"결정 {d['id']} 권장안 번호 오류")
    for h in O.HUMAN_POINTS:
        if h not in acts:
            errs.append(f"사람 확정 지점 {h} 없음")
    for c in O.PLAN_CHANGES:
        for d in c["dec"]:
            if d not in decs:
                errs.append(f"수정안 → 없는 결정 {d}")
    return errs


def payload(rev: str) -> dict:
    return {
        "rev": rev, "asOf": O.AS_OF, "conclusion": O.CONCLUSION, "reason": O.REASON, "lanes": O.LANES,
        "controlLabel": O.CONTROL_LABEL, "nodes": O.NODES,
        "edges": [{"s": s, "p": p, "o": o, "impl": i} for s, p, o, i in O.EDGES],
        "layers": O.LAYERS, "actions": O.ACTIONS, "decisions": O.DECISIONS, "whenLabel": O.WHEN_LABEL,
        "humanPoints": O.HUMAN_POINTS, "planChanges": O.PLAN_CHANGES,
    }


def build_html(rev: str) -> Path:
    tpl = (ROOT / "scripts" / "ontology_template.html").read_text(encoding="utf-8")
    data = json.dumps(payload(rev), ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/", data).replace("/*__REV__*/", f"REV{rev}")
    out = DOCS / f"SCF_온톨로지_REV{rev}.html"
    out.write_text(html, encoding="utf-8")
    return out


def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def ontology_block(rev: str) -> str:
    node = {n["id"]: n for n in O.NODES}
    lane_label = {l["id"]: l["label"] for l in O.LANES} | {"control": O.CONTROL_LABEL}
    lines = [f"생성: `python scripts/build_ontology.py --rev {rev}` · HTML: [SCF_온톨로지_REV{rev}.html](SCF_온톨로지_REV{rev}.html)", "",
             f"### 개념 {len(O.NODES)}개", "",
             "| 영역 | 개념 | 정의 | 구현 | 입력 유형 | 성숙도 | 착수 | 데이터 | 막힌 것 |", "|---|---|---|---|---|---|---|---|---|"]
    for n in O.NODES:
        lines.append(f"| {lane_label[n['lane']]} | **{n['label']}** | {md_escape(n['desc'])} | `{n['impl'][0]}` | "
                     f"{INPUT[n['input']]} | {n['m']} {MLV[n['m']]} | {STAGE[n['stage']]} | {STATE[n['state']]} | "
                     f"{md_escape(n['gap']) or '—'} |")
    lines += ["", f"### 관계 {len(O.EDGES)}개", "", "| 주어 | 관계 | 목적어 | 근거·구현 |", "|---|---|---|---|"]
    for s, p, o, i in O.EDGES:
        lines.append(f"| {node[s]['label']} | {p} | {node[o]['label']} | {md_escape(i)} |")
    return "\n".join(lines)


def decisions_block() -> str:
    node = {n["id"]: n for n in O.NODES}
    lines = []
    for when, label in O.WHEN_LABEL.items():
        ds = [d for d in O.DECISIONS if d["when"] == when]
        lines += [f"### {label} — {len(ds)}건", ""]
        for d in ds:
            opts = " / ".join(("★ " if i == d["rec"] else "") + o for i, o in enumerate(d["options"]))
            nodes = ", ".join(node[x]["label"] for x in d["nodes"]) or "—"
            lines += [f"**{d['id']}. {d['title']}** — {d['q']}", "",
                      f"- 선택지: {opts}", f"- 이유: {d['why']}", f"- 안 정하면: {d['default']}", f"- 영향 개념: {nodes}", ""]
    return "\n".join(lines).rstrip()


def actions_block() -> str:
    lines = ["| ID | 계층 | 액션 | 입력 유형 | 성숙도 | 착수 | 선행 조건 | 결정 | 메모 |", "|---|---|---|---|---|---|---|---|---|"]
    for a in O.ACTIONS:
        lines.append(f"| {a['id']} | {a['layer']} | {a['name']} | {INPUT[a['input']]} | {a['m_now']}→{a['m_to']} | "
                     f"{STAGE[a['stage']]} | {md_escape(a['pre'])} | {', '.join(a['dec']) or '—'} | {md_escape(a['note'])} |")
    counts = {s: sum(1 for a in O.ACTIONS if a["stage"] == s) for s in STAGE}
    lines += ["", "착수 단계별 액션 수(업무량 아님): " + " · ".join(f"{STAGE[s]} {c}" for s, c in counts.items())]
    hp = {a["id"]: a for a in O.ACTIONS}
    lines += ["", "사람 확정 지점: " + " · ".join(f"{h} {hp[h]['name']}" for h in O.HUMAN_POINTS)]
    return "\n".join(lines)


def plan_block() -> str:
    lines = ["| 원 기획 | 수정안 | 이유 | 결정 |", "|---|---|---|---|"]
    for c in O.PLAN_CHANGES:
        lines.append(f"| {c['from']} | **{c['to']}** | {c['why']} | {', '.join(c['dec'])} |")
    return "\n".join(lines)


def replace_block(path: Path, name: str, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    start, end = f"<!-- AUTO:{name}:START -->", f"<!-- AUTO:{name}:END -->"
    if start not in text or end not in text:
        raise SystemExit(f"{path.name} 에 {start} / {end} 표시가 없습니다")
    new = re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: f"{start}\n{body}\n{end}", text, flags=re.S)
    path.write_text(new, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="01")
    a = ap.parse_args()
    rev = f"{int(a.rev):02d}"
    errs = validate()
    if errs:
        print("데이터 오류:\n  " + "\n  ".join(errs))
        return 1
    out = build_html(rev)
    replace_block(DOCS / "ONTOLOGY.md", "ONTOLOGY", ontology_block(rev))
    replace_block(DOCS / "DECISIONS.md", "DECISIONS", decisions_block())
    replace_block(DOCS / "AUTOMATION_REVIEW.md", "ACTIONS", actions_block())
    replace_block(DOCS / "AUTOMATION_REVIEW.md", "PLAN", plan_block())
    print(f"HTML: {out.relative_to(ROOT)}")
    print(f"개념 {len(O.NODES)} · 관계 {len(O.EDGES)} · 액션 {len(O.ACTIONS)} · 결정 {len(O.DECISIONS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
