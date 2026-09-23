"""
보유 코인 설정 — collect.py / analyze.py / ingest_issue.py 가 전부 여기서 읽는다.
코인을 바꾸려면 여기 + .github/ISSUE_TEMPLATE/market-journal.yml 의 '예측 대상' 옵션(name 과 같은 글자)을 같이 고칠 것.

평단·수량은 여기 넣지 말 것. 저장소와 GitHub Pages 가 공개라서 누구나 볼 수 있다.
평단은 journal.html 의 '보유 코인' 칸에 입력하면 그 브라우저에만 저장된다.
"""

# key: raw.csv 컬럼은 hold_<key>, 일지 target 값도 이 key
HOLDINGS = {
    "re":   {"name": "리 RE",       "upbit": "KRW-RE",   "bithumb": "RE_KRW"},
    "o":    {"name": "오원 O",      "upbit": "KRW-O",    "bithumb": "O_KRW"},
    "ondo": {"name": "온도 ONDO",   "upbit": "KRW-ONDO", "bithumb": "ONDO_KRW"},
}


def col(key: str) -> str:
    return f"hold_{key}"
