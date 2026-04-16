import requests
import json
import os
from datetime import datetime

STOCKS = {
    "삼성전자":      "005930",
    "SK하이닉스":    "000660",
    "LG에너지솔루션": "373220",
    "NAVER":        "035420",
    "현대차":        "005380",
    "카카오":        "035720",
}

def fetch_prices(code):
    url = f"https://m.stock.naver.com/api/stock/{code}/price"
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        return res.json()
    except:
        return None

def fetch_history(code):
    url = f"https://m.stock.naver.com/api/stock/{code}/candle/day?count=65"
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        return res.json()
    except:
        return []

def calc_returns(candles):
    if not candles:
        return {}
    current = candles[0].get("closePrice", 0)
    def pct(days):
        if len(candles) > days:
            base = candles[days].get("closePrice", 0)
            if base:
                return round((current - base) / base * 100, 2)
        return None
    return {
        "current":     current,
        "weekly":      pct(4),
        "monthly":     pct(19),
        "three_month": pct(59),
    }

def main():
    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stocks": {}
    }

    for name, code in STOCKS.items():
        print(f"▶ {name} ({code}) 수집 중...")
        candles = fetch_history(code)

        if not candles:
            print(f"  [경고] 데이터 없음")
            continue

        prices = []
        for c in candles[:65]:
            try:
                prices.append({
                    "date":   c.get("localDate", ""),
                    "close":  c.get("closePrice", 0),
                    "open":   c.get("openPrice", 0),
                    "high":   c.get("highPrice", 0),
                    "low":    c.get("lowPrice", 0),
                    "volume": c.get("accumulatedTradingVolume", 0),
                })
            except:
                continue

        result["stocks"][code] = {
            "name":    name,
            "code":    code,
            "returns": calc_returns(candles),
            "prices":  prices,
        }
        print(f"  ✔ {len(prices)}일 치 수집 완료")

    os.makedirs("data", exist_ok=True)
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n✅ 저장 완료!")

if __name__ == "__main__":
    main()
