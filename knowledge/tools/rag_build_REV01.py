# -*- coding: utf-8 -*-
"""
RAG 코퍼스 빌더 REV01
=====================
원본(= knowledge/rag/chunks/*.md + 용어사전 CSV)에서 다음을 생성한다.

  knowledge/rag/corpus_REVxx.jsonl      ← RAG 인제스트용. 전처리 없이 그대로 쓴다.
  knowledge/조선소_조립공정_지식_REVxx.md ← 사람이 읽는 통합본 (생성물. 직접 고치지 말 것)

청크 파일 형식 (YAML 프론트매터 + 본문, 외부 라이브러리 불필요):
  ---
  id: flow-01
  title: ...
  chapter: 1
  chapter_title: 전체 흐름
  order: 1
  type: 메커니즘 | 개념 | 설비 | 데이터 | 지표 | 안전 | 용어 | 확인대기 | 사내확정 | 출처
  grade: E | G | C | ?
  aliases:
    - 관련어
  questions:
    - 이 청크가 답하는 질문
  related:
    - 다른 청크 id
  ---
  본문 (표는 통째로. "N절 참조" 같은 교차참조 금지 — 필요한 요지는 여기에 다시 쓴다)

실행:  py rag_build_REV01.py            (knowledge/ 아래에서 경로 자동 탐색)
확인:  마지막 줄에 "검증 통과 · 청크 N개" 가 나오면 정상. 오류가 있으면 파일명과 이유를 출력하고 종료코드 1.
"""
import sys, re, io, json, csv
from pathlib import Path
from collections import Counter, defaultdict

# ══════════════ 설정 ══════════════
REV       = "REV05"                 # 통합본·코퍼스 파일명에 붙는 리비전
AS_OF     = "2026-10"               # 코퍼스 기준월
BODY_WARN = 900                     # 본문 글자수 경고 임계
BODY_MAX  = 1500                    # 본문 글자수 상한 (초과 시 오류)
GRADE_TEXT = {
    "E": "외부검증(E) — 공개 자료 2건 이상으로 교차 확인된 내용이다.",
    "G": "업계통용(G) — 업계에서 일반적으로 통하지만 출처가 단일하거나 구두 전승이다. 사내 문서에 쓸 때 한 번 확인할 것.",
    "C": "사내확정(C) — 담당자가 확인한 사내 사실이다. 확인일은 본문에 있다.",
    "?": "확인 대기(?) — 야드·과·시스템마다 다른 사내 고유값으로 아직 확인되지 않았다. 이 값을 추정하거나 지어내지 말고 '확인 필요'라고 답할 것.",
}
TYPES = {"메커니즘","개념","설비","데이터","지표","안전","용어","확인대기","사내확정","출처"}
# ══════════════════════════════════

BASE = Path(__file__).resolve().parent.parent          # knowledge/
CHUNK_DIR = BASE / "rag" / "chunks"
OUT_JSONL = BASE / "rag" / f"corpus_{REV}.jsonl"
OUT_MD    = BASE / f"조선소_조립공정_지식_{REV}.md"
GLOSS     = sorted(BASE.glob("용어사전_조립공정_REV*.csv"))[-1]


def parse_front(text, fname):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{fname}: 프론트매터(---) 없음")
    meta, body = {}, m.group(2).strip()
    cur = None
    for line in m.group(1).split("\n"):
        if not line.strip():
            continue
        if re.match(r"^\s+-\s", line):
            if cur is None:
                raise ValueError(f"{fname}: 리스트 항목이 키 없이 등장: {line}")
            meta.setdefault(cur, []).append(line.split("-", 1)[1].strip())
        else:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v == "" or v == "[]":
                cur = k if v == "" else None
                meta[k] = []
            else:
                cur = None; meta[k] = v
    return meta, body


def load_chunks():
    chunks, errs = [], []
    for f in sorted(CHUNK_DIR.glob("*.md")):
        try:
            meta, body = parse_front(io.open(f, encoding="utf-8").read(), f.name)
            for req in ("id","title","chapter","chapter_title","order","type","grade"):
                if req not in meta: errs.append(f"{f.name}: '{req}' 없음")
            if meta.get("type") not in TYPES: errs.append(f"{f.name}: type '{meta.get('type')}' 미정의")
            if meta.get("grade") not in GRADE_TEXT: errs.append(f"{f.name}: grade '{meta.get('grade')}' 미정의")
            if meta.get("id") != f.stem: errs.append(f"{f.name}: id '{meta.get('id')}'가 파일명과 다름")
            n = len(body)
            if n > BODY_MAX: errs.append(f"{f.name}: 본문 {n}자 — 상한 {BODY_MAX} 초과, 청크를 나눌 것")
            elif n > BODY_WARN: print(f"  ! {f.name}: 본문 {n}자 (경고 {BODY_WARN})")
            if re.search(r"[0-9]+-[0-9]+절|[0-9]+장 참조|검증로그 [A-F][0-9]+|부록 [AB]", body):
                errs.append(f"{f.name}: 교차참조 표현 발견 — 요지를 본문에 직접 쓸 것")
            if re.search(r"\[[EGC?]\]", body):
                errs.append(f"{f.name}: 본문에 [E]/[G]/[C]/[?] 약식 표기 — 문장으로 풀어 쓸 것 (등급은 프론트매터)")
            meta["_body"] = body; meta["_file"] = f.name
            chunks.append(meta)
        except Exception as e:
            errs.append(str(e))
    return chunks, errs


def load_terms():
    rows = list(csv.DictReader(io.open(GLOSS, encoding="utf-8-sig")))
    out = []
    for i, r in enumerate(rows, 1):
        g = r["검증등급"].strip()
        body = (f"{r['용어']} ({r['한자/영문']})\n\n"
                f"뜻: {r['정의']}\n\n"
                f"분류: {r['분류']} · 관련 공종: {r['관련공종']}")
        out.append({
            "id": f"term-{i:03d}", "title": f"용어 — {r['용어']}",
            "chapter": "11", "chapter_title": "용어사전", "order": str(i),
            "type": "용어", "grade": g if g in GRADE_TEXT else "G",
            "aliases": [a.strip() for a in re.split(r"\s*/\s*", r["한자/영문"]) if a.strip()],
            "questions": [f"{r['용어']}이 뭐야", f"{r['용어']} 뜻"],
            "related": [], "_body": body, "_file": GLOSS.name,
        })
    return out


def render_text(c):
    """임베딩·검색에 들어갈 최종 텍스트: 본문 + 등급 문장 + 관련어 + 답하는 질문."""
    parts = [f"# {c['title']}", "", c["_body"], "", f"근거 등급: {GRADE_TEXT[c['grade']]}"]
    if c.get("aliases"):   parts.append("관련어: " + " · ".join(c["aliases"]))
    if c.get("questions"): parts.append("이 항목이 답하는 질문: " + " / ".join(c["questions"]))
    return "\n".join(parts)


def main():
    print(f"청크 디렉터리: {CHUNK_DIR}")
    chunks, errs = load_chunks()
    ids = [c["id"] for c in chunks]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup: errs.append(f"id 중복: {dup}")
    idset = set(ids)
    for c in chunks:
        for r in c.get("related", []):
            if r not in idset: errs.append(f"{c['_file']}: related '{r}' 없음")
    if errs:
        print("\n".join("✖ " + e for e in errs)); return 1

    terms = load_terms()
    allc = chunks + terms
    allc.sort(key=lambda c: (int(c["chapter"]), int(c["order"])))

    # ── JSONL
    with io.open(OUT_JSONL, "w", encoding="utf-8") as f:
        for c in allc:
            rec = {
                "id": c["id"], "title": c["title"],
                "chapter": int(c["chapter"]), "chapter_title": c["chapter_title"],
                "type": c["type"], "grade": c["grade"],
                "rev": REV, "as_of": AS_OF,
                "aliases": c.get("aliases", []), "questions": c.get("questions", []),
                "related": c.get("related", []),
                "text": render_text(c),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ── 통합본 (사람용)
    L = [f"# 조선소 조립공정 지식 — {REV}", "",
         f"> **생성물이다. 직접 고치지 말 것.** 원본은 `rag/chunks/*.md`와 `{GLOSS.name}`이고, `tools/rag_build_REV01.py`로 다시 만든다.",
         f"> 기준월 {AS_OF} · 청크 {len(chunks)}개 + 용어 {len(terms)}개 · 등급: E 외부검증 / G 업계통용 / C 사내확정 / ? 확인대기", ""]
    bych = defaultdict(list)
    for c in allc: bych[(int(c["chapter"]), c["chapter_title"])].append(c)
    for (n, t), cs in sorted(bych.items()):
        L += [f"## {n}. {t}", ""]
        if n == 11:
            L += ["| 용어 | 한자/영문 | 뜻 | 등급 |", "|---|---|---|---|"]
            for c in cs:
                first = c["_body"].split("\n")[0]
                term, _, rest = first.partition(" (")
                L.append(f"| {term} | {rest.rstrip(')')} | {c['_body'].split('뜻: ')[1].split(chr(10))[0]} | {c['grade']} |")
            L.append(""); continue
        for c in cs:
            L += [f"### {c['title']}  `{c['id']}` · 등급 {c['grade']}", "", c["_body"], ""]
            if c.get("aliases"): L.append(f"*관련어: {' · '.join(c['aliases'])}*")
            L.append("")
    io.open(OUT_MD, "w", encoding="utf-8").write("\n".join(L))

    # ── 통계
    g = Counter(c["grade"] for c in chunks); t = Counter(c["type"] for c in chunks)
    print(f"본문 청크 {len(chunks)}개  등급 {dict(g)}")
    print(f"유형 {dict(t)}")
    print(f"용어 청크 {len(terms)}개")
    print(f"→ {OUT_JSONL.name}  ({OUT_JSONL.stat().st_size:,} bytes)")
    print(f"→ {OUT_MD.name}")
    print(f"검증 통과 · 청크 {len(allc)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
