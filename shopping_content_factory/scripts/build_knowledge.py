#!/usr/bin/env python3
"""SCF 지식체계 생성기.

    python scripts/build_knowledge.py --rev 01

입력: scripts/ontology_data.py(도메인) + scripts/knowledge_data.py(나머지 지식 층)
출력:
  docs/SCF_지식체계_REV<NN>.html   — 진행 현황·지식 지도·탐색기·추적표 (오프라인 단일 파일)
  docs/KNOWLEDGE_BASE.md            — AUTO:KB 구간
  docs/PROGRESS.md                  — AUTO:PROGRESS 구간 (손으로 쓴 '다음 할 일·메모'는 보존)
  docs/knowledge/scf_knowledge.json — 개체·관계 전체
  docs/knowledge/scf_knowledge.ttl  — RDF(Turtle): owl:Class · owl:ObjectProperty · 개체
검사: ID 중복, 관계 끝점, 관계 유형별 정의역·치역, 도메인 관계 술어 매핑.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import knowledge_data as K  # noqa: E402
import ontology_data as O  # noqa: E402

DOCS = ROOT / "docs"
STATUS_LABEL = {
    "done": "완료", "partial": "부분", "todo": "미착수", "active": "진행 중", "pass": "통과", "caveat": "통과(단서)",
    "fail": "실패", "open": "미해결", "fixed": "해결", "pending": "결정 대기", "decided": "결정됨",
    "now": "즉시", "short": "단기", "mid": "중기", "out": "대상 외",
}
STAGE_LABEL = {"done": "구현 완료", "now": "즉시", "short": "단기", "mid": "중기", "out": "대상 외"}
CLS_LABEL = {c[0]: c[1] for c in K.CLASSES}
PROP = {p[0]: {"id": p[0], "label": p[1], "domain": p[2], "range": p[3]} for p in K.PROPERTIES}


def expand(token: str, ents: dict) -> list[str]:
    if token.endswith(":*"):
        cls = token[:-2]
        return [e for e, v in ents.items() if v["cls"] == cls]
    return [token]


def build_graph() -> tuple[dict, list]:
    ents: dict[str, dict] = {}
    rels: list[dict] = []

    def add(eid, cls, label, desc="", status=None, **props):
        if eid in ents:
            raise SystemExit(f"ID 중복: {eid}")
        ents[eid] = {"id": eid, "cls": cls, "label": label, "desc": desc, "status": status, "props": props}

    def rel(s, p, o, note="", sub=None):
        rels.append({"s": s, "p": p, "o": o, "note": note, "sub": sub})

    # ---- 도메인(ontology_data)
    lane = {l["id"]: l["label"] for l in O.LANES} | {"control": O.CONTROL_LABEL}
    for n in O.NODES:
        add(n["id"], "Concept", n["label"], n["desc"], n["stage"], area=lane[n["lane"]], input=n["input"], m=n["m"],
            data_state=n["state"], gap=n["gap"], sub=n["sub"])
    for a in O.ACTIONS:
        add(a["id"], "Action", a["name"], a["note"], a["stage"], layer=a["layer"], input=a["input"],
            m=f"{a['m_now']}→{a['m_to']}", pre=a["pre"])
    for d in O.DECISIONS:
        decided = K.DECIDED.get(d["id"])
        add(d["id"], "Decision", d["title"], d["q"], "decided" if decided else "pending", when=O.WHEN_LABEL[d["when"]],
            recommend=d["options"][d["rec"]], options=" / ".join(d["options"]), why=d["why"], default=d["default"],
            decided=f"{decided[0]} {decided[1]}" if decided else "")
    for i, c in enumerate(O.PLAN_CHANGES, 1):
        add(f"PC{i:02d}", "PlanChange", c["to"], c["why"], None, before=c["from"])

    # ---- 지식 층(knowledge_data)
    for pid, label, status, desc, _ in K.PHASES:
        add(pid, "Phase", label, desc, status)
    for cid, label, paths, desc in K.COMPONENTS:
        add(cid, "Component", label, desc, None, paths=", ".join(paths))
    for did, label, status, memo, _, _ in K.DELIVERABLES:
        add(did, "Deliverable", label, memo, status)
    for cid, label, status, caveat, _ in K.CRITERIA:
        add(cid, "Criterion", label, caveat, status)
    for vid, label, count, desc, _ in K.VERIFICATIONS:
        add(vid, "Verification", label, desc, None, count=count)
    for eid, label, desc, _ in K.EVIDENCE:
        add(eid, "Evidence", label, desc, None)
    for did, label, path, desc in K.DOCUMENTS:
        add(did, "Document", label, desc, None, path=path)
    for pid, label, desc in K.PARTIES:
        add(pid, "Party", label, desc, None)
    for fid, label, conf, _, _ in K.FACTS:
        add(fid, "Fact", label, "", None, confidence=conf)
    for gid, label, _, _ in K.REGULATIONS:
        add(gid, "Regulation", label, "", None)
    for sid, label, kind, _ in K.ASSUMPTIONS:
        add(sid, "Assumption", label, "", None, kind=kind)
    for rid, label, level, _, _ in K.RISKS:
        add(rid, "Risk", label, "", None, level=level)
    for kid, label, kind, status, _, _, _ in K.DEFECTS:
        add(kid, "Defect", label, "", status, kind="결함" if kind == "defect" else "설계 약점")
    for mid, label, status, _ in K.METRICS:
        add(mid, "Metric", label, status, None)

    # ---- 관계
    prefixes = sorted(((p, cid) for cid, _, paths, _ in K.COMPONENTS for p in paths), key=lambda x: -len(x[0]))
    for n in O.NODES:
        hit = set()
        for impl in n["impl"]:
            path = impl.split(" ")[0]
            comp = next((cid for pfx, cid in prefixes if path.startswith(pfx.rstrip("*").replace("*.toml", ""))), None)
            if comp is None and "/" not in path and not path.endswith(".py"):
                comp = "CP25"  # 테이블·컬럼
            if comp and comp not in hit:
                hit.add(comp)
                rel(comp, "implements", n["id"], impl)
    for s, p, o, note in O.EDGES:
        rel(s, "domain", o, note, sub=p)
    for d in O.DECISIONS:
        for nid in d["nodes"]:
            rel(d["id"], "impacts", nid)
        rel(d["id"], "gates", K.DECISION_GATE_DEFAULT[d["when"]])
        rel(d["id"], "decidedBy", "P_USER")
    for a in O.ACTIONS:
        rel(a["id"], "targets", a["node"])
        for dd in a["dec"]:
            rel(a["id"], "dependsOn", dd)
    for i, c in enumerate(O.PLAN_CHANGES, 1):
        for dd in c["dec"]:
            rel(f"PC{i:02d}", "dependsOn", dd)
    for pid, _, _, _, parent in K.PHASES:
        if parent:
            rel(pid, "partOf", parent)
    for did, _, _, _, comps, phase in K.DELIVERABLES:
        for c in comps:
            rel(c, "realizes", did)
        rel(did, "deliveredIn", phase)
    for cid, _, _, _, verifs in K.CRITERIA:
        for v in verifs:
            rel(v, "verifies", cid)
    for vid, _, _, _, comps in K.VERIFICATIONS:
        for c in comps:
            rel(vid, "verifies", c)
    for eid, _, _, verifs in K.EVIDENCE:
        for v in verifs:
            rel(v, "produces", eid)
    for fid, _, _, party, targets in K.FACTS:
        rel(fid, "sourcedFrom", party)
        for t in targets:
            rel(fid, "supports", t)
    for gid, _, party, targets in K.REGULATIONS:
        rel(gid, "sourcedFrom", party)
        for t in targets:
            rel(gid, "constrains", t)
    for sid, _, _, targets in K.ASSUMPTIONS:
        for t in targets:
            rel(sid, "feeds", t)
    for rid, _, _, threats, mitig in K.RISKS:
        for t in threats:
            rel(rid, "threatens", t)
        for m in mitig:
            rel(rid, "mitigatedBy", m)
    have = {(r["s"], r["p"], r["o"]) for r in rels}
    for s, r in K.RISK_SUPPORT:  # 사실 목록에 이미 있는 근거는 건너뜀
        if (s, "supports", r) not in have:
            rel(s, "supports", r)
    for kid, _, _, _, affects, found, resolved in K.DEFECTS:
        for t in affects:
            rel(kid, "affects", t)
        for f in found:
            rel(kid, "foundBy", f)
        for r in resolved:
            rel(kid, "resolvedBy", r)
    for mid, _, _, targets in K.METRICS:
        for t in targets:
            rel(mid, "measures", t)
    for party, cid in K.PARTY_PROVIDES:
        rel(party, "provides", cid)
    doc_map = {
        "DOC01": ["Criterion:*", "Deliverable:*"], "DOC03": ["Risk:*", "Defect:*"], "DOC04": ["PH1", "PH2", "PH3", "PH4", "PH5", "ST1", "ST2", "ST3"],
        "DOC05": ["Fact:*"], "DOC06": ["Regulation:*"], "DOC07": ["M11", "S13", "D9"], "DOC08": ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "M07", "M08"],
        "DOC09": ["CP25"], "DOC10": ["CP13", "lever"], "DOC11": ["K01", "K03", "K04", "K15", "job"], "DOC12": ["Decision:*"],
        "DOC13": ["Action:*", "PlanChange:*"], "DOC14": ["Concept:*"], "DOC15": ["E05", "E07", "K03", "K04", "K05", "K12", "R11", "M10"],
        "DOC16": ["Concept:*"], "DOC18": ["Phase:*", "Deliverable:*"],
    }
    for doc, toks in doc_map.items():
        for t in toks:
            for e in expand(t, ents):
                rel(doc, "describes", e)
    return ents, rels


def validate(ents: dict, rels: list) -> list[str]:
    errs = []
    for r in rels:
        if r["s"] not in ents or r["o"] not in ents:
            errs.append(f"끝점 없음: {r['s']} -{r['p']}-> {r['o']}")
            continue
        p = PROP.get(r["p"])
        if p is None:
            errs.append(f"관계 유형 없음: {r['p']}")
            continue
        sc, oc = ents[r["s"]]["cls"], ents[r["o"]]["cls"]
        if "*" not in p["domain"] and sc not in p["domain"]:
            errs.append(f"정의역 위반: {r['s']}({sc}) -{r['p']}->")
        if "*" not in p["range"] and oc not in p["range"]:
            errs.append(f"치역 위반: -{r['p']}-> {r['o']}({oc})")
        if r["p"] == "domain" and r["sub"] not in K.DOMAIN_PRED:
            errs.append(f"도메인 술어 매핑 없음: {r['sub']}")
    seen = set()
    for r in rels:
        key = (r["s"], r["p"], r["o"], r["sub"])
        if key in seen:
            errs.append(f"관계 중복: {key}")
        seen.add(key)
    return errs


def git_log() -> list[tuple[str, str, str]]:
    try:
        out = subprocess.run(["git", "log", "--format=%h|%ad|%s", "--date=short", "--", "shopping_content_factory"],
                             cwd=ROOT.parent, capture_output=True, text=True, timeout=10).stdout
        return [tuple(line.split("|", 2)) for line in out.strip().splitlines() if line]
    except Exception:  # noqa: BLE001
        return []


def summary(ents: dict) -> dict:
    by = defaultdict(list)
    for e in ents.values():
        by[e["cls"]].append(e)
    cnt = lambda cls, st: sum(1 for e in by[cls] if e["status"] == st)  # noqa: E731
    facts = Counter(e["props"]["confidence"] for e in by["Fact"])
    tests = sum(e["props"]["count"] for e in by["Verification"] if e["label"].startswith("test_"))
    open_def = cnt("Defect", "open")
    return {
        "deliverables": {"total": len(by["Deliverable"]), "done": cnt("Deliverable", "done"), "partial": cnt("Deliverable", "partial"), "todo": cnt("Deliverable", "todo")},
        "criteria": {"total": len(by["Criterion"]), "pass": cnt("Criterion", "pass"), "caveat": cnt("Criterion", "caveat"), "fail": cnt("Criterion", "fail")},
        "decisions": {"total": len(by["Decision"]), "decided": cnt("Decision", "decided"), "pending": cnt("Decision", "pending")},
        "defects": {"total": len(by["Defect"]), "open": open_def, "fixed": cnt("Defect", "fixed"),
                    "open_defect": sum(1 for e in by["Defect"] if e["status"] == "open" and e["props"]["kind"] == "결함"),
                    "open_gap": sum(1 for e in by["Defect"] if e["status"] == "open" and e["props"]["kind"] == "설계 약점")},
        "facts": {"A": facts.get("A", 0), "B": facts.get("B", 0), "C": facts.get("C", 0)},
        "phases": {e["id"]: e["status"] for e in by["Phase"]},
        "tests": tests, "risks_high": sum(1 for e in by["Risk"] if e["props"]["level"] == "상"),
        "external_calls": 0,
    }


def headline(sm: dict) -> tuple[str, str]:
    d = sm["deliverables"]
    return ("MVP 는 끝났고, 다음 단계는 결정 대기와 미해결 결함에 막혀 있다.",
            f"산출물 {d['total']}개 중 완료 {d['done']}·부분 {d['partial']}, 결정 {sm['decisions']['decided']}/{sm['decisions']['total']}, "
            f"미해결 결함·약점 {sm['defects']['open']}건, 외부 API 실호출 {sm['external_calls']}건.")


# ---------------------------------------------------------------- RDF(Turtle)
def ttl_str(s) -> str:
    s = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{s}"@ko'


def to_ttl(ents: dict, rels: list) -> str:
    L = ["@prefix scf: <" + K.NS + "> .", "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
         "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", "@prefix owl: <http://www.w3.org/2002/07/owl#> .", "",
         "<" + K.NS.rstrip("#") + "> a owl:Ontology ; rdfs:label " + ttl_str("Shopping Content Factory 지식체계") + " .", ""]
    for cid, label, desc, _ in K.CLASSES:
        L.append(f"scf:{cid} a owl:Class ; rdfs:label {ttl_str(label)} ; rdfs:comment {ttl_str(desc)} .")
    L.append("")
    for pid, p in PROP.items():
        line = f"scf:{pid} a owl:ObjectProperty ; rdfs:label {ttl_str(p['label'])}"
        if len(p["domain"]) == 1 and p["domain"][0] != "*":
            line += f" ; rdfs:domain scf:{p['domain'][0]}"
        if len(p["range"]) == 1 and p["range"][0] != "*":
            line += f" ; rdfs:range scf:{p['range'][0]}"
        L.append(line + " .")
    for ko, en in K.DOMAIN_PRED.items():
        L.append(f"scf:{en} a owl:ObjectProperty ; rdfs:subPropertyOf scf:domain ; rdfs:label {ttl_str(ko)} .")
    for dp, label in [("status", "상태"), ("description", "설명"), ("confidence", "확인 수준"), ("level", "수준"),
                      ("kind", "종류"), ("path", "경로"), ("area", "영역"), ("maturity", "성숙도"), ("inputType", "입력 유형")]:
        L.append(f"scf:{dp} a owl:DatatypeProperty ; rdfs:label {ttl_str(label)} .")
    L.append("")
    for e in ents.values():
        parts = [f"scf:{e['id']} a scf:{e['cls']}", f"rdfs:label {ttl_str(e['label'])}"]
        if e["desc"]:
            parts.append(f"scf:description {ttl_str(e['desc'])}")
        if e["status"]:
            parts.append(f'scf:status "{e["status"]}"')
        pr = e["props"]
        for key, dp in [("confidence", "confidence"), ("level", "level"), ("kind", "kind"), ("path", "path"),
                        ("area", "area"), ("m", "maturity"), ("input", "inputType")]:
            if pr.get(key):
                parts.append(f"scf:{dp} {ttl_str(pr[key])}")
        L.append(" ;\n    ".join(parts) + " .")
    L.append("")
    for r in rels:
        pred = K.DOMAIN_PRED[r["sub"]] if r["p"] == "domain" else r["p"]
        L.append(f"scf:{r['s']} scf:{pred} scf:{r['o']} .")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- md
def md(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def kb_block(ents: dict, rels: list, rev: str) -> str:
    cls_count = Counter(e["cls"] for e in ents.values())
    prop_count = Counter(r["p"] for r in rels)
    lines = [f"생성: `python scripts/build_knowledge.py --rev {rev}` · HTML: [SCF_지식체계_REV{rev}.html](SCF_지식체계_REV{rev}.html) · "
             f"RDF: [knowledge/scf_knowledge.ttl](knowledge/scf_knowledge.ttl) · JSON: [knowledge/scf_knowledge.json](knowledge/scf_knowledge.json)", "",
             f"### 클래스 {len(K.CLASSES)}개 · 개체 {len(ents)}개", "", "| 클래스 | 이름 | 설명 | 개체 수 |", "|---|---|---|---|"]
    for cid, label, desc, _ in K.CLASSES:
        lines.append(f"| `{cid}` | **{label}** | {desc} | {cls_count[cid]} |")
    lines += ["", f"### 관계 유형 {len(PROP)}개 · 관계 {len(rels)}개 (도메인 관계 세부 술어 {len(K.DOMAIN_PRED)}종)", "",
              "| 관계 | 이름 | 주어 → 목적어 | 사용 수 |", "|---|---|---|---|"]
    for pid, p in PROP.items():
        dom = ", ".join(CLS_LABEL.get(x, "모든 클래스") for x in p["domain"])
        rng = ", ".join(CLS_LABEL.get(x, "모든 클래스") for x in p["range"])
        lines.append(f"| `{pid}` | {p['label']} | {dom} → {rng} | {prop_count[pid]} |")
    out_rel = defaultdict(list)
    for r in rels:
        out_rel[r["s"]].append(r)
    for cid, label, _, _ in K.CLASSES:
        es = [e for e in ents.values() if e["cls"] == cid]
        lines += ["", f"### {label} ({len(es)})", "", "| ID | 이름 | 상태·속성 | 주요 관계 |", "|---|---|---|---|"]
        for e in es:
            pr = e["props"]
            attr = STATUS_LABEL.get(e["status"], e["status"] or "")
            for k in ("confidence", "level", "kind"):
                if pr.get(k):
                    attr += (" · " if attr else "") + {"confidence": "확인 ", "level": "수준 ", "kind": ""}[k] + str(pr[k])
            rs = [r for r in out_rel[e["id"]] if r["p"] != "describes"][:5]
            rel_txt = "; ".join(f"{(r['sub'] or PROP[r['p']]['label'])} → {ents[r['o']]['label']}" for r in rs)
            more = len([r for r in out_rel[e["id"]] if r["p"] != "describes"]) - len(rs)
            lines.append(f"| `{e['id']}` | {md(e['label'])} | {md(attr) or '—'} | {md(rel_txt) or '—'}{f' 외 {more}' if more > 0 else ''} |")
    return "\n".join(lines)


def progress_block(ents: dict, rels: list, sm: dict, rev: str) -> str:
    h1, h2 = headline(sm)
    d, c, dec, df = sm["deliverables"], sm["criteria"], sm["decisions"], sm["defects"]
    L = [f"**{h1}** {h2}", "", f"생성: `python scripts/build_knowledge.py --rev {rev}` · 인터랙티브: [SCF_지식체계_REV{rev}.html](SCF_지식체계_REV{rev}.html) (진행 현황 탭)", "",
         "### 요약", "", "| 항목 | 값 | 비고 |", "|---|---|---|",
         f"| 산출물(요구서 16장) | 완료 {d['done']} · 부분 {d['partial']} · 미착수 {d['todo']} / {d['total']} | 부분 = 코드는 있으나 권한·품질 미완 |",
         f"| 완료 기준(요구서 17장) | 통과 {c['pass']} · 단서 {c['caveat']} · 실패 {c['fail']} / {c['total']} | 단서 = 테스트는 통과, 한계 확인됨 |",
         f"| pytest | {sm['tests']}개 통과 | 외부 호출 없음(mock) |",
         f"| 결정 | {dec['decided']} / {dec['total']} 결정 | 이번 주 7건 대기 |",
         f"| 결함·약점 | 미해결 {df['open']}(결함 {df['open_defect']} · 약점 {df['open_gap']}) · 해결 {df['fixed']} | 결함 수정은 D2 승인 대기 |",
         f"| 외부 사실 확인 수준 | A {sm['facts']['A']} · B {sm['facts']['B']} · C {sm['facts']['C']} | B·C 는 원문 재확인 필요 |",
         f"| 외부 API 실호출 | {sm['external_calls']}건 | PHASE 3 미착수 |", "",
         "### 단계", "", "| 단계 | 상태 | 내용 |", "|---|---|---|"]
    for pid, label, status, desc, parent in K.PHASES:
        indent = "　" if parent and pid.startswith("ST") else ("　· " if pid.startswith("RM") else "")
        L.append(f"| {indent}{label} | {STATUS_LABEL[status]} | {desc} |")
    L += ["", "### 산출물 20", "", "| # | 산출물 | 상태 | 메모 |", "|---|---|---|---|"]
    for did, label, status, memo, _, _ in K.DELIVERABLES:
        L.append(f"| {did} | {label} | {STATUS_LABEL[status]} | {memo} |")
    L += ["", "### 완료 기준 15", "", "| # | 기준 | 상태 | 단서 | 검증 |", "|---|---|---|---|---|"]
    for cid, label, status, caveat, verifs in K.CRITERIA:
        L.append(f"| {cid} | {label} | {STATUS_LABEL[status]} | {caveat or '—'} | {', '.join(ents[v]['label'] for v in verifs)} |")
    L += ["", "### 결정 대기", ""]
    for when_key, when_label in O.WHEN_LABEL.items():
        ds = [x for x in O.DECISIONS if x["when"] == when_key and x["id"] not in K.DECIDED]
        L.append(f"- **{when_label}** ({len(ds)}): " + " · ".join(f"{x['id']} {x['title']}" for x in ds))
    L += ["", "### 미해결 결함·약점", "", "| # | 내용 | 종류 | 해결 경로 |", "|---|---|---|---|"]
    res = defaultdict(list)
    for r in rels:
        if r["p"] == "resolvedBy":
            res[r["s"]].append(r["o"])
    for kid, label, kind, status, _, _, _ in K.DEFECTS:
        if status == "open":
            L.append(f"| {kid} | {label} | {'결함' if kind == 'defect' else '설계 약점'} | {', '.join(res[kid])} |")
    L += ["", "### 상위 리스크(상)", ""]
    for rid, label, level, _, mitig in K.RISKS:
        if level == "상":
            L.append(f"- {rid} {label} → 완화: {', '.join(mitig)}")
    L += ["", "### 원문 재확인이 필요한 사실 (확인 수준 B·C)", ""]
    L.append(" · ".join(f"{fid}({conf})" for fid, _, conf, _, _ in K.FACTS if conf in ("B", "C")) + " — 목록은 KNOWLEDGE_BASE.md '사실' 표")
    L += ["", "### 작업 기록", "", "| 날짜 | 내용 |", "|---|---|"]
    for dt, note in K.WORKLOG_NOTES:
        L.append(f"| {dt} | {note} |")
    commits = git_log()
    if commits:
        L += ["", "커밋: " + " · ".join(f"`{h}` {dt} {msg[:48]}" for h, dt, msg in commits)]
    L += ["", "### 다음 할 일", "", "| 누가 | 할 일 |", "|---|---|"]
    for who, what in K.NEXT_ACTIONS:
        L.append(f"| {who} | {what} |")
    return "\n".join(L)


def replace_block(path: Path, name: str, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    start, end = f"<!-- AUTO:{name}:START -->", f"<!-- AUTO:{name}:END -->"
    if start not in text or end not in text:
        raise SystemExit(f"{path.name} 에 {start} / {end} 표시가 없습니다")
    path.write_text(re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: f"{start}\n{body}\n{end}", text, flags=re.S),
                    encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="01")
    rev = f"{int(ap.parse_args().rev):02d}"
    ents, rels = build_graph()
    errs = validate(ents, rels)
    if errs:
        print("지식체계 오류:\n  " + "\n  ".join(errs[:40]))
        return 1
    sm = summary(ents)
    h1, h2 = headline(sm)
    payload = {
        "rev": rev, "asOf": K.AS_OF, "headline": h1, "headline2": h2,
        "classes": [{"id": c[0], "label": c[1], "desc": c[2], "group": c[3]} for c in K.CLASSES],
        "props": list(PROP.values()), "entities": list(ents.values()), "relations": rels, "summary": sm,
        "phases": [{"id": p[0], "label": p[1], "status": p[2], "desc": p[3], "parent": p[4]} for p in K.PHASES],
        "worklog": K.WORKLOG_NOTES, "commits": git_log(), "next": K.NEXT_ACTIONS, "statusLabel": STATUS_LABEL,
        "whenLabel": O.WHEN_LABEL,
    }
    out_dir = DOCS / "knowledge"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "scf_knowledge.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "scf_knowledge.ttl").write_text(to_ttl(ents, rels), encoding="utf-8")
    tpl = (ROOT / "scripts" / "knowledge_template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")).replace("/*__REV__*/", f"REV{rev}")
    out = DOCS / f"SCF_지식체계_REV{rev}.html"
    out.write_text(html, encoding="utf-8")
    replace_block(DOCS / "KNOWLEDGE_BASE.md", "KB", kb_block(ents, rels, rev))
    replace_block(DOCS / "PROGRESS.md", "PROGRESS", progress_block(ents, rels, sm, rev))
    print(f"HTML: {out.relative_to(ROOT)}")
    print(f"클래스 {len(K.CLASSES)} · 개체 {len(ents)} · 관계 유형 {len(PROP)} · 관계 {len(rels)}")
    print(h2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
