# -*- coding: utf-8 -*-
"""
검사데이터 구조진단 REV01
========================
조립부 검사 데이터(구조 검사신청 등)의 스키마를 자동 진단해서
지식베이스 검증로그의 D1·D2·D7·D8 질문에 기계적으로 답을 낸다.

  D1  재검이 새 행인가 행 갱신인가            → 중복 그룹 분석으로 판정
  D2  R 사유 코드가 있는가                    → 컬럼명·값 패턴 탐색
  D7  재검 행이 원 행을 가리키는 키가 있는가  → 차수/원번호 후보 탐색  ★최우선
  D8  재검 행의 용도결정이 A로 찍히는가       → 판정 컬럼 값 분포

실행:
    py 검사데이터_구조진단_REV01.py --selftest     # 더미로 동작 확인 (엑셀 불필요)
    py 검사데이터_구조진단_REV01.py                # 아래 FILES 실데이터 진단

정상동작 확인:
    --selftest 실행 시 CASE-A는 "차수 컬럼 있음(D7 해결)", CASE-B는
    "구분 키 없음(D7 미해결)"으로 갈리면 정상.

주의: 작업자 실명·사번으로 의심되는 컬럼은 샘플값을 자동 마스킹한다.
      리포트를 사내 공유해도 개인정보가 새지 않게 하기 위함.
"""

# ══════════════════════════════════════════════════════════════════
#  설정 블록 — 여기만 고치면 된다. 아래 엔진부는 건드리지 말 것.
# ══════════════════════════════════════════════════════════════════

# 진단할 파일. 확장자는 .xls/.xlsx/.csv 아무거나. 여러 개 넣어도 됨.
FILES = [
    # r"C:\작업\구조_검사신청.xlsx",
    # r"C:\작업\용접불량률.xlsx",
]

# Fasoo DRM 걸린 파일이면 True (xlwings로 실제 Excel을 숨겨서 띄워 읽음)
USE_XLWINGS = True

# 읽을 시트. None이면 첫 시트.
SHEET = None

# 헤더가 첫 줄이 아니면 0-base 행번호 지정 (예: 3행이 헤더면 2)
HEADER_ROW = 0

# 샘플값을 마스킹할 컬럼명 조각 (개인정보 보호)
MASK_HINTS = ["성명", "이름", "작업자", "사번", "사원", "담당자", "검사원", "연락", "전화", "주민"]

# 리포트 저장 위치. None이면 스크립트와 같은 폴더.
OUT_DIR = None

# ══════════════════════════════════════════════════════════════════
#  엔진부 — 수정 불필요
# ══════════════════════════════════════════════════════════════════

import sys, re, io, itertools
from pathlib import Path
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas가 없다. 동봉한 휠로 설치할 것: pip install --no-index --find-links=./wheels pandas")

BASE = Path(__file__).resolve().parent
OUT = Path(OUT_DIR) if OUT_DIR else BASE

# 컬럼 역할 추정용 패턴
PAT = {
    "판정":   ["용도결정", "판정", "합부", "결과", "accept", "result", "판정결과"],
    "차수":   ["차수", "회차", "차", "회", "round", "seq", "순번", "재검", "rev"],
    "원번호": ["원", "모", "parent", "ref", "원번호", "원신청", "최초", "선행"],
    "신청번호": ["신청번호", "신청no", "검사번호", "문서번호", "접수번호", "id", "no"],
    "사유":   ["사유", "원인", "내용", "지적", "비고", "reason", "cause", "remark"],
    "일자":   ["일자", "일시", "날짜", "date", "신청일", "검사일", "완료일"],
    "호선":   ["호선", "선번", "ship", "hull"],
    "블럭":   ["블럭", "블록", "block"],
    "부위":   ["부위", "위치", "조인트", "이음", "joint", "seam", "포지션"],
    "검사종류": ["검사종류", "검사구분", "종류", "구분", "type"],
}
ACCEPT_TOKENS = {"A", "ACC", "ACCEPT", "합격", "OK", "P", "PASS"}
REJECT_TOKENS = {"R", "REJ", "REJECT", "불합격", "NG", "F", "FAIL", "재검"}


def _norm(s):
    return re.sub(r"[\s_\-\.\(\)\[\]/]", "", str(s)).lower()


def guess_role(colname):
    n = _norm(colname)
    hits = []
    for role, keys in PAT.items():
        for k in keys:
            if _norm(k) and _norm(k) in n:
                hits.append(role)
                break
    return hits


def mask_needed(colname):
    n = _norm(colname)
    return any(_norm(h) in n for h in MASK_HINTS)


def sample_values(sr, col, k=5):
    vals = sr.dropna().unique()[:k]
    if mask_needed(col):
        return [f"<마스킹:{len(str(v))}자>" for v in vals]
    out = []
    for v in vals:
        s = str(v)
        out.append(s if len(s) <= 24 else s[:24] + "…")
    return out


# ────────────────────────── 읽기 ──────────────────────────

def read_xlwings(path, sheet, header_row):
    """DRM 보호 파일용. 숨긴 별도 인스턴스에서 read-only로 열고 반드시 종료."""
    import xlwings as xw
    app = None
    try:
        app = xw.App(visible=False, add_book=False)
        app.display_alerts = False
        app.screen_updating = False
        bk = app.books.open(str(path), read_only=True, update_links=False)
        ws = bk.sheets[sheet] if sheet is not None else bk.sheets[0]
        vals = ws.used_range.value
        bk.close()
        if not vals:
            return pd.DataFrame()
        head = vals[header_row]
        body = vals[header_row + 1:]
        cols = [str(c) if c is not None else f"col{i}" for i, c in enumerate(head)]
        return pd.DataFrame(body, columns=cols)
    finally:
        if app is not None:
            try:
                app.quit()
            except Exception:
                pass


def read_plain(path, sheet, header_row):
    p = Path(path)
    if p.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
            try:
                return pd.read_csv(p, encoding=enc, header=header_row, dtype=str)
            except UnicodeDecodeError:
                continue
        raise RuntimeError("CSV 인코딩 판별 실패 (utf-8-sig/cp949/euc-kr 모두 실패)")
    # .xls ↔ .xlsx 자동 토글
    cands = [p]
    alt = p.with_suffix(".xlsx" if p.suffix.lower() == ".xls" else ".xls")
    if alt != p:
        cands.append(alt)
    last = None
    for c in cands:
        if not c.exists():
            continue
        try:
            return pd.read_excel(c, sheet_name=sheet or 0, header=header_row, dtype=object)
        except Exception as e:
            last = e
    raise RuntimeError(f"읽기 실패: {p} / {last}")


def load(path):
    if USE_XLWINGS:
        try:
            return read_xlwings(path, SHEET, HEADER_ROW), "xlwings(COM)"
        except Exception as e:
            print(f"  ! xlwings 실패({type(e).__name__}) → 일반 읽기로 재시도")
    return read_plain(path, SHEET, HEADER_ROW), "pandas"


# ────────────────────────── 진단 ──────────────────────────

def find_verdict_col(df):
    """값에 A/R 계열이 몰려 있는 컬럼을 판정 컬럼으로 추정."""
    best, best_score = None, 0.0
    for c in df.columns:
        sr = df[c].dropna().astype(str).str.strip().str.upper()
        if sr.empty or sr.nunique() > 12:
            continue
        hit = sr.isin(ACCEPT_TOKENS | REJECT_TOKENS).mean()
        bonus = 0.15 if "판정" in guess_role(c) else 0.0
        if hit + bonus > best_score:
            best, best_score = c, hit + bonus
    return (best, round(best_score, 3)) if best_score >= 0.5 else (None, round(best_score, 3))


def find_identity_cols(df):
    """한 검사 '부위'를 특정할 만한 컬럼 조합 후보."""
    want = ["호선", "블럭", "부위", "검사종류"]
    found = []
    for w in want:
        for c in df.columns:
            if w in guess_role(c) and c not in found:
                found.append(c)
                break
    return found


def dup_analysis(df, id_cols, verdict_col):
    """같은 부위가 여러 행으로 나뉘는지 = 재검이 새 행인지."""
    if not id_cols:
        return {"판정": "식별 컬럼을 못 찾아 분석 불가", "id_cols": []}
    key = df[id_cols].astype(str).agg("|".join, axis=1)
    vc = key.value_counts()
    multi = vc[vc > 1]
    res = {
        "id_cols": id_cols,
        "고유부위": int(vc.size),
        "2행이상부위": int(multi.size),
        "중복비율": round(float(multi.size) / vc.size, 4) if vc.size else 0.0,
        "최대반복": int(vc.max()) if vc.size else 0,
    }
    if verdict_col is not None and multi.size:
        grp = df.assign(_k=key)
        sub = grp[grp["_k"].isin(multi.index)]
        v = sub[verdict_col].astype(str).str.strip().str.upper()
        mixed = sub.assign(_v=v).groupby("_k")["_v"].nunique()
        res["중복부위중_판정이섞인비율"] = round(float((mixed > 1).mean()), 4)
    res["판정"] = ("재검이 별도 행으로 쌓이는 구조로 보임"
                   if res["중복비율"] > 0.001 else
                   "중복 행이 거의 없음 — 행 갱신 방식이거나 식별 컬럼이 부족")
    return res


def diagnose(df, name, source):
    L = []
    w = L.append
    w("=" * 70)
    w(f"■ {name}")
    w(f"  읽기: {source} · {len(df):,}행 × {len(df.columns)}열")
    w("=" * 70)

    # 1) 컬럼 인벤토리
    w("\n[1] 컬럼 인벤토리")
    w(f"  {'컬럼':<22}{'결측%':>7}{'고유':>8}  역할추정 / 샘플")
    w("  " + "-" * 66)
    for c in df.columns:
        sr = df[c]
        miss = round(float(sr.isna().mean()) * 100, 1)
        roles = guess_role(c)
        tag = ("," .join(roles)) if roles else "-"
        w(f"  {str(c)[:21]:<22}{miss:>7}{sr.nunique(dropna=True):>8}  {tag} {sample_values(sr, c, 3)}")

    # 2) 판정 컬럼 (D8)
    vcol, score = find_verdict_col(df)
    w("\n[2] 판정(용도결정) 컬럼 — D8")
    if vcol:
        dist = df[vcol].astype(str).str.strip().str.upper().value_counts()
        w(f"  → '{vcol}' (A/R 토큰 일치도 {score})")
        for k, v in dist.head(10).items():
            kind = "합격" if k in ACCEPT_TOKENS else ("불합격" if k in REJECT_TOKENS else "기타★")
            w(f"     {k:<12} {v:>8,}  {kind}")
        others = [k for k in dist.index if k not in ACCEPT_TOKENS | REJECT_TOKENS]
        if others:
            w(f"  ★ A/R 외 값 {len(others)}종 존재 → 분모 정의 재확인 필요: {others[:6]}")
        else:
            w("  ✔ 값이 A/R 계열로만 구성 → 재검 행도 같은 코드계를 쓴다고 볼 수 있음 (D8 해결)")
    else:
        w(f"  ✖ 판정 컬럼 자동 탐지 실패 (최고 일치도 {score}) → 수동 지정 필요")

    # 3) 차수/원번호 키 (D7) ★
    w("\n[3] 재검 구분 키 — D7 ★최우선")
    cand_round = [c for c in df.columns if "차수" in guess_role(c)]
    cand_ref = [c for c in df.columns if "원번호" in guess_role(c)]
    cand_no = [c for c in df.columns if "신청번호" in guess_role(c)]
    w(f"  차수/회차 후보 : {cand_round or '없음'}")
    w(f"  원번호 참조 후보: {cand_ref or '없음'}")
    w(f"  신청번호 후보  : {cand_no or '없음'}")
    for c in cand_round:
        u = df[c].dropna().unique()[:10]
        w(f"    · '{c}' 값 예시: {list(u)}")
    if cand_round or cand_ref:
        w("  ✔ D7 해결 가능 — 위 컬럼으로 1차/재검 분리 가능 → 1차 R률 산출 가능")
    else:
        w("  ✖ D7 미해결 — 차수·원번호 컬럼 없음.")
        w("     → 1차 R률을 셀 수 없고, 지식문서 9-1절 '98% ≈ 1차 R률 2.04%' 해석을 검증할 수 없다.")
        w("     → 대안: 같은 부위 안에서 검사일자 순서로 1차/재검을 추정(아래 [5] 참조).")

    # 4) R 사유 (D2)
    w("\n[4] R 사유 코드 — D2")
    cand_reason = [c for c in df.columns if "사유" in guess_role(c)]
    if cand_reason:
        for c in cand_reason:
            nun = df[c].nunique(dropna=True)
            kind = "코드성(분류 가능)" if nun <= 50 else "자유기술(분류에 NLP 필요)"
            w(f"  · '{c}' 고유값 {nun}종 → {kind}")
        w("  ✔ 사전경고 모델 피처로 쓸 수 있음")
    else:
        w("  ✖ 사유 컬럼 없음 → R 원인 분석·사전경고 모델 피처 확보 불가")

    # 5) 중복 구조 (D1 재확인)
    w("\n[5] 부위 식별 및 중복 구조 — D1 재확인")
    idc = find_identity_cols(df)
    da = dup_analysis(df, idc, vcol)
    w(f"  식별 컬럼 조합: {da.get('id_cols') or '탐지 실패'}")
    if da.get("id_cols"):
        w(f"  고유 부위 {da['고유부위']:,}건 중 2행 이상 {da['2행이상부위']:,}건 "
          f"({da['중복비율']*100:.2f}%) · 최대 {da['최대반복']}회")
        if "중복부위중_판정이섞인비율" in da:
            w(f"  중복 부위 중 판정이 섞인(R→A) 비율 {da['중복부위중_판정이섞인비율']*100:.1f}%")
        w(f"  → {da['판정']}")
        if da["중복비율"] > 0:
            w(f"  ※ 추정 1차 R률 상한 = 중복비율 {da['중복비율']*100:.2f}% "
              f"(차수 컬럼 없을 때의 근사. 목표 98%의 임계 2.04%와 비교)")

    # 5-1) 지표 실측
    if vcol is not None:
        v = df[vcol].astype(str).str.strip().str.upper()
        a, r = int(v.isin(ACCEPT_TOKENS).sum()), int(v.isin(REJECT_TOKENS).sum())
        if a + r:
            rate = a / (a + r) * 100
            w(f"\n  ▸ 당일검사완료율 실측 = A {a:,} / (A {a:,} + R {r:,}) = {rate:.2f}%")
            w(f"    이 분모는 '검사 부위 수'가 아니라 '검사 시행 횟수'다 (재검 = 별도 행).")
            w(f"    목표 98% 환산 임계: 1차 R률 2.04% 이하. 현재 R/A = {r/a*100:.2f}%"
              f" → {'달성' if rate >= 98 else '미달'}")

    # 6) 신선도
    w("\n[6] 데이터 신선도")
    dcols = [c for c in df.columns if "일자" in guess_role(c)]
    if dcols:
        for c in dcols[:4]:
            s = pd.to_datetime(df[c], errors="coerce")
            if s.notna().any():
                w(f"  · {c}: {s.min():%Y-%m-%d} ~ {s.max():%Y-%m-%d} (유효 {s.notna().mean()*100:.1f}%)")
    else:
        w("  ✖ 일자 컬럼 없음 → 신선도 판정 불가")

    # 7) 요약
    w("\n[7] 검증로그 자동 회신안")
    w(f"  D1 : {'새 행으로 쌓임 (확인됨)' if da.get('중복비율', 0) > 0 else '판단 보류 — 식별 컬럼 부족'}")
    w(f"  D2 : {'사유 컬럼 있음 → ' + str(cand_reason) if cand_reason else '사유 컬럼 없음'}")
    w(f"  D7 : {'구분 키 있음 → ' + str(cand_round + cand_ref) if (cand_round or cand_ref) else '구분 키 없음 (★해결 필요)'}")
    w(f"  D8 : {'A/R 계열로만 구성' if vcol and not [k for k in df[vcol].astype(str).str.strip().str.upper().unique() if k not in ACCEPT_TOKENS | REJECT_TOKENS] else 'A/R 외 값 존재 또는 탐지 실패'}")
    w("")
    return "\n".join(L)


# ────────────────────────── 자가 테스트 ──────────────────────────

def make_dummy(with_round_col):
    """검사 데이터 모사. 부위 200건 중 7건이 1차 R 후 재검 합격 (1차 R률 3.5%)."""
    import random
    random.seed(7)
    rows = []
    for i in range(200):
        blk = f"B{i//10:03d}"
        part = f"J{i:04d}"
        rejected = i % 33 == 0            # 약 6건
        if rejected:
            rows.append({"검사일자": "2026-09-03", "호선": "H2601", "블럭": blk, "부위": part,
                         "검사종류": "취부", "용도결정": "R", "지적사유": "루트갭 과대",
                         "검사차수": 1, "작업자명": "홍길동", "사번": "12345678"})
            rows.append({"검사일자": "2026-09-07", "호선": "H2601", "블럭": blk, "부위": part,
                         "검사종류": "취부", "용도결정": "A", "지적사유": None,
                         "검사차수": 2, "작업자명": "홍길동", "사번": "12345678"})
        else:
            rows.append({"검사일자": "2026-09-03", "호선": "H2601", "블럭": blk, "부위": part,
                         "검사종류": "취부", "용도결정": "A", "지적사유": None,
                         "검사차수": 1, "작업자명": "홍길동", "사번": "12345678"})
    df = pd.DataFrame(rows)
    if not with_round_col:
        df = df.drop(columns=["검사차수"])
    return df


def selftest():
    print("자가 테스트 — 더미 데이터로 진단 로직 확인 (실데이터·엑셀 불필요)\n")
    reports = []
    for label, flag in (("CASE-A 차수 컬럼 있음", True), ("CASE-B 차수 컬럼 없음", False)):
        rep = diagnose(make_dummy(flag), f"[더미] {label}", "selftest")
        print(rep)
        reports.append(rep)
    a_ok = "D7 해결 가능" in reports[0]
    b_ng = "D7 미해결" in reports[1]
    print("=" * 70)
    print(f"자가 테스트 결과: CASE-A D7해결={a_ok} / CASE-B D7미해결={b_ng} "
          f"→ {'정상' if (a_ok and b_ng) else '★비정상 — 로직 점검 필요'}")
    return 0 if (a_ok and b_ng) else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if not FILES:
        print("FILES가 비어 있다. 스크립트 상단 설정 블록에 파일 경로를 넣거나 --selftest로 실행할 것.")
        return 1
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    parts = [f"검사데이터 구조진단 · 생성 {datetime.now():%Y-%m-%d %H:%M}\n"]
    for f in FILES:
        try:
            df, src = load(f)
            parts.append(diagnose(df, Path(f).name, src))
        except Exception as e:
            parts.append(f"{'='*70}\n■ {Path(f).name}\n  ✖ 실패: {type(e).__name__}: {e}\n")
    text = "\n".join(parts)
    print(text)
    out = OUT / f"구조진단리포트_{stamp}.txt"
    out.write_text(text, encoding="utf-8")
    print(f"\n리포트 저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
