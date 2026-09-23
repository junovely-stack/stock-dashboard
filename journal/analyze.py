"""
시장 일지 · 분석 (네트워크 안 씀)
  raw.csv + 일지(entries/*.json) → data/journal/dashboard.json, data/journal/briefing.md

실행: python journal/analyze.py
확인: 콘솔에 "현재 상태" 표와 "비슷했던 날 n일"이 찍히고 data/journal/dashboard.json 이 갱신되면 정상.

원칙
- 숫자 계산은 전부 여기서 한다. LLM(Claude)은 briefing.md 를 읽고 해석만 한다.
- "예측값"이 아니라 "과거에 이 상태였을 때 이후 수익률 분포"를 낸다. 반드시 기저율(아무 조건 없을 때)과 같이 본다.
- 매일 겹치는 구간이라 30일 수익률 표본 300일은 독립 표본 ≈ 10개다. eff(=n/기간)를 항상 같이 낸다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = Path(os.environ.get("JOURNAL_RAW_CSV", ROOT / "data" / "market" / "raw.csv"))
SNAP_CSV = ROOT / "data" / "market" / "snapshots.csv"
STATUS_JSON = ROOT / "data" / "market" / "status.json"
ENTRIES_DIR = Path(os.environ.get("JOURNAL_ENTRIES_DIR", ROOT / "data" / "journal" / "entries"))
OUT_JSON = Path(os.environ.get("JOURNAL_OUT_JSON", ROOT / "data" / "journal" / "dashboard.json"))
OUT_BRIEF = OUT_JSON.with_name("briefing.md")

HORIZONS = [7, 30]

# key: (raw 컬럼, 표시명, 종류)  — 종류 stock 은 거래일에만 표본으로 쓴다
TARGETS = {
    "btc": ("btc", "BTC", "coin"),
    "eth": ("eth", "ETH", "coin"),
    "alt": ("alt_idx", "알트바스켓", "coin"),
    "ndx": ("ndx", "나스닥", "stock"),
    "rut": ("rut", "러셀2000", "stock"),
    "kospi": ("kospi", "코스피", "stock"),
    "kosdaq": ("kosdaq", "코스닥", "stock"),
}

INF = float("inf")
# 구간 경계는 [이상, 미만). 값 바꾸면 모든 통계가 다시 계산된다.
INDICATORS = [
    dict(key="alt_breadth", name="알트 강도", unit="%", digits=0,
         desc="알트 20종 중 최근 90일 수익률이 BTC보다 좋은 비율 (75% 이상 = 알트시즌 기준)",
         bins=[-INF, 25, 50, 75, INF], labels=["BTC 시즌 (<25)", "BTC 우위 (25~49)", "알트 우위 (50~74)", "알트시즌 (75+)"]),
    dict(key="fng", name="공포탐욕지수", unit="", digits=0,
         desc="alternative.me Crypto Fear & Greed",
         bins=[-INF, 25, 45, 56, 75, INF], labels=["극공포 (<25)", "공포 (25~44)", "중립 (45~55)", "탐욕 (56~74)", "극탐욕 (75+)"]),
    dict(key="btc_trend", name="BTC 200일선 괴리", unit="%", digits=1,
         desc="BTC 가격이 200일 이동평균보다 몇 % 위/아래인지",
         bins=[-INF, -20, 0, 30, 60, INF], labels=["-20% 아래", "200일선 아래", "200일선 위", "+30% 이상", "+60% 과열"]),
    dict(key="ethbtc", name="ETH/BTC 30일 변화", unit="%", digits=1,
         desc="ETH가 BTC 대비 강해지는지 (알트 선행 신호로 자주 쓰임)",
         bins=[-INF, -10, 10, INF], labels=["ETH 약세 (<-10%)", "보합", "ETH 강세 (>+10%)"]),
    dict(key="dxy", name="달러인덱스 4주 변화", unit="%", digits=1,
         desc="DXY 28일 변화율. 달러 강세 = 위험자산 역풍",
         bins=[-INF, -1.5, 1.5, INF], labels=["달러 약세 (<-1.5%)", "보합", "달러 강세 (>+1.5%)"]),
    dict(key="us10y", name="미 10년물 4주 변화", unit="bp", digits=0,
         desc="28일간 금리 변화(bp)",
         bins=[-INF, -25, 25, INF], labels=["금리 하락 (<-25bp)", "보합", "금리 상승 (>+25bp)"]),
    dict(key="vix", name="VIX", unit="", digits=1,
         desc="미국 주식 변동성 지수",
         bins=[-INF, 15, 20, 30, INF], labels=["안정 (<15)", "보통 (15~20)", "불안 (20~30)", "공포 (30+)"]),
    dict(key="stable", name="스테이블코인 30일 증감", unit="%", digits=1,
         desc="달러 스테이블코인 총 공급 변화 = 코인시장 대기자금 유입/유출",
         bins=[-INF, -1, 1, 3, INF], labels=["감소 (<-1%)", "정체", "증가 (1~3%)", "급증 (3%+)"]),
    dict(key="kimchi", name="김치 프리미엄", unit="%", digits=1,
         desc="업비트 BTC 원화가 ÷ (BTC 달러가 × 환율) - 1. 국내 개인 과열도",
         bins=[-INF, 0, 3, 6, INF], labels=["역프 (<0)", "보통 (0~3)", "과열 (3~6)", "과열 심함 (6+)"]),
    dict(key="smallcap", name="러셀2000/S&P 90일 상대", unit="%", digits=1,
         desc="미국 중소형주가 대형주보다 강한지",
         bins=[-INF, -3, 3, INF], labels=["대형주 우위", "비슷", "중소형주 우위"]),
]

# "지금과 비슷했던 날" 조건. 표본이 모자라면 뒤에서부터 하나씩 뺀다.
ANALOG_KEYS = ["alt_breadth", "fng", "btc_trend", "dxy"]
ANALOG_MIN_DAYS = 60          # BTC 30일 결과가 있는 날이 이보다 적으면 조건 완화

# 일지 채점: |수익률| 이 이 값(%) 이내면 "횡보"
FLAT_BAND = {"coin": {7: 3.0, 30: 8.0}, "stock": {7: 1.5, 30: 4.0}}

FFILL_LIMIT = 5               # 주말·휴장 메우기 한도(일)
STALE_DAYS = 7                # 지표 최신값이 이보다 오래되면 "과거값"
THIN_EFF, REF_EFF = 5, 10     # 독립 표본 기준: <5 표본 부족, <10 참고용

KST = timezone(timedelta(hours=9))
DIR_KO = {"up": "상승", "down": "하락", "flat": "횡보"}


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────
def r1(x, d=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return int(round(float(x))) if d == 0 else round(float(x), d)


def clean(o):
    """JSON 직렬화용: NaN/inf → None, numpy → python"""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not math.isfinite(float(o)) else float(o)
    return o


def dist(s: pd.Series, h: int) -> dict:
    s = s.dropna()
    n = int(len(s))
    if n == 0:
        return {"n": 0}
    q = s.quantile([0.1, 0.5, 0.9])
    return {"n": n, "eff": r1(n / h), "med": r1(q[0.5]), "mean": r1(s.mean()),
            "up": r1((s > 0).mean() * 100, 0), "p10": r1(q[0.1]), "p90": r1(q[0.9])}


def tier(d: dict) -> str:
    eff = (d or {}).get("eff") or 0
    return "thin" if eff < THIN_EFF else "ref" if eff < REF_EFF else "ok"


def dstr(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────
# 1) 피처 · 미래수익률
# ─────────────────────────────────────────────
def build(raw: pd.DataFrame):
    df = raw.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().asfreq("D")
    px = df.ffill(limit=FFILL_LIMIT)

    def col(name):
        return px[name] if name in px.columns else pd.Series(np.nan, index=px.index)

    # 알트 바스켓 (동일가중, 코인이 상장되는 시점부터 편입)
    alt_cols = [c for c in px.columns if c.startswith("alt_")]
    if alt_cols:
        r = px[alt_cols].pct_change(fill_method=None)
        cnt = r.notna().sum(axis=1)
        basket = r.mean(axis=1).where(cnt >= 5)
        first = basket.first_valid_index()
        idx = (1 + basket.fillna(0)).cumprod() * 100
        if first is None:
            idx[:] = np.nan
        else:
            idx[idx.index < first] = np.nan
        px["alt_idx"] = idx

        ret90 = px[alt_cols] / px[alt_cols].shift(90) - 1
        btc90 = col("btc") / col("btc").shift(90) - 1
        valid = ret90.notna() & btc90.notna().to_numpy()[:, None]
        beats = ret90.gt(btc90, axis=0) & valid
        n = valid.sum(axis=1)
        alt_breadth = (beats.sum(axis=1) / n.replace(0, np.nan) * 100).where(n >= 10)
    else:
        px["alt_idx"] = np.nan
        alt_breadth = pd.Series(np.nan, index=px.index)

    f = pd.DataFrame(index=px.index)
    f["alt_breadth"] = alt_breadth
    f["fng"] = col("fng")
    f["btc_trend"] = (col("btc") / col("btc").rolling(200, min_periods=200).mean() - 1) * 100
    ethbtc = col("eth") / col("btc")
    f["ethbtc"] = (ethbtc / ethbtc.shift(30) - 1) * 100
    f["dxy"] = (col("dxy") / col("dxy").shift(28) - 1) * 100
    f["us10y"] = (col("us10y") - col("us10y").shift(28)) * 100
    f["vix"] = col("vix")
    f["stable"] = (col("stable_usd") / col("stable_usd").shift(30) - 1) * 100
    f["kimchi"] = (col("upbit_btc_krw") / (col("btc") * col("usdkrw")) - 1) * 100
    rs = col("rut") / col("spx")
    f["smallcap"] = (rs / rs.shift(91) - 1) * 100

    fwd = {}
    for key, (c, _, kind) in TARGETS.items():
        s = px[c] if c in px.columns else pd.Series(np.nan, index=px.index)
        for h in HORIZONS:
            fr = (s.shift(-h) / s - 1) * 100
            if kind == "stock" and c in df.columns:
                fr = fr.where(df[c].notna())       # 휴장일 중복 표본 제거
            fwd[(key, h)] = fr
    return df, px, f, fwd


def bucketize(f: pd.DataFrame) -> pd.DataFrame:
    codes = pd.DataFrame(index=f.index)
    for ind in INDICATORS:
        codes[ind["key"]] = pd.cut(f[ind["key"]], bins=ind["bins"], labels=False, right=False)
    return codes


# ─────────────────────────────────────────────
# 2) 지표별 구간 통계 + 현재 상태
# ─────────────────────────────────────────────
def indicator_stats(f, codes, fwd, latest):
    out = []
    for ind in INDICATORS:
        k = ind["key"]
        s = f[k].loc[:latest]
        last_valid = s.last_valid_index()
        cur = None
        if last_valid is not None:
            v = float(s.loc[last_valid])
            b = codes[k].loc[last_valid]
            cur = {"value": r1(v, ind["digits"]), "date": dstr(last_valid),
                   "bucket": None if pd.isna(b) else int(b),
                   "stale": (latest - last_valid).days > STALE_DAYS}
        has = f[k].notna()
        base = {t: {str(h): dist(fwd[(t, h)][has], h) for h in HORIZONS} for t in TARGETS}
        buckets = []
        for i, label in enumerate(ind["labels"]):
            m = codes[k] == i
            buckets.append({"label": label, "n_days": int(m.sum()),
                            "stats": {t: {str(h): dist(fwd[(t, h)][m], h) for h in HORIZONS} for t in TARGETS}})
        first = f[k].first_valid_index()
        out.append({"key": k, "name": ind["name"], "unit": ind["unit"], "desc": ind["desc"],
                    "labels": ind["labels"], "since": dstr(first) if first is not None else None,
                    "current": cur, "base": base, "buckets": buckets})
    return out


# ─────────────────────────────────────────────
# 3) 지금과 비슷했던 날
# ─────────────────────────────────────────────
def analog(f, codes, fwd, inds, latest):
    cur = {i["key"]: i["current"] for i in inds}
    names = {i["key"]: i for i in inds}
    keys = [k for k in ANALOG_KEYS if cur.get(k) and cur[k]["bucket"] is not None and not cur[k]["stale"]]
    unusable = [k for k in ANALOG_KEYS if k not in keys]
    used, dropped = list(keys), []
    mask = pd.Series(False, index=f.index)
    while used:
        mask = pd.Series(True, index=f.index)
        for k in used:
            mask &= codes[k] == cur[k]["bucket"]
        if fwd[("btc", 30)][mask].notna().sum() >= ANALOG_MIN_DAYS or len(used) == 1:
            break
        dropped.insert(0, used.pop())
    if not used:
        return {"available": False, "reason": "현재 값이 있는 조건 지표가 없음"}

    has_all = pd.Series(True, index=f.index)
    for k in used:
        has_all &= f[k].notna()

    stats = {t: {str(h): dist(fwd[(t, h)][mask], h) for h in HORIZONS} for t in TARGETS}
    base = {t: {str(h): dist(fwd[(t, h)][has_all], h) for h in HORIZONS} for t in TARGETS}

    # 에피소드: 10일 넘게 끊기면 다른 구간
    days = f.index[mask.fillna(False).to_numpy()]
    episodes = []
    if len(days):
        start = prev = days[0]
        for d in list(days[1:]) + [None]:
            if d is None or (d - prev).days > 10:
                seg = mask.loc[start:prev]
                seg_idx = seg[seg].index
                episodes.append({
                    "start": dstr(start), "end": dstr(prev), "days": int(len(seg_idx)),
                    "ongoing": (latest - prev).days <= 1,
                    "btc30": r1(fwd[("btc", 30)].loc[seg_idx].median()),
                    "alt30": r1(fwd[("alt", 30)].loc[seg_idx].median()),
                })
                if d is not None:
                    start = d
            if d is not None:
                prev = d
    episodes.sort(key=lambda e: e["start"], reverse=True)

    return {
        "available": True,
        "conditions": [{"key": k, "name": names[k]["name"], "label": names[k]["labels"][cur[k]["bucket"]],
                        "value": cur[k]["value"], "unit": names[k]["unit"]} for k in used],
        "dropped": [{"key": k, "name": names[k]["name"],
                     "label": names[k]["labels"][cur[k]["bucket"]]} for k in dropped],
        "unusable": [{"key": k, "name": names[k]["name"]} for k in unusable],
        "n_days": int(mask.sum()), "n_episodes": len(episodes),
        "stats": stats, "base": base, "episodes": episodes,
    }


# ─────────────────────────────────────────────
# 4) 차트용 시계열
# ─────────────────────────────────────────────
def series(px, f, latest):
    full = pd.DataFrame({"btc": px["btc"] if "btc" in px else np.nan,
                         "alt_idx": px.get("alt_idx"),
                         "alt_breadth": f["alt_breadth"],
                         "fng": f["fng"], "fng7": f["fng"].rolling(7, min_periods=3).mean(),
                         "kimchi": f["kimchi"], "btc_trend": f["btc_trend"]}).loc[:latest]
    first = full["btc"].first_valid_index()
    full = full.loc[first:] if first is not None else full
    weekly = full.iloc[::-7].iloc[::-1]                 # 최신일 포함 7일 간격
    recent = full.iloc[-180:]

    def pack(d, cols):
        o = {"date": [dstr(x) for x in d.index]}
        for c in cols:
            o[c] = [r1(v, 2) for v in d[c]]
        return o
    return {"weekly": pack(weekly, ["btc", "alt_breadth", "fng7"]),
            "recent": pack(recent, ["btc", "alt_idx", "alt_breadth", "fng", "kimchi"])}


# ─────────────────────────────────────────────
# 5) 일지 채점
# ─────────────────────────────────────────────
def load_entries() -> list[dict]:
    out = []
    if ENTRIES_DIR.exists():
        for p in sorted(ENTRIES_DIR.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception as e:
                print(f"  [경고] 일지 파일 읽기 실패 {p.name}: {e}")
    return out


def grade(entries, px, f, codes, fwd, latest):
    graded = []
    for e in entries:
        g = dict(e)
        t = e.get("target")
        h = int(e.get("horizon") or 0)
        if t not in TARGETS or h not in HORIZONS:
            g["status"] = "invalid"
            graded.append(g)
            continue
        c, tname, kind = TARGETS[t]
        s = px[c] if c in px.columns else pd.Series(dtype=float)
        base = pd.Timestamp(e["base_date"])
        end = base + timedelta(days=h)
        g["target_name"] = tname
        g["due_date"] = dstr(end)
        g["band"] = FLAT_BAND[kind][h]
        g["counts"] = not (e.get("backdated") or e.get("edited_late"))

        hist = s.loc[:base].dropna()
        if hist.empty:
            g["status"] = "no_data"
            graded.append(g)
            continue
        p0 = float(hist.iloc[-1])
        if latest < end:
            now = s.loc[:latest].dropna()
            g["status"] = "pending"
            g["ret_so_far"] = r1((float(now.iloc[-1]) / p0 - 1) * 100) if len(now) else None
            g["days_left"] = int((end - latest).days)
        else:
            p1 = float(s.loc[:end].dropna().iloc[-1])
            ret = (p1 / p0 - 1) * 100
            band = FLAT_BAND[kind][h]
            actual = "up" if ret > band else "down" if ret < -band else "flat"
            hit = actual == e.get("direction")
            conf = (e.get("confidence") or 50) / 100
            g.update(status="graded", ret=r1(ret), actual=actual, hit=bool(hit),
                     brier=r1((conf - (1 if hit else 0)) ** 2, 3))

        # 복기용: 기록 시점 시장 상태
        ctx = {}
        for ind in INDICATORS:
            k = ind["key"]
            v = f[k].loc[:base].dropna()
            if len(v) and (base - v.index[-1]).days <= STALE_DAYS:
                b = codes[k].loc[v.index[-1]]
                ctx[k] = {"value": r1(float(v.iloc[-1]), ind["digits"]),
                          "label": None if pd.isna(b) else ind["labels"][int(b)]}
        g["context"] = ctx
        b30 = fwd[("btc", 30)].get(base) if base in fwd[("btc", 30)].index else None
        g["btc_fwd30"] = r1(b30) if b30 is not None and pd.notna(b30) else None
        graded.append(g)

    graded.sort(key=lambda x: (x.get("base_date", ""), x.get("issue", 0)), reverse=True)

    scored = [g for g in graded if g.get("status") == "graded" and g.get("counts")]
    summary = {
        "total": len(graded),
        "pending": sum(1 for g in graded if g.get("status") == "pending"),
        "graded": len(scored),
        "excluded": sum(1 for g in graded if g.get("status") == "graded" and not g.get("counts")),
        "hits": sum(1 for g in scored if g["hit"]),
    }
    summary["hit_rate"] = r1(summary["hits"] / len(scored) * 100, 0) if scored else None
    summary["brier"] = r1(np.mean([g["brier"] for g in scored]), 3) if scored else None

    calib = []
    for c in (50, 60, 70, 80, 90):
        grp = [g for g in scored if int(g.get("confidence") or 0) == c]
        calib.append({"conf": c, "n": len(grp),
                      "hit_rate": r1(sum(g["hit"] for g in grp) / len(grp) * 100, 0) if grp else None})

    by_mood = []
    for m in range(1, 6):
        grp = [g for g in graded if g.get("mood") == m and g.get("btc_fwd30") is not None and g.get("counts", True)]
        vals = [g["btc_fwd30"] for g in grp]
        by_mood.append({"mood": m, "n": len(vals),
                        "btc30_med": r1(float(np.median(vals))) if vals else None,
                        "up": r1(sum(v > 0 for v in vals) / len(vals) * 100, 0) if vals else None})
    return {"summary": summary, "calibration": calib, "by_mood": by_mood, "entries": graded}


# ─────────────────────────────────────────────
# 6) 브리핑 텍스트 (Claude 에 붙여넣는 용)
# ─────────────────────────────────────────────
def fmt_d(d):
    if not d or not d.get("n"):
        return "표본 없음"
    warn = " ⚠표본부족" if tier(d) == "thin" else " (참고)" if tier(d) == "ref" else ""
    return (f"중앙값 {d['med']:+.1f}% · 상승확률 {d['up']:.0f}% · p10~p90 {d['p10']:+.1f}~{d['p90']:+.1f}% "
            f"· n={d['n']}(독립≈{d['eff']:.0f}){warn}")


def briefing(dash) -> str:
    L = []
    st = dash.get("status") or {}
    L.append(f"# 시장 일지 브리핑 — 데이터 기준 {dash['data_through']} (UTC 일봉)")
    L.append(f"생성 {dash['generated_at_kst']} KST · 수집 {st.get('fetched_at_kst', '?')} KST")
    bad = [f"{k}({v['state']})" for k, v in (st.get("sources") or {}).items() if v.get("state") != "ok"]
    L.append("소스 상태: " + ("전부 정상" if not bad else "⚠ " + ", ".join(bad) + " → 해당 값은 과거값/없음"))
    L.append("")
    L.append("## 현재 상태 (지표 · 구간 · 이 구간일 때 BTC 30일 / 알트바스켓 30일 · 기저율)")
    for ind in dash["indicators"]:
        c = ind["current"]
        if not c or c["bucket"] is None:
            L.append(f"- {ind['name']}: 값 없음 (연동 대기)")
            continue
        b = ind["buckets"][c["bucket"]]["stats"]
        stale = " ⚠과거값" if c["stale"] else ""
        L.append(f"- {ind['name']} = {c['value']}{ind['unit']} [{ind['labels'][c['bucket']]}] ({c['date']}){stale}")
        L.append(f"  - BTC 30일: {fmt_d(b['btc']['30'])} | 기저 {fmt_d(ind['base']['btc']['30'])}")
        L.append(f"  - 알트 30일: {fmt_d(b['alt']['30'])} | 기저 {fmt_d(ind['base']['alt']['30'])}")
    a = dash["analog"]
    L.append("")
    if a.get("available"):
        conds = " & ".join(f"{c['name']}={c['label']}" for c in a["conditions"])
        L.append(f"## 지금과 비슷했던 날: {conds}")
        if a["dropped"]:
            L.append("  (표본 부족으로 뺀 조건: " + ", ".join(f"{d['name']}={d['label']}" for d in a["dropped"]) + ")")
        L.append(f"  {a['n_days']}일, {a['n_episodes']}개 구간")
        for t, (_, tn, _) in TARGETS.items():
            for h in HORIZONS:
                L.append(f"  - {tn} {h}일: {fmt_d(a['stats'][t][str(h)])} | 기저 상승확률 {a['base'][t][str(h)].get('up')}%")
        L.append("  최근 구간: " + "; ".join(
            f"{e['start']}~{e['end']}({e['days']}일, BTC30 {e['btc30']}%, 알트30 {e['alt30']}%)" for e in a["episodes"][:6]))
    j = dash["journal"]
    s = j["summary"]
    L.append("")
    L.append(f"## 내 일지: 총 {s['total']}건 · 진행중 {s['pending']} · 채점 {s['graded']} · 적중률 {s['hit_rate']}% · Brier {s['brier']}")
    for e in j["entries"][:10]:
        res = (f"→ 실제 {e.get('ret')}% {DIR_KO.get(e.get('actual'), '')} {'적중' if e.get('hit') else '빗나감'}"
               if e.get("status") == "graded" else
               f"→ 진행중 (현재 {e.get('ret_so_far')}%, {e.get('days_left')}일 남음)" if e.get("status") == "pending" else "")
        L.append(f"- {e.get('base_date')} 느낌 {e.get('mood')}/5 · {e.get('target_name')} {e.get('horizon')}일 "
                 f"{DIR_KO.get(e.get('direction'), '?')} {e.get('confidence')}% · 근거: {e.get('reason', '')} {res}")
    L.append("")
    L.append("※ 과거 통계는 예측이 아니라 기저율이다. 알트바스켓은 현재 살아남은 20종 기준(생존 편향). "
             "겹치는 구간이라 독립 표본은 n/기간 수준.")
    return "\n".join(L) + "\n"


# ─────────────────────────────────────────────
# 7) 이슈 댓글 (일지 접수 확인)
# ─────────────────────────────────────────────
def issue_comment(dash, entry_id) -> str:
    e = next((x for x in dash["journal"]["entries"] if x.get("id") == entry_id), None)
    if not e:
        return f"일지 `{entry_id}` 를 찾지 못했습니다."
    t, h = e["target"], str(e["horizon"])
    L = [f"✅ 일지 기록됨 — 기준일 **{e['base_date']}** (UTC 일봉 종가 기준), 채점일 **{e.get('due_date')}**", ""]
    L.append(f"- 예측: **{e.get('target_name')} {e['horizon']}일 {DIR_KO[e['direction']]}** · 확신 {e['confidence']}% "
             f"(횡보 기준 ±{e.get('band')}%)")
    if e.get("backdated"):
        L.append("- ⚠ 날짜를 지정해 과거로 기록 → 적중률 집계에서 제외")
    a = dash["analog"]
    if a.get("available"):
        d, b = a["stats"][t][h], a["base"][t][h]
        conds = " & ".join(f"{c['name']} {c['label']}" for c in a["conditions"])
        L.append(f"- 지금과 비슷했던 날({conds}, {a['n_days']}일): {e.get('target_name')} {h}일 {fmt_d(d)}")
        L.append(f"- 조건 없는 기저율: 상승확률 {b.get('up')}% · 중앙값 {b.get('med')}%")
    L.append("")
    names = {i["key"]: i["name"] for i in INDICATORS}
    L.append("기록 시점 상태: " + " · ".join(f"{names.get(k, k)} {v['label']}" for k, v in (e.get("context") or {}).items()))
    return "\n".join(L) + "\n"


# ─────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--comment", help="이 일지 id 의 이슈 댓글 본문을 --comment-out 에 쓴다")
    ap.add_argument("--comment-out", default="comment.md")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    status = json.loads(STATUS_JSON.read_text(encoding="utf-8")) if STATUS_JSON.exists() else {}

    if not RAW_CSV.exists():
        dash = {"ready": False, "generated_at_kst": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
                "repo": os.environ.get("GITHUB_REPOSITORY"), "status": status,
                "message": "raw.csv 없음 — Actions 에서 'Market Journal' 워크플로를 한 번 수동 실행하세요."}
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(clean(dash), ensure_ascii=False), encoding="utf-8")
        print("raw.csv 없음 → 빈 dashboard.json 작성")
        return 0

    raw = pd.read_csv(RAW_CSV, index_col="date")
    df, px, f, fwd = build(raw)
    codes = bucketize(f)
    latest = df["btc"].last_valid_index()

    inds = indicator_stats(f, codes, fwd, latest)
    ana = analog(f, codes, fwd, inds, latest)
    journal = grade(load_entries(), px, f, codes, fwd, latest)

    snap = None
    if SNAP_CSV.exists():
        sdf = pd.read_csv(SNAP_CSV)
        if len(sdf):
            snap = sdf.iloc[-1].to_dict()

    dash = {
        "ready": True,
        "generated_at_kst": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        "repo": os.environ.get("GITHUB_REPOSITORY"),
        "data_through": dstr(latest),
        "status": status,
        "config": {"horizons": HORIZONS,
                   "targets": [{"key": k, "name": v[1], "kind": v[2]} for k, v in TARGETS.items()],
                   "flat_band": FLAT_BAND, "thin_eff": THIN_EFF, "ref_eff": REF_EFF,
                   "analog_keys": ANALOG_KEYS, "analog_min_days": ANALOG_MIN_DAYS},
        "prices": {k: r1(px[v[0]].loc[:latest].dropna().iloc[-1], 2) if v[0] in px and px[v[0]].loc[:latest].notna().any() else None
                   for k, v in TARGETS.items()},
        "snapshot": snap,
        "indicators": inds,
        "analog": ana,
        "series": series(px, f, latest),
        "journal": journal,
    }
    dash = clean(dash)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(dash, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    OUT_BRIEF.write_text(briefing(dash), encoding="utf-8")

    print(f"데이터 기준 {dash['data_through']} · 일지 {journal['summary']['total']}건")
    print("현재 상태")
    for ind in inds:
        c = ind["current"]
        lab = ind["labels"][c["bucket"]] if c and c["bucket"] is not None else "값 없음"
        print(f"  {ind['name']:<18} {'' if not c else c['value']}{ind['unit']:<3} {lab}")
    if ana.get("available"):
        print(f"비슷했던 날 {ana['n_days']}일 / {ana['n_episodes']}구간: "
              + " & ".join(c["label"] for c in ana["conditions"]))
    print(f"✅ {OUT_JSON.relative_to(ROOT) if OUT_JSON.is_relative_to(ROOT) else OUT_JSON}")

    if args.comment:
        Path(args.comment_out).write_text(issue_comment(dash, args.comment), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
