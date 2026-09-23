"""
시장 일지 · 원천 데이터 수집 (매일 1회, 2017-09~어제 전체 재추출)

실행: python journal/collect.py
확인: data/market/status.json 의 sources 가 전부 "ok" 이고,
      data/market/raw.csv 마지막 행 날짜가 어제(UTC)면 정상.

- 증분이 아니라 매일 전체를 다시 받는다 → 하루 빠져도 다음 날 자동 복구.
- 소스 하나가 실패하면 그 소스 컬럼만 직전 raw.csv 값을 유지하고 status 에 "stale"(과거값)로 남긴다.
- 품질 게이트(행 수 급감, BTC 최신일 후퇴)에 걸리면 raw.csv 를 덮어쓰지 않는다.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

# ─────────────────────────────────────────────
# 설정 (여기만 고치면 됨)
# ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "data" / "market" / "raw.csv"
SNAP_CSV = ROOT / "data" / "market" / "snapshots.csv"   # 과거 이력을 무료로 못 받는 값(도미넌스)만 매일 누적
STATUS_JSON = ROOT / "data" / "market" / "status.json"

START = "2017-09-01"

# 컬럼명: 야후 티커
YF_TICKERS = {
    "btc": "BTC-USD",
    "eth": "ETH-USD",
    "spx": "^GSPC",      # S&P500
    "ndx": "^IXIC",      # 나스닥 종합
    "rut": "^RUT",       # 러셀2000 (미국 중소형주)
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",   # 달러인덱스
    "us10y": "^TNX",     # 미 10년물 금리
    "gold": "GC=F",
    "wti": "CL=F",
    "usdkrw": "KRW=X",
    "kospi": "^KS11",
    "kosdaq": "^KQ11",   # 한국 중소형주 대용
}

# 알트 바스켓: 2017~2020년부터 거래돼 온 대형 알트 20종.
# 오늘 살아남은 코인만 골랐기 때문에 과거 성과가 실제보다 좋게 나온다(생존 편향) → 화면에 명시.
ALT_BASKET = [
    "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "TRX", "DOT", "LTC", "BCH",
    "LINK", "XLM", "AVAX", "ATOM", "ETC", "HBAR", "FIL", "ALGO", "NEAR", "AAVE",
]

CRITICAL_SOURCES = ["yahoo"]      # 이게 과거값이면 워크플로를 실패로 끝내 메일 알림을 받는다
GATE_MIN_ROW_RATIO = 0.95         # 직전 대비 행 수가 이 비율 밑으로 떨어지면 저장 중단
HTTP_TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (market-journal; +https://github.com)"}

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# 소스별 수집기: 각자 date 인덱스(YYYY-MM-DD 문자열) DataFrame 반환
# ─────────────────────────────────────────────
def fetch_yahoo() -> pd.DataFrame:
    import yfinance as yf

    cols = dict(YF_TICKERS)
    for sym in ALT_BASKET:
        cols[f"alt_{sym.lower()}"] = f"{sym}-USD"
    tickers = sorted(set(cols.values()))

    last_err = None
    for attempt in range(3):
        try:
            data = yf.download(
                tickers, start=START, interval="1d",
                auto_adjust=False, progress=False, threads=True,
            )
            close = data["Close"]
            if close.empty:
                raise RuntimeError("빈 응답")
            break
        except Exception as e:  # yfinance 는 간헐적으로 실패함
            last_err = e
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"yfinance 3회 실패: {last_err}")

    out = pd.DataFrame(index=close.index)
    for col, tk in cols.items():
        out[col] = close[tk] if tk in close.columns else float("nan")
    out.index = pd.to_datetime(out.index).strftime("%Y-%m-%d")

    # ^TNX 가 과거 방식(수익률×10)으로 오면 보정
    if out["us10y"].dropna().median() > 20:
        out["us10y"] = out["us10y"] / 10
    return out


def fetch_fng() -> pd.DataFrame:
    """alternative.me 공포탐욕지수 (2018-02~ 전체)"""
    r = requests.get("https://api.alternative.me/fng/", params={"limit": 0, "format": "json"},
                     headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    rows = r.json()["data"]
    df = pd.DataFrame({
        "date": [datetime.fromtimestamp(int(x["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d") for x in rows],
        "fng": [float(x["value"]) for x in rows],
    })
    return df.drop_duplicates("date").set_index("date")


def fetch_stablecoins() -> pd.DataFrame:
    """DefiLlama 달러 스테이블코인 총 공급 (코인시장 대기자금 대용)"""
    r = requests.get("https://stablecoins.llama.fi/stablecoincharts/all", headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    dates, vals = [], []
    for x in r.json():
        v = (x.get("totalCirculatingUSD") or {}).get("peggedUSD")
        if v is None:
            continue
        dates.append(datetime.fromtimestamp(int(x["date"]), tz=timezone.utc).strftime("%Y-%m-%d"))
        vals.append(float(v))
    df = pd.DataFrame({"date": dates, "stable_usd": vals})
    return df.drop_duplicates("date", keep="last").set_index("date")


def fetch_upbit_btc() -> pd.DataFrame:
    """업비트 KRW-BTC 일봉 종가 (김치프리미엄 계산용). 업비트 일봉은 UTC 00:00 기준이라 야후 BTC-USD 와 구간이 같다."""
    rows, to = [], None
    for _ in range(40):  # 200일 × 40 = 약 22년치 상한
        params = {"market": "KRW-BTC", "count": 200}
        if to:
            params["to"] = to
        r = requests.get("https://api.upbit.com/v1/candles/days", params=params,
                         headers={**UA, "Accept": "application/json"}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        js = r.json()
        if not js:
            break
        rows += js
        oldest = js[-1]["candle_date_time_utc"]
        if oldest[:10] <= START:
            break
        to = oldest + "Z"
        time.sleep(0.2)
    df = pd.DataFrame({
        "date": [x["candle_date_time_utc"][:10] for x in rows],
        "upbit_btc_krw": [float(x["trade_price"]) for x in rows],
    })
    return df.drop_duplicates("date").set_index("date")


def fetch_coingecko_global() -> dict:
    """오늘 값만 제공(무료 이력 없음) → snapshots.csv 에 매일 누적"""
    r = requests.get("https://api.coingecko.com/api/v3/global", headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    d = r.json()["data"]
    return {
        "btc_dom": round(float(d["market_cap_percentage"]["btc"]), 2),
        "eth_dom": round(float(d["market_cap_percentage"]["eth"]), 2),
        "total_mcap_usd": float(d["total_market_cap"]["usd"]),
    }


SOURCES = {
    # 이름: (함수, 담당 컬럼 접두/목록, 설명)
    "yahoo": (fetch_yahoo, None, "코인·지수·환율·금리 (Yahoo Finance)"),
    "fng": (fetch_fng, ["fng"], "공포탐욕지수 (alternative.me)"),
    "stablecoin": (fetch_stablecoins, ["stable_usd"], "스테이블코인 공급 (DefiLlama)"),
    "upbit": (fetch_upbit_btc, ["upbit_btc_krw"], "업비트 BTC 원화가 (김치프리미엄)"),
}


# ─────────────────────────────────────────────
# 엔진
# ─────────────────────────────────────────────
def yahoo_columns() -> list[str]:
    return list(YF_TICKERS) + [f"alt_{s.lower()}" for s in ALT_BASKET]


def load_old() -> pd.DataFrame | None:
    if RAW_CSV.exists():
        return pd.read_csv(RAW_CSV, index_col="date", dtype={"date": str})
    return None


def main() -> int:
    now = datetime.now(timezone.utc)
    old = load_old()
    frames, status = [], {}

    for name, (fn, cols, desc) in SOURCES.items():
        cols = cols or yahoo_columns()
        print(f"▶ {name}: {desc}")
        try:
            df = fn()
            df = df[[c for c in cols if c in df.columns]]
            df = df[df.index >= START]
            if df.dropna(how="all").empty:
                raise RuntimeError("유효 행 0")
            frames.append(df)
            status[name] = {"state": "ok", "desc": desc, "rows": int(df.dropna(how="all").shape[0]),
                            "max_date": str(df.dropna(how="all").index.max())}
            print(f"  ✔ {status[name]['rows']}행, 최신 {status[name]['max_date']}")
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"[:300]
            print(f"  ✖ {msg}")
            keep = [c for c in cols if old is not None and c in old.columns]
            if keep:
                frames.append(old[keep])
                status[name] = {"state": "stale", "desc": desc, "error": msg,
                                "max_date": str(old[keep].dropna(how="all").index.max())}
            else:
                status[name] = {"state": "fail", "desc": desc, "error": msg}

    # 도미넌스 스냅샷 (오늘 행 upsert)
    try:
        g = fetch_coingecko_global()
        snap = pd.read_csv(SNAP_CSV, dtype={"date": str}) if SNAP_CSV.exists() else pd.DataFrame(columns=["date"])
        today = now.strftime("%Y-%m-%d")
        snap = pd.concat([snap[snap["date"] != today], pd.DataFrame([{"date": today, **g}])], ignore_index=True)
        SNAP_CSV.parent.mkdir(parents=True, exist_ok=True)
        snap.sort_values("date").to_csv(SNAP_CSV, index=False, float_format="%.8g")
        status["coingecko"] = {"state": "ok", "desc": "BTC 도미넌스 (CoinGecko, 오늘값만 누적)", "rows": len(snap),
                               "max_date": today}
    except Exception as e:
        status["coingecko"] = {"state": "fail", "desc": "BTC 도미넌스 (CoinGecko, 오늘값만 누적)",
                               "error": f"{type(e).__name__}: {e}"[:300]}

    # 병합 + 품질 게이트
    gate = {"passed": True, "reasons": []}
    if frames:
        new = pd.concat(frames, axis=1).sort_index()
        new = new.loc[:, ~new.columns.duplicated()]
        new.index.name = "date"
        # 오늘(UTC) 행은 아직 마감 전 봉이라 버린다
        new = new[new.index < now.strftime("%Y-%m-%d")]
        new = new.dropna(how="all")
    else:
        new = pd.DataFrame()

    if new.empty or "btc" not in new.columns:
        gate["passed"] = False
        gate["reasons"].append("BTC 컬럼 없음")
    elif old is not None and len(old):
        if len(new) < len(old) * GATE_MIN_ROW_RATIO:
            gate["passed"] = False
            gate["reasons"].append(f"행 수 급감 {len(old)} → {len(new)}")
        old_max = old["btc"].dropna().index.max() if "btc" in old.columns else None
        new_max = new["btc"].dropna().index.max()
        if old_max and new_max < old_max:
            gate["passed"] = False
            gate["reasons"].append(f"BTC 최신일 후퇴 {old_max} → {new_max}")
    if not new.empty and "btc" in new.columns:
        n_btc = new["btc"].notna().sum()
        if n_btc < 1500:
            gate["passed"] = False
            gate["reasons"].append(f"BTC 이력 부족 {n_btc}행")

    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    if gate["passed"]:
        new.to_csv(RAW_CSV, float_format="%.8g")
        print(f"\n✅ raw.csv 저장: {len(new)}행 × {new.shape[1]}열, 최신 {new.index.max()}")
    else:
        print(f"\n⛔ 품질 게이트 차단, raw.csv 유지: {gate['reasons']}")
        for s in status.values():
            if s["state"] == "ok":
                s["state"] = "stale"
                s["error"] = "품질 게이트 차단으로 저장 안 됨"

    STATUS_JSON.write_text(json.dumps({
        "fetched_at_utc": now.strftime("%Y-%m-%d %H:%M"),
        "fetched_at_kst": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        "gate": gate,
        "sources": status,
        "critical": CRITICAL_SOURCES,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
