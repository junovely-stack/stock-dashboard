import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

# ─────────────────────────────────────────────
# ✏️  원하는 종목 코드를 여기서 수정하세요
# ─────────────────────────────────────────────
STOCKS = {
    "삼성전자":     "005930",
    "SK하이닉스":   "000660",
    "LG에너지솔루션": "373220",
    "NAVER":       "035420",
    "현대차":       "005380",
    "카카오":       "035720",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com",
}


def fetch_daily_prices(code: str, pages: int = 5) -> list[dict]:
    """네이버 금융 일별 시세 페이지를 크롤링해 OHLCV 리스트 반환"""
    prices = []
    for page in range(1, pages + 1):
        url = (
            f"https://finance.naver.com/item/sise_day.nhn"
            f"?code={code}&page={page}"
        )
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            res.encoding = "euc-kr"
        except requests.RequestException as e:
            print(f"  [오류] {code} page {page}: {e}")
            break

        soup = BeautifulSoup(res.text, "html.parser")
        rows = soup.select("table.type2 tr")

        for row in rows:
            cols = row.select("td")
            if len(cols) < 7:
                continue

            texts = [c.text.strip().replace(",", "") for c in cols]
            date_str = texts[0]
            if not date_str or not date_str[0].isdigit():
                continue

            try:
                prices.append({
                    "date":   date_str,
                    "close":  int(texts[1]),
                    "diff":   int(texts[2]) if texts[2] not in ("", "-") else 0,
                    "open":   int(texts[3]),
                    "high":   int(texts[4]),
                    "low":    int(texts[5]),
                    "volume": int(texts[6]),
                })
            except (ValueError, IndexError):
                continue

    return prices


def calc_returns(prices: list[dict]) -> dict:
    """주간 / 월간 / 3개월 수익률 계산"""
    if not prices:
        return {}

    current = prices[0]["close"]

    def pct(days: int) -> float | None:
        if len(prices) > days:
            base = prices[days]["close"]
            return round((current - base) / base * 100, 2)
        return None

    return {
        "current":     current,
        "weekly":      pct(4),   # 5 거래일
        "monthly":     pct(19),  # ~20 거래일
        "three_month": pct(59),  # ~60 거래일
    }


def main():
    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stocks":     {},
    }

    for name, code in STOCKS.items():
        print(f"▶ {name} ({code}) 크롤링 중...")
        prices = fetch_daily_prices(code, pages=4)

        if not prices:
            print(f"  [경고] 데이터 없음. 건너뜀.")
            continue

        result["stocks"][code] = {
            "name":    name,
            "code":    code,
            "returns": calc_returns(prices),
            "prices":  prices[:65],   # 최근 65 거래일만 보관
        }
        print(f"  ✔ {len(prices[:65])}일 치 수집 완료")

    os.makedirs("data", exist_ok=True)
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n✅ data/stocks.json 저장 완료")


if __name__ == "__main__":
    main()
