import json
from pathlib import Path

import pytest

from tests.conftest import RUN_DATE

CID = "C20261118-01"


def test_script_images_and_manifests_saved(pipeline):
    out = pipeline / "out" / "contents" / CID
    for name in ["script.json", "product_original.png", "product_hero.png", "problem_scene.png", "usage_scene.png",
                 "thumbnail.png", "landing_card.png", "image_manifest.json", "captions.srt", "content_manifest.json",
                 "reel_final.mp4", "shorts_final.mp4"]:
        assert (out / name).exists(), name
    man = json.loads((out / "image_manifest.json").read_text(encoding="utf-8"))
    assert man["all_preserved"] and man["all_rights_cleared"]
    for img in man["images"]:
        assert img["rights_status"] and img["source"]
        if img["contains_product"] and img["role"] != "product_original":
            assert img["product_preservation"]["passed"]
            assert img["product_preservation"]["color_delta"] < 2.0
    script = json.loads((out / "script.json").read_text(encoding="utf-8"))
    for key in ["title", "variants", "scenes", "narration_full", "disclosure", "cta", "caption", "hashtags",
                "landing_url", "cost_estimate_krw", "cautions"]:
        assert key in script
    assert script["hashtags"][0] == "#광고"
    assert set(script["variants"]) == {"A", "B"}


def test_mp4_is_valid_vertical_short(pipeline):
    from services.video_renderer.renderer import probe

    for name in ("reel_final.mp4", "shorts_final.mp4"):
        info = probe(pipeline / "out" / "contents" / CID / name)
        assert (info["width"], info["height"]) == (1080, 1920)
        assert 15 <= info["duration"] <= 30
        assert info["codec"] == "h264" and info["pix_fmt"] == "yuv420p" and info["has_audio"]


def test_srt_has_all_scenes(pipeline):
    srt = (pipeline / "out" / "contents" / CID / "captions.srt").read_text(encoding="utf-8")
    assert srt.count("-->") == 5


def test_preservation_check_detects_recolor():
    from PIL import Image

    from services.image_generator.composer import Paste, paste_product, preservation_check

    prod = Image.new("RGBA", (200, 100), (200, 30, 30, 255))
    canvas = Image.new("RGBA", (400, 400), (0, 0, 0, 255))
    paste = paste_product(canvas, prod, (0, 0, 400, 400))
    assert preservation_check(canvas, paste, prod)["passed"]
    recolored = canvas.copy()
    recolored.paste((30, 200, 30, 255), (paste.x, paste.y, paste.x + paste.img.width, paste.y + paste.img.height))
    assert not preservation_check(recolored, paste, prod)["passed"]
    squashed = Paste(paste.x, paste.y, paste.img.resize((paste.img.width, paste.img.height // 2)))
    assert not preservation_check(canvas, squashed, prod)["passed"]


def test_unclear_image_rights_block_content(pipeline):
    from app.models import Content, ProductImage
    from services.common.db import session_scope
    from services.image_generator.composer import RightsBlocked, produce_images
    from sqlalchemy import select

    with session_scope() as s:
        img = s.scalars(select(ProductImage).where(ProductImage.product_id == "DEMO-001")).first()
        img.rights_status = "unknown"
    with pytest.raises(RightsBlocked):
        produce_images(CID)
    with session_scope() as s:
        c = s.get(Content, CID)
        assert c.status == "blocked"
        assert any("사용권" in r for r in c.block_reasons)


def test_partner_display_image_not_used_in_video_by_default(pipeline):
    from app.models import ProductImage
    from services.common.db import session_scope
    from services.image_generator.composer import RightsBlocked, produce_images
    from sqlalchemy import select

    with session_scope() as s:
        img = s.scalars(select(ProductImage).where(ProductImage.product_id == "DEMO-001")).first()
        img.rights_status = "partner_display_only"
    with pytest.raises(RightsBlocked):
        produce_images(CID)


def test_korean_wrap_keeps_words():
    from PIL import Image, ImageDraw

    from services.image_generator.drawing import font, wrap_smart, wrap_text

    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f = font(88, "extrabold")
    lines = wrap_smart(d, "책상 위는 깔끔한데, 책상 밑은 어떠신가요?", f, 860)
    assert lines == ["책상 위는 깔끔한데,", "책상 밑은 어떠신가요?"]
    for ln in wrap_text(d, "멀티탭과 남는 케이블이 바닥에서 사라져 청소기가 걸리지 않는다", font(62), 830):
        assert not ln.startswith(" ") and d.textlength(ln, font=font(62)) <= 830
