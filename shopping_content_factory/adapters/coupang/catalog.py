"""후보 상품 공급 어댑터.

- MockCatalogAdapter: data/mock/products_demo.json (DEMO 상품, 실재하지 않음)
- ManualCatalogAdapter: data/manual/products.json (사람이 확인한 상품을 직접 입력, 실운영 초기 경로)
- CoupangSearchCatalog: 쿠팡파트너스 검색 API (키가 있을 때만)

쿠팡 API 키가 없는 초기에는 상품 탐색이 '수동 입력 + 자동 평가'가 된다. 무단 크롤링으로 메우지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

from adapters.base import ProductCandidate
from adapters.coupang.partners import CoupangPartnersAdapter, map_search_item


def _to_candidate(row: dict, source_type: str, is_demo: bool) -> ProductCandidate:
    return ProductCandidate(
        id=row["id"],
        name=row["name"],
        category_key=row["category_key"],
        keywords=row.get("keywords", []),
        price=row.get("price"),
        data=row,
        source_type=source_type,
        source_url=row.get("source_url"),
        is_demo=is_demo,
    )


class MockCatalogAdapter:
    name = "mock_catalog"

    def __init__(self, path: Path):
        self.path = path

    def is_configured(self) -> bool:
        return self.path.exists()

    def candidates(self, keywords: list[str]) -> list[ProductCandidate]:
        rows = json.loads(self.path.read_text(encoding="utf-8"))["products"]
        return [_to_candidate(r, "mock", True) for r in rows]


class ManualCatalogAdapter:
    name = "manual_catalog"

    def __init__(self, path: Path):
        self.path = path

    def is_configured(self) -> bool:
        return self.path.exists()

    def candidates(self, keywords: list[str]) -> list[ProductCandidate]:
        if not self.path.exists():
            return []
        rows = json.loads(self.path.read_text(encoding="utf-8")).get("products", [])
        return [_to_candidate(r, "manual", bool(r.get("is_demo", False))) for r in rows]


class CoupangSearchCatalog:
    name = "coupang_search"

    def __init__(self, adapter: CoupangPartnersAdapter, keyword_categories: dict[str, str], per_keyword: int = 5):
        self.adapter = adapter
        self.keyword_categories = keyword_categories
        self.per_keyword = per_keyword

    def is_configured(self) -> bool:
        return self.adapter.is_configured()

    def candidates(self, keywords: list[str]) -> list[ProductCandidate]:
        out: list[ProductCandidate] = []
        for kw in keywords:
            for item in self.adapter.search_products(kw, limit=self.per_keyword):
                row = map_search_item(item, kw, self.keyword_categories.get(kw, "unknown"))
                out.append(_to_candidate(row, "coupang_api", False))
        return out
