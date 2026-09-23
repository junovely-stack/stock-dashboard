# stock-dashboard

| 페이지 | 내용 | 갱신 |
|---|---|---|
| `index.html` | 국내 6종목 시세·수익률 | 평일 KST 10:10 (`scrape.yml`) |
| `journal.html` | **시장 일지 · 복기** — 코인·매크로 10개 지표 구간, 과거 같은 구간일 때 이후 수익률, 내 예측 자동 채점 | 매일 KST 09:20 (`market-journal.yml`) + 일지 쓸 때 |

## 시장 일지 · 복기

- 계획·한계·처음 켜는 법: [`docs/PLAN.md`](docs/PLAN.md)
- Claude에 줄 프롬프트(프로젝트 정의 / 매일·매주 복기): [`docs/PROMPT.md`](docs/PROMPT.md)

```
journal/collect.py        수집 (Yahoo·alternative.me·DefiLlama·Upbit·CoinGecko, 2017~ 전체 재추출)
journal/analyze.py        구간 통계·비슷했던 날·일지 채점 → data/journal/dashboard.json, briefing.md
journal/ingest_issue.py   이슈 폼 일지 → data/journal/entries/*.json
journal/holdings.py       보유 코인 목록 (평단은 넣지 말 것 — 페이지에서 브라우저에만 저장)
.github/ISSUE_TEMPLATE/market-journal.yml   30초 일지 입력 폼
```

로컬 실행: `pip install yfinance pandas requests` → `python journal/collect.py && python journal/analyze.py`
→ 콘솔에 "현재 상태" 표가 찍히고 `data/journal/dashboard.json` 이 생기면 정상.
