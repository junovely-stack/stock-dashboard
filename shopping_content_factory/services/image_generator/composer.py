"""상품당 이미지 6종 + image_manifest.json.

- 상품 이미지는 '권리가 확인된 원본'을 비율 그대로 붙인다(색·형태 수정 없음).
- 붙인 뒤 원형 보존 검수: 불투명 픽셀이 원본(리사이즈)과 같은지, 가로세로비 변화가 없는지.
- 권리 미확인 이미지는 사용하지 않고 콘텐츠를 중단한다(RightsBlocked).
- 배경·문제/사용 장면은 코드 일러스트(또는 허가된 생성 도구) — 상품이 아닌 부분만 생성.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

from app.models import Content, ImageRights, Product
from config.settings import get_settings
from services.common.db import session_scope
from services.common.timeutil import now_utc
from services.image_generator import illustrations as il
from services.image_generator.drawing import (CARD, NAVY, ORANGE, SUB, WHITE, draw_text_lines, font, vertical_gradient,
                                              wrap_smart, wrap_text)


class RightsBlocked(RuntimeError):
    pass


@dataclass
class Paste:
    x: int
    y: int
    img: Image.Image  # 리사이즈된 RGBA 상품 이미지


def paste_product(canvas: Image.Image, product: Image.Image, box: tuple[int, int, int, int]) -> Paste:
    """box 안에 비율 유지로 맞춰 붙인다. 반환값은 검수용."""
    x0, y0, x1, y1 = box
    scale = min((x1 - x0) / product.width, (y1 - y0) / product.height)
    w, h = max(1, int(product.width * scale)), max(1, int(product.height * scale))
    resized = product.resize((w, h), Image.LANCZOS)
    x, y = x0 + (x1 - x0 - w) // 2, y0 + (y1 - y0 - h) // 2
    canvas.alpha_composite(resized, (x, y))
    return Paste(x, y, resized)


def preservation_check(final: Image.Image, paste: Paste, original: Image.Image) -> dict:
    region = np.asarray(final.convert("RGBA").crop((paste.x, paste.y, paste.x + paste.img.width,
                                                    paste.y + paste.img.height))).astype(np.int16)
    ref = np.asarray(paste.img).astype(np.int16)
    mask = ref[..., 3] >= 250
    color_delta = float(np.abs(region[..., :3][mask] - ref[..., :3][mask]).mean()) if mask.any() else 0.0
    ar_orig = original.width / original.height
    ar_new = paste.img.width / paste.img.height
    ar_delta = abs(ar_new - ar_orig) / ar_orig
    return {"checked": True, "aspect_ratio_delta": round(ar_delta, 4), "color_delta": round(color_delta, 3),
            "opaque_pixels": int(mask.sum()), "passed": ar_delta < 0.01 and color_delta < 2.0}


def _badge(d: ImageDraw.ImageDraw, text: str, x: int, y: int, size: int = 40) -> None:
    f = font(size, "bold")
    w = d.textlength(text, font=f)
    d.rounded_rectangle((x, y, x + w + 36, y + size + 24), radius=14, fill=ORANGE)
    d.text((x + 18, y + 9), text, font=f, fill=WHITE)


def _demo_mark(d: ImageDraw.ImageDraw, w: int, y: int = 150, label: str = "DEMO 예시") -> None:
    f = font(30, "bold")
    tw = d.textlength(label, font=f)
    d.rounded_rectangle((w - tw - 90, y, w - 48, y + 52), radius=12, fill=(0, 0, 0, 110))
    d.text((w - tw - 69, y + 9), label, font=f, fill=(255, 255, 255, 230))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_original(p: Product, out_dir: Path, settings) -> tuple[Image.Image, dict]:
    imgs = [i for i in p.images if i.role == "original"]
    if not imgs:
        raise RightsBlocked("상품 원본 이미지 없음")
    src = imgs[0]
    video_ok = set(ImageRights.VIDEO_OK)
    if settings.allow_partner_images_in_video:
        video_ok.add(ImageRights.PARTNER_DISPLAY)
    if src.rights_status not in video_ok:
        raise RightsBlocked(f"상품 이미지 사용권 미확인({src.rights_status}) — 영상·편집 사용 불가")
    target = out_dir / "product_original.png"
    if src.source == "demo_illustration":
        kind = (p.signals or {}).get("illustration")
        img = il.cable_tray_product() if kind == "cable_tray" else il.generic_product(p.name)
        img.save(target)
        entry = {"source": "demo_illustration (코드로 직접 그림, 실제 상품 사진 아님)", "generator": "pillow"}
    elif src.path and Path(src.path).exists():
        ext = Path(src.path).suffix.lower() or ".png"
        target = out_dir / f"product_original{ext}"
        shutil.copyfile(src.path, target)
        img = Image.open(target).convert("RGBA")
        entry = {"source": src.source, "generator": None}
    else:
        raise RightsBlocked("권리가 확인된 로컬 상품 이미지 파일이 없음 (URL 만 있는 판매처 이미지는 영상에 쓰지 않음)")
    src.path = str(target)
    entry.update({"file": target.name, "role": "product_original", "rights_status": src.rights_status,
                  "rights_evidence": src.rights_evidence, "ai_generated": False, "contains_product": True,
                  "edited": False})
    return img.convert("RGBA"), entry


def produce_images(content_id: str) -> dict:
    try:
        return _produce_images(content_id)
    except RightsBlocked as exc:
        # 위 트랜잭션은 롤백되므로 차단 상태는 별도 트랜잭션으로 확정한 뒤 다시 던진다
        with session_scope() as s:
            c = s.get(Content, content_id)
            c.status = "blocked"
            c.block_reasons = list(dict.fromkeys((c.block_reasons or []) + [str(exc)]))
            c.product.content_status = "blocked"
        raise


def _produce_images(content_id: str) -> dict:
    settings = get_settings()
    with session_scope() as s:
        c = s.get(Content, content_id)
        p = c.product
        out = Path(c.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        original, orig_entry = load_original(p, out, settings)
        manifest: list[dict] = [orig_entry]
        demo_kind = (p.signals or {}).get("illustration")
        scene_src = "procedural_illustration (pillow, 연출 이미지)"

        problem = il.desk_scene("mess") if demo_kind == "cable_tray" else il.generic_scene("mess")
        problem.save(out / "problem_scene.png")
        manifest.append({"file": "problem_scene.png", "role": "problem_scene", "source": scene_src,
                         "rights_status": ImageRights.OWN, "generator": "pillow", "ai_generated": False,
                         "contains_product": False, "note": "연출 일러스트 — 실제 사용 전 사진 아님"})

        if demo_kind == "cable_tray":
            usage = il.desk_scene("tidy", product=original).convert("RGBA")
            pw = 560
            paste = Paste(260, 760, original.resize((pw, int(original.height * pw / original.width)), Image.LANCZOS))
        else:
            usage = il.generic_scene("tidy").convert("RGBA")
            paste = paste_product(usage, original, (140, 520, 940, 1220))
        usage.convert("RGB").save(out / "usage_scene.png")
        manifest.append({"file": "usage_scene.png", "role": "usage_scene", "source": scene_src + " + 상품 원본 합성",
                         "rights_status": ImageRights.OWN, "generator": "pillow", "ai_generated": False,
                         "contains_product": True, "product_preservation": preservation_check(usage, paste, original),
                         "note": "사용 상황 연출 — 실제 설치 사진 아님"})

        # 상품 대표 이미지: 상품 + 검증 사양 칩
        hero = vertical_gradient((1080, 1920), (24, 44, 72), NAVY).convert("RGBA")
        hp = paste_product(hero, original, (90, 360, 990, 1100))
        d = ImageDraw.Draw(hero)
        y = 1180
        chip_f = font(40, "bold")
        for spec in (p.verified_specs or [])[:4]:
            label = f"{spec['key']}  {spec['value']}{spec.get('unit') or ''}"
            lines = wrap_text(d, label, chip_f, 860)
            hgt = 40 * 1.4 * len(lines) + 34
            d.rounded_rectangle((90, y, 990, y + hgt), radius=20, fill=CARD, outline=(52, 76, 108), width=2)
            draw_text_lines(d, lines, chip_f, 124, y + 17, WHITE, 40 * 1.4)
            y += hgt + 18
        hero_rgb = hero.convert("RGB")
        hero_rgb.save(out / "product_hero.png")
        manifest.append({"file": "product_hero.png", "role": "product_hero", "source": "상품 원본 + 그래픽 배경·사양 칩",
                         "rights_status": orig_entry["rights_status"], "generator": "pillow", "ai_generated": False,
                         "contains_product": True, "product_preservation": preservation_check(hero, hp, original)})

        # 영상용 무대(사양 칩 없이 상품만) + 엔드카드 배경
        stage = vertical_gradient((1080, 1920), (24, 44, 72), NAVY).convert("RGBA")
        sp = paste_product(stage, original, (120, 300, 960, 900))
        stage.convert("RGB").save(out / "product_stage.png")
        manifest.append({"file": "product_stage.png", "role": "video_stage", "source": "상품 원본 + 그래픽 배경",
                         "rights_status": orig_entry["rights_status"], "generator": "pillow", "ai_generated": False,
                         "contains_product": True, "product_preservation": preservation_check(stage, sp, original)})
        il.endcard_background().save(out / "endcard.png")
        manifest.append({"file": "endcard.png", "role": "endcard_bg", "source": "단색 그라디언트",
                         "rights_status": ImageRights.OWN, "generator": "pillow", "ai_generated": False,
                         "contains_product": False})

        # 썸네일: 문제 장면 + 후킹 + 광고 배지
        script = c.script
        hook = script["variants"][c.primary_variant]["hook"]
        thumb = ImageEnhance.Brightness(problem).enhance(0.55).convert("RGBA")
        overlay = Image.new("RGBA", thumb.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((0, 0, 1080, 1920), fill=(10, 26, 47, 70))
        thumb.alpha_composite(overlay)
        ImageDraw.Draw(thumb).rounded_rectangle((150, 1130, 930, 1590), radius=36, fill=(244, 246, 250, 255))
        tp = paste_product(thumb, original, (190, 1170, 890, 1550))
        d = ImageDraw.Draw(thumb)
        hook_f = font(92, "extrabold")
        lines = wrap_smart(d, hook, hook_f, 900)
        draw_text_lines(d, lines, hook_f, 90, 430, WHITE, 92 * 1.3)
        _badge(d, "광고", 60, 160)
        if p.is_demo:
            _demo_mark(d, 1080)
        thumb.convert("RGB").save(out / "thumbnail.png")
        manifest.append({"file": "thumbnail.png", "role": "thumbnail", "source": "문제 장면 + 상품 원본 + 후킹 문구",
                         "rights_status": orig_entry["rights_status"], "generator": "pillow", "ai_generated": False,
                         "contains_product": True, "product_preservation": preservation_check(thumb, tp, original)})

        # 랜딩용 이미지 (1200×900, 밝은 배경)
        land = vertical_gradient((1200, 900), (246, 248, 251), (230, 235, 242)).convert("RGBA")
        lp = paste_product(land, original, (100, 90, 1100, 810))
        land.convert("RGB").save(out / "landing_card.png")
        manifest.append({"file": "landing_card.png", "role": "landing", "source": "상품 원본 + 단색 배경",
                         "rights_status": orig_entry["rights_status"], "generator": "pillow", "ai_generated": False,
                         "contains_product": True, "product_preservation": preservation_check(land, lp, original)})

        for m in manifest:
            m["sha256_16"] = _sha(out / m["file"])
        all_ok = all(m.get("product_preservation", {"passed": True})["passed"] for m in manifest)
        rights_ok = all(m["rights_status"] in ImageRights.VIDEO_OK or
                        (settings.allow_partner_images_in_video and m["rights_status"] == ImageRights.PARTNER_DISPLAY)
                        for m in manifest)
        doc = {"content_id": content_id, "product_id": p.id, "created_at": now_utc().isoformat(),
               "is_demo": p.is_demo, "images": manifest, "all_preserved": all_ok, "all_rights_cleared": rights_ok,
               "ai_generated_any": any(m["ai_generated"] for m in manifest)}
        (out / "image_manifest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        assets = dict(c.assets or {})
        assets["images"] = {m["role"]: m["file"] for m in manifest}
        assets["image_manifest"] = "image_manifest.json"
        c.assets = assets
        c.ai_generated_media = doc["ai_generated_any"]
        if not (all_ok and rights_ok):
            c.status = "blocked"
            c.block_reasons = list(dict.fromkeys((c.block_reasons or []) + ["이미지 원형 보존 또는 권리 검수 실패"]))
        return {"images": len(manifest), "preserved": all_ok, "rights_cleared": rights_ok}
