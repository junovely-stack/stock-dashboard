import yfinance as yf
import json
import os
from datetime import datetime

# 종목코드 뒤에 .KS = 코스피, .KQ = 코스닥
STOCKS = {
    "삼성전자":      "005930.KS",
    "SK하이닉스":    "000660.KS",
    "LG에너지솔루션": "373220.KS",
    "NAVER":        "035420.KS",
    "현대차":        "005380.KS",
    "카카오":        "035720.KS",
}

def calc_returns(prices):
    if not prices:
        return {}
    current = prices[0]["close"]
    def pct(days):
        if len(prices) > days and prices[days]["close"]:
            base = prices[days]["close"]
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

    for name, ticker in STOCKS.items():
        code = ticker.replace(".KS", "").replace(".KQ", "")
        print(f"▶ {name} ({ticker}) 수집 중...")
        try:
            df = yf.download(ticker, period="4mo", interval="1d", progress=False)
            if df.empty:
                print(f"  [경고] 데이터 없음")
                continue

            df = df.sort_index(ascending=False)
            prices = []
            for date, row in df.iterrows():
                try:
                    prices.append({
                        "date":   date.strftime("%Y.%m.%d"),
                        "close":  int(row["Close"].iloc[0] if hasattr(row["Close"], 'iloc') else row["Close"]),
                        "open":   int(row["Open"].iloc[0] if hasattr(row["Open"], 'iloc') else row["Open"]),
                        "high":   int(row["High"].iloc[0] if hasattr(row["High"], 'iloc') else row["High"]),
                        "low":    int(row["Low"].iloc[0] if hasattr(row["Low"], 'iloc') else row["Low"]),
                        "volume": int(row["Volume"].iloc[0] if hasattr(row["Volume"], 'iloc') else row["Volume"]),
                    })
                except:
                    continue

            result["stocks"][code] = {
                "name":    name,
                "code":    code,
                "returns": calc_returns(prices),
                "prices":  prices[:65],
            }
            print(f"  ✔ {len(prices[:65])}일 치 수집 완료")

        except Exception as e:
            print(f"  [오류] {e}")

    os.makedirs("data", exist_ok=True)
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n✅ 저장 완료!")

if __name__ == "__main__":
    main()
