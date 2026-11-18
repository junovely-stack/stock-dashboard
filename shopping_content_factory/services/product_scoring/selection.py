"""상위 5개 → 최종 1개 선정 + 상품정보 재검증 (07:35 단계).

상위 후보를 순위대로 다시 확인(가격 유효시간·재고·이미지 권리·사양)하고, 처음 통과한 상품을 최종 선정.
최종 점수가 기준(SCF_MIN_FINAL_SCORE) 미만이면 '오늘은 제작하지 않음' — 억지로 만들지 않는다.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import ImageRights, Product, ProductScore, SelectionLog, StockStatus
from config.settings import get_settings
from services.common.db import session_scope
from services.common.timeutil import hours_since


class NothingToProduce(RuntimeError):
    pass


def reverify(p: Product, ttl_hours: int) -> list[str]:
    problems = []
    age = hours_since(p.price_checked_at)
    if age is None or age > ttl_hours:
        problems.append("가격 확인 만료")
    if p.stock_status not in (StockStatus.IN_STOCK, StockStatus.LOW_STOCK):
        problems.append(f"재고 {p.stock_status}")
    if p.image_rights_status not in ImageRights.VIDEO_OK:
        problems.append("이미지 권리 미확인")
    if len(p.verified_specs or []) < 3:
        problems.append("검증 사양 부족")
    return problems


def select_final(run_date: date) -> dict:
    settings = get_settings()
    with session_scope() as s:
        top = list(s.scalars(select(ProductScore).where(ProductScore.run_date == run_date,
                                                        ProductScore.selection.in_(["top5", "final"]))
                             .order_by(ProductScore.rank)))
        for sc in top:
            sc.selection = "top5"
        log_rows = []
        final = None
        for sc in top:
            p = s.get(Product, sc.product_id)
            problems = reverify(p, settings.price_ttl_hours)
            log_rows.append({"product_id": p.id, "rank": sc.rank, "total": sc.total, "problems": problems})
            if problems:
                continue
            if sc.total < settings.min_final_score:
                log_rows[-1]["problems"].append(f"점수 {sc.total} < 기준 {settings.min_final_score}")
                continue
            final = sc
            break
        if final is None:
            s.add(SelectionLog(run_date=run_date, step="final", message="최종 선정 없음 — 오늘은 제작하지 않음",
                               data={"checked": log_rows}))
            raise NothingToProduce("기준을 통과한 최종 후보가 없습니다 (selection_logs 참조)")
        final.selection = "final"
        p = s.get(Product, final.product_id)
        p.content_status = "selected"
        s.add(SelectionLog(run_date=run_date, step="final",
                           message=f"최종 선정: {p.name} ({final.total:.1f}점, {final.rank}위)",
                           data={"product_id": p.id, "checked": log_rows}))
        return {"final": p.id, "total": final.total, "checked": log_rows}


def final_product_id(run_date: date) -> str | None:
    with session_scope() as s:
        sc = s.scalars(select(ProductScore).where(ProductScore.run_date == run_date,
                                                  ProductScore.selection == "final")).first()
        return sc.product_id if sc else None
