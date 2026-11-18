"""모의 트렌드 데이터 — 실데이터 아님(confidence=mock).

data/mock/trend_keywords.json 의 형태 정의(base·slope·spike)로 35일치 시계열을 만든다.
같은 날짜에는 같은 값이 나오도록 키워드+날짜로 시드를 고정한다.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

from adapters.base import TrendRecord
from app.models import Confidence


class MockTrendAdapter:
    name = "mock_trends"

    def __init__(self, spec_path: Path):
        self.spec = json.loads(spec_path.read_text(encoding="utf-8"))

    def is_configured(self) -> bool:
        return True

    @staticmethod
    def _series(spec: dict, run_date: date, days: int = 35) -> list[dict]:
        seed = int(hashlib.sha256(f"{spec['keyword']}|{run_date}".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        end = run_date - timedelta(days=1)
        out = []
        for i in range(days):
            d = end - timedelta(days=days - 1 - i)
            value = spec["base"] + spec.get("slope", 0) * i
            if spec.get("spike") and i >= days - spec["spike"]["days"]:
                value *= spec["spike"]["mult"]
            if d.weekday() >= 5:
                value *= spec.get("weekend", 1.0)
            value *= 1 + rng.uniform(-0.08, 0.08)
            out.append({"period": d.isoformat(), "ratio": round(max(value, 0.1), 3)})
        return out

    def collect(self, run_date: date, raw_dir: Path) -> list[TrendRecord]:
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "mock_trends.json"
        records, raw = [], []
        for spec in self.spec["keywords"]:
            series = self._series(spec, run_date)
            raw.append({"keyword": spec["keyword"], "series": series})
            records.append(TrendRecord(keyword=spec["keyword"], category_key=spec.get("category"), series=series,
                                       source=self.name, confidence=Confidence.MOCK,
                                       source_url="mock://data/mock/trend_keywords.json", raw_ref=str(raw_path)))
        raw_path.write_text(json.dumps({"note": "MOCK DATA — 실데이터 아님", "items": raw}, ensure_ascii=False,
                                       indent=1), encoding="utf-8")
        return records
