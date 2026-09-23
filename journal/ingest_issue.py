"""
GitHub 이슈 폼(.github/ISSUE_TEMPLATE/market-journal.yml)으로 쓴 일지를 JSON 으로 저장.
워크플로(journal-entry.yml)가 호출한다. 이슈 본문은 환경변수로만 받는다(스크립트 인젝션 방지).

실행(로컬 테스트):
  ISSUE_NUMBER=1 ISSUE_CREATED_AT=2026-09-24T00:30:00Z ISSUE_BODY="$(cat sample.md)" python journal/ingest_issue.py
확인: data/journal/entries/<날짜>_<이슈번호>.json 생성되고, 마지막 줄에 ENTRY_ID=... 가 찍히면 정상.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_DIR = Path(os.environ.get("JOURNAL_ENTRIES_DIR", ROOT / "data" / "journal" / "entries"))

# 이슈 폼 라벨 → 키. 폼 라벨을 바꾸면 여기도 같이 바꿀 것.
LABELS = {
    "오늘 시장 느낌 (내 심리)": "mood",
    "오늘 본 이슈 (글로벌·매크로·코인)": "issues",
    "예측 대상": "target",
    "예측 방향": "direction",
    "예측 기간": "horizon",
    "확신도": "confidence",
    "근거 한 줄": "reason",
    "오늘 한 행동": "action",
    "행동 메모": "action_note",
    "태그": "tags",
    "날짜 (비우면 오늘)": "date",
}
TARGET_MAP = {"BTC": "btc", "ETH": "eth", "알트바스켓": "alt", "나스닥": "ndx",
              "러셀2000": "rut", "코스피": "kospi", "코스닥": "kosdaq"}
DIR_MAP = {"상승": "up", "하락": "down", "횡보": "flat"}
ACTIONS = {"관망", "매수", "매도", "비중 확대", "비중 축소"}
LATE_EDIT_HOURS = 24          # 작성 후 이 시간 넘어 고치면 적중률 집계에서 제외
EMPTY = {"", "_No response_", "None"}


def parse_sections(body: str) -> dict:
    out, cur, buf = {}, None, []
    for line in body.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1), []
        else:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def fail(msg: str) -> int:
    print(f"ERROR={msg}")
    Path(os.environ.get("COMMENT_OUT", "comment.md")).write_text(
        f"⚠ 일지를 저장하지 못했습니다: {msg}\n\n이슈를 수정하면 다시 처리됩니다.\n", encoding="utf-8")
    return 1


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    number = int(os.environ.get("ISSUE_NUMBER", "0"))
    created = datetime.fromisoformat(os.environ["ISSUE_CREATED_AT"].replace("Z", "+00:00"))
    updated_raw = os.environ.get("ISSUE_UPDATED_AT")
    updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00")) if updated_raw else created

    sec = parse_sections(body)
    v = {}
    for label, key in LABELS.items():
        val = sec.get(label, "").strip()
        v[key] = "" if val in EMPTY else val

    try:
        mood = int(v["mood"].split()[0])
        assert 1 <= mood <= 5
    except Exception:
        return fail(f"'오늘 시장 느낌' 값이 이상함: {v['mood']!r}")
    if v["target"] not in TARGET_MAP:
        return fail(f"'예측 대상' 값이 이상함: {v['target']!r}")
    if v["direction"] not in DIR_MAP:
        return fail(f"'예측 방향' 값이 이상함: {v['direction']!r}")
    try:
        horizon = int(v["horizon"].replace("일", ""))
        assert horizon in (7, 30)
        conf = int(v["confidence"].replace("%", ""))
        assert conf in (50, 60, 70, 80, 90)
    except Exception:
        return fail("'예측 기간' 또는 '확신도' 값이 이상함")
    if v["action"] not in ACTIONS:
        return fail(f"'오늘 한 행동' 값이 이상함: {v['action']!r}")
    if not v["reason"]:
        return fail("'근거 한 줄'이 비어 있음")

    # 기준일 = 작성 시점에 마감된 마지막 UTC 일봉 (KST 09:00 이전 작성이면 그 전날)
    backdated = False
    if v["date"]:
        try:
            base = datetime.strptime(v["date"], "%Y-%m-%d").date()
        except ValueError:
            return fail(f"날짜 형식은 YYYY-MM-DD: {v['date']!r}")
        auto_base = (created.astimezone(timezone.utc) - timedelta(days=1)).date()
        backdated = base < auto_base
    else:
        base = (created.astimezone(timezone.utc) - timedelta(days=1)).date()

    tags = [t.strip().lstrip("#") for t in re.split(r"[,\s]+", v["tags"]) if t.strip()][:10]
    entry = {
        "id": f"{base.isoformat()}_{number}",
        "issue": number,
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_date": base.isoformat(),
        "mood": mood,
        "issues": v["issues"][:2000],
        "target": TARGET_MAP[v["target"]],
        "direction": DIR_MAP[v["direction"]],
        "horizon": horizon,
        "confidence": conf,
        "reason": v["reason"][:300],
        "action": v["action"],
        "action_note": v["action_note"][:1000],
        "tags": tags,
        "backdated": backdated,
        "edited_late": (updated - created).total_seconds() > LATE_EDIT_HOURS * 3600,
    }

    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    for old in ENTRIES_DIR.glob(f"*_{number}.json"):   # 날짜를 고쳐 수정한 경우 옛 파일 제거
        old.unlink()
    (ENTRIES_DIR / f"{entry['id']}.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ENTRY_ID={entry['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
