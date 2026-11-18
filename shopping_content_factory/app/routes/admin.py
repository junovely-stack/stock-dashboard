"""관리자 화면 — 후보·선정·콘텐츠 검수·게시·성과·비용·로그. 모든 POST 는 CSRF 토큰 확인, 변경은 감사 로그."""
from __future__ import annotations

import hmac
import json
import tempfile
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import (Blueprint, abort, flash, redirect, render_template, request, send_from_directory, session,
                   url_for)
from sqlalchemy import func, select

from app.models import (AffiliateLink, ApiUsage, AuditLog, Content, ContentStatus, CostEntry, DataSource, ImageRights,
                        JobRun, LinkStatus, Product, ProductImage, ProductScore, Publication, SelectionLog,
                        StockStatus)
from config.settings import get_settings, load_policy
from services.affiliate_links.links import confirm_link, register_manual_link
from services.analytics.funnel import content_funnels, cost_summary, unattributed_affiliate
from services.analytics.importers import import_affiliate_csv, import_metrics_csv
from services.analytics.simulation import run_all
from services.common.cost_guard import spent_krw
from services.common.db import session_scope
from services.common.facts import facts_hash
from services.common.timeutil import now_utc, parse_date, today_local, tz
from services.social_publishers import review
from services.social_publishers.publisher import PLATFORMS, publish_content
from workflows.pipeline import STAGES, FileLock, run_stage

bp = Blueprint("admin", __name__)


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@bp.before_request
def csrf_protect():
    if request.method == "POST":
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if not session.get("csrf") or not hmac.compare_digest(session["csrf"], token):
            abort(400, "CSRF 토큰 불일치")


def actor() -> str:
    return session.get("admin_name") or "admin"


@bp.route("/login", methods=["GET", "POST"])
def login():
    pw = get_settings().admin_password
    error = None
    if request.method == "POST":
        if not pw:
            error = "SCF_ADMIN_PASSWORD 가 설정되지 않아 로그인할 수 없습니다 (.env)."
        elif hmac.compare_digest(pw, request.form.get("password", "")):
            session["admin"] = True
            session["admin_name"] = (request.form.get("name") or "admin")[:32]
            return redirect(request.args.get("next") or url_for("admin.dashboard"))
        else:
            error = "비밀번호가 틀렸습니다."
    return render_template("admin/login.html", error=error, configured=bool(pw))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@bp.get("/")
@login_required
def dashboard():
    settings = get_settings()
    d = today_local()
    with session_scope() as s:
        sources = list(s.scalars(select(DataSource).order_by(DataSource.kind, DataSource.name)))
        jobs = {j.stage: j for j in s.scalars(select(JobRun).where(JobRun.run_date == d))}
        final = s.scalars(select(ProductScore).where(ProductScore.run_date == d, ProductScore.selection == "final")).first()
        final_p = s.get(Product, final.product_id) if final else None
        pending = list(s.scalars(select(Content).where(Content.status == ContentStatus.AWAITING_APPROVAL)))
        blocked = list(s.scalars(select(Content).where(Content.status == ContentStatus.BLOCKED)
                                 .order_by(Content.created_at.desc()).limit(5)))
        errors = list(s.scalars(select(ApiUsage).where(ApiUsage.success.is_(False)).order_by(ApiUsage.ts.desc()).limit(5)))
        log_rows = list(s.scalars(select(SelectionLog).where(SelectionLog.run_date == d).order_by(SelectionLog.id)))
        ctx = dict(sources=sources, stages=STAGES, jobs=jobs, final=final, final_p=final_p, pending=pending,
                   blocked=blocked, errors=errors, logs=log_rows, today=d)
    today_cost, month_cost = spent_krw()
    hb = settings.output_dir / ".scheduler_heartbeat"
    return render_template("admin/dashboard.html", today_cost=today_cost, month_cost=month_cost,
                           heartbeat=hb.read_text() if hb.exists() else None, **ctx)


@bp.post("/run")
@login_required
def run():
    stage = request.form.get("stage")
    d = parse_date(request.form.get("date") or None)
    names = [s.name for s in STAGES] if stage == "__all__" else [stage]
    msgs = []
    try:
        with FileLock(get_settings().output_dir / ".pipeline.lock"):
            for name in names:
                if name == "publish_approved" and stage == "__all__":
                    continue
                r = run_stage(d, name, force=bool(request.form.get("force")))
                msgs.append(f"{name}: {r['status']}")
    except RuntimeError as exc:
        msgs.append(str(exc))
    with session_scope() as s:
        s.add(AuditLog(actor=actor(), action="run_stage", target_type="job", target_id=stage or "-",
                       detail={"date": d.isoformat(), "result": msgs}))
    flash(" / ".join(msgs))
    return redirect(request.referrer or url_for("admin.dashboard"))


@bp.get("/candidates")
@login_required
def candidates():
    d = parse_date(request.args.get("date") or None)
    with session_scope() as s:
        rows = []
        for sc in s.scalars(select(ProductScore).where(ProductScore.run_date == d)
                            .order_by(ProductScore.filter_result.desc(), ProductScore.total.desc())):
            rows.append({"score": sc, "p": s.get(Product, sc.product_id)})
        rows.sort(key=lambda r: ({"pass": 0, "hold": 1, "exclude": 2}[r["score"].filter_result], -r["score"].total))
        logs = list(s.scalars(select(SelectionLog).where(SelectionLog.run_date == d).order_by(SelectionLog.id)))
        from app.models import TrendSnapshot

        trends = list(s.scalars(select(TrendSnapshot).where(TrendSnapshot.run_date == d)
                                .order_by(TrendSnapshot.excluded_reason.is_not(None), TrendSnapshot.growth_7d.desc())))
        return render_template("admin/candidates.html", rows=rows, logs=logs, trends=trends, d=d,
                               weights=load_policy("scoring")["weights"])


@bp.get("/contents")
@login_required
def contents():
    with session_scope() as s:
        items = list(s.scalars(select(Content).order_by(Content.created_at.desc()).limit(100)))
        for c in items:
            _ = c.product.name
        return render_template("admin/contents.html", items=items)


@bp.get("/contents/<cid>")
@login_required
def content_detail(cid: str):
    with session_scope() as s:
        c = s.get(Content, cid)
        if c is None:
            abort(404)
        p = c.product
        pubs = list(s.scalars(select(Publication).where(Publication.content_id == cid)))
        audits = list(s.scalars(select(AuditLog).where(AuditLog.target_id == cid).order_by(AuditLog.ts.desc())))
        man = {}
        if c.output_dir and (Path(c.output_dir) / "image_manifest.json").exists():
            man = json.loads((Path(c.output_dir) / "image_manifest.json").read_text(encoding="utf-8"))
        cmanifest = {}
        if c.output_dir and (Path(c.output_dir) / "content_manifest.json").exists():
            cmanifest = json.loads((Path(c.output_dir) / "content_manifest.json").read_text(encoding="utf-8"))
        return render_template("admin/content_detail.html", c=c, p=p, pubs=pubs, audits=audits, man=man,
                               cman=cmanifest, platforms=PLATFORMS, facts_changed=facts_hash(p) != c.facts_hash,
                               links=list(p.links))


@bp.post("/contents/<cid>/action")
@login_required
def content_action(cid: str):
    act = request.form.get("action")
    msg = ""
    try:
        if act == "publish":
            res = publish_content(cid, request.form.get("platform", "instagram"), actor(), trigger="manual")
            msg = f"게시 결과: {res['status']}" + (f" — {res.get('reasons') or res.get('missing') or res.get('error') or ''}")
        else:
            with session_scope() as s:
                c = s.get(Content, cid)
                if c is None:
                    abort(404)
                if act == "approve":
                    review.approve(s, c, actor(), request.form.get("notes"))
                    msg = "승인됨 — 게시 게이트(링크·가격·재고)는 게시 시점에 다시 확인"
                elif act == "reject":
                    review.reject(s, c, actor(), request.form.get("notes") or "사유 미기재")
                    msg = "거절됨"
                elif act == "revision":
                    review.request_revision(s, c, actor(), request.form.get("notes") or "")
                    msg = "수정 요청됨"
                elif act == "edit":
                    scenes = {k[6:]: v for k, v in request.form.items() if k.startswith("scene_") and v.strip()}
                    r = review.edit_copy(s, c, actor(), title=request.form.get("title") or None,
                                         caption_body=request.form.get("caption_body") or None, scene_texts=scenes)
                    msg = f"수정 저장 — 검사 {'통과' if r['passed'] else '실패'}" + (" · 자막 변경: 영상 재렌더 필요"
                                                                              if r["rerender_needed"] else "")
                elif act == "schedule":
                    when = datetime.fromisoformat(request.form["when"]).replace(tzinfo=tz())
                    review.schedule(s, c, actor(), when)
                    msg = f"예약: {request.form['when']}"
                else:
                    abort(400)
    except review.ReviewError as exc:
        msg = f"처리 불가: {exc}"
    flash(msg)
    return redirect(url_for("admin.content_detail", cid=cid))


@bp.post("/contents/<cid>/rerender")
@login_required
def rerender(cid: str):
    from services.image_generator.composer import produce_images
    from services.video_renderer.qa import run_qa
    from services.video_renderer.renderer import render_content

    try:
        produce_images(cid)
        render_content(cid)
        res = run_qa(cid)
        flash(f"재렌더 완료 — QA {res['status']}")
    except Exception as exc:  # noqa: BLE001
        flash(f"재렌더 실패: {exc}")
    return redirect(url_for("admin.content_detail", cid=cid))


@bp.get("/media/<cid>/<path:filename>")
@login_required
def admin_media(cid: str, filename: str):
    with session_scope() as s:
        c = s.get(Content, cid)
        if c is None or not c.output_dir:
            abort(404)
        directory = c.output_dir
    return send_from_directory(directory, filename)


@bp.route("/products/<pid>", methods=["GET", "POST"])
@login_required
def product_edit(pid: str):
    with session_scope() as s:
        p = s.get(Product, pid)
        if p is None:
            abort(404)
        if request.method == "POST":
            act = request.form.get("action")
            if act == "facts":
                try:
                    specs = json.loads(request.form.get("specs_json") or "[]")
                    assert isinstance(specs, list) and all("key" in x and "value" in x for x in specs)
                except (ValueError, AssertionError):
                    flash("사양 JSON 형식 오류 — [{\"key\":..,\"value\":..,\"unit\":..}]")
                    return redirect(url_for("admin.product_edit", pid=pid))
                p.verified_specs = [dict(x, source="admin", verified_at=now_utc().isoformat()) for x in specs]
                for f in ("pros", "cons", "cautions", "recommended_for", "not_recommended_for"):
                    p.__setattr__(f, [ln.strip() for ln in request.form.get(f, "").splitlines() if ln.strip()])
                p.signals = dict(p.signals or {}, admin_edited=True)
                p.facts_hash = facts_hash(p)
                s.add(AuditLog(actor=actor(), action="edit_facts", target_type="product", target_id=pid))
                flash("사실 정보 저장 — 기존 콘텐츠는 재생성·재승인이 필요합니다")
            elif act == "price":
                p.base_price = int(request.form["price"])
                p.price_checked_at = now_utc()
                p.stock_status = request.form.get("stock", p.stock_status)
                p.stock_checked_at = now_utc()
                p.signals = dict(p.signals or {}, admin_edited=True)
                s.add(AuditLog(actor=actor(), action="price_check", target_type="product", target_id=pid,
                               detail={"price": p.base_price, "stock": p.stock_status}))
                flash("가격·재고 확인 시각 갱신")
            elif act == "rights":
                img = s.get(ProductImage, int(request.form["image_id"]))
                img.rights_status = request.form["rights"]
                img.rights_evidence = request.form.get("evidence")
                img.verified_by = actor()
                ranks = [ImageRights.OWN, ImageRights.LICENSED, ImageRights.AI_GENERATED, ImageRights.PARTNER_DISPLAY,
                         ImageRights.REFERENCE_ONLY, ImageRights.UNKNOWN, ImageRights.DENIED]
                p.image_rights_status = min((i.rights_status for i in p.images), key=lambda r: ranks.index(r)
                                            if r in ranks else 99)
                s.add(AuditLog(actor=actor(), action="image_rights", target_type="product", target_id=pid,
                               detail={"image": img.id, "rights": img.rights_status, "evidence": img.rights_evidence}))
                flash("이미지 권리 상태 저장")
            elif act == "link_register":
                link = register_manual_link(s, p, request.form.get("url", ""), actor(),
                                            sub_id=request.form.get("sub_id") or None,
                                            content_id=request.form.get("content_id") or None)
                flash(f"링크 등록: {link.status} — {link.note}")
            elif act == "link_confirm":
                link = s.get(AffiliateLink, int(request.form["link_id"]))
                try:
                    confirm_link(s, link, actor())
                    flash("링크 확인 완료로 표시")
                except ValueError as exc:
                    flash(str(exc))
            elif act == "delete":
                if request.form.get("confirm") != pid:
                    flash("삭제하려면 상품 ID 를 정확히 입력하세요")
                else:
                    res = review.delete_product(s, pid, actor())
                    flash(f"삭제 완료 — 콘텐츠 {res['deleted_contents']}개. 플랫폼 게시물 "
                          f"{res['platform_posts_to_remove_manually']}개는 각 앱에서 직접 삭제하세요")
                    return redirect(url_for("admin.dashboard"))
            return redirect(url_for("admin.product_edit", pid=pid))
        contents_ = list(s.scalars(select(Content).where(Content.product_id == pid)))
        return render_template("admin/product.html", p=p, contents=contents_, rights_options=[
            ImageRights.OWN, ImageRights.LICENSED, ImageRights.AI_GENERATED, ImageRights.PARTNER_DISPLAY,
            ImageRights.REFERENCE_ONLY, ImageRights.UNKNOWN, ImageRights.DENIED],
            stock_options=[StockStatus.IN_STOCK, StockStatus.LOW_STOCK, StockStatus.OUT_OF_STOCK,
                           StockStatus.DISCONTINUED, StockStatus.UNKNOWN])


@bp.get("/publications")
@login_required
def publications():
    with session_scope() as s:
        rows = list(s.scalars(select(Publication).order_by(Publication.updated_at.desc()).limit(200)))
        return render_template("admin/publications.html", rows=rows)


@bp.route("/analytics", methods=["GET", "POST"])
@login_required
def analytics():
    if request.method == "POST":
        kind = request.form.get("kind")
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".csv"):
            flash("CSV 파일을 선택하세요")
            return redirect(url_for("admin.analytics"))
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            f.save(tmp.name)
            path = Path(tmp.name)
        try:
            res = import_metrics_csv(path) if kind == "metrics" else import_affiliate_csv(path)
        finally:
            path.unlink(missing_ok=True)
        with session_scope() as s:
            s.add(AuditLog(actor=actor(), action=f"import_{kind}", target_type="csv", target_id=f.filename[:60],
                           detail={"imported": res["imported"], "rejected": len(res["rejected"])}))
        flash(f"적재 {res['imported']}행 · 거부 {len(res['rejected'])}행 "
              + "; ".join(f"{r['line']}행 {r['reason']}" for r in res["rejected"][:5]))
        return redirect(url_for("admin.analytics"))
    return render_template("admin/analytics.html", rows=content_funnels(), un=unattributed_affiliate(),
                           cost=cost_summary())


@bp.get("/finance")
@login_required
def finance():
    return render_template("admin/finance.html", sim=run_all())


@bp.route("/logs", methods=["GET", "POST"])
@login_required
def logs():
    if request.method == "POST":
        with session_scope() as s:
            s.add(CostEntry(cost_date=parse_date(request.form.get("date") or None),
                            category=request.form.get("category", "other"),
                            amount_krw=int(request.form.get("amount") or 0),
                            content_id=request.form.get("content_id") or None, note=request.form.get("note")))
            s.add(AuditLog(actor=actor(), action="cost_entry", target_type="cost", target_id="-",
                           detail={"amount": request.form.get("amount"), "category": request.form.get("category")}))
        flash("비용 기록 저장")
        return redirect(url_for("admin.logs"))
    with session_scope() as s:
        jobs = list(s.scalars(select(JobRun).order_by(JobRun.run_date.desc(), JobRun.id.desc()).limit(80)))
        usage = list(s.scalars(select(ApiUsage).order_by(ApiUsage.ts.desc()).limit(80)))
        audits = list(s.scalars(select(AuditLog).order_by(AuditLog.ts.desc()).limit(80)))
        costs = list(s.scalars(select(CostEntry).order_by(CostEntry.cost_date.desc()).limit(50)))
        return render_template("admin/logs.html", jobs=jobs, usage=usage, audits=audits, costs=costs,
                               cost=cost_summary())
