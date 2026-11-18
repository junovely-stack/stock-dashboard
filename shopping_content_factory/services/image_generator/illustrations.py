"""DEMO 일러스트 (코드로 직접 그림 → 권리: own). 실제 상품 사진이 아니며 화면에 'DEMO 일러스트'로 표기.

실운영에서는 이 자리에 '권리가 확인된 실제 상품 사진'이 들어간다.
문제 장면·사용 장면 배경은 생성형 도구로 바꿀 수 있지만, 상품 자체는 원본 이미지를 그대로 합성한다.
"""
from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFilter

from services.image_generator.drawing import CARD, NAVY, ORANGE, SUB, bezier, font, vertical_gradient

S = 2  # 슈퍼샘플링 배율 (부드러운 곡선)


def _s(*vals):
    return tuple(v * S for v in vals)


def cable_tray_product(size=(1200, 800)) -> Image.Image:
    """책상 하단 케이블 트레이 (투명 배경 RGBA)."""
    w, h = size
    img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(_s(140, 640, 1060, 720), fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18 * S)))
    # 고정 날개(나사 구멍)
    for x0 in (70, 1000):
        d.rounded_rectangle(_s(x0, 150, x0 + 130, 215), radius=10 * S, fill=(88, 94, 106))
        for cx in (x0 + 35, x0 + 95):
            d.ellipse(_s(cx - 11, 171, cx + 11, 193), fill=(40, 43, 50))
    # 윗면(안쪽)
    d.polygon([_s(150, 215), _s(1050, 215), _s(1100, 285), _s(100, 285)], fill=(36, 39, 46))
    # 앞면
    d.rounded_rectangle(_s(100, 280, 1100, 600), radius=18 * S, fill=(58, 63, 72))
    d.rectangle(_s(100, 280, 1100, 300), fill=(96, 103, 116))
    # 타공 패턴
    for row in range(4):
        for col in range(14):
            x = 150 + col * 66 + (33 if row % 2 else 0)
            y = 335 + row * 62
            if x < 1060:
                d.rounded_rectangle(_s(x, y, x + 34, y + 22), radius=8 * S, fill=(80, 86, 98))
    # 측면 판
    d.polygon([_s(100, 285), _s(100, 600), _s(70, 560), _s(70, 255)], fill=(46, 50, 58))
    d.polygon([_s(1100, 285), _s(1100, 600), _s(1130, 560), _s(1130, 255)], fill=(46, 50, 58))
    return img.resize(size, Image.LANCZOS)


def generic_product(name: str, size=(1200, 800)) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((150, 120, w - 150, h - 120), radius=48, fill=(234, 238, 243), outline=(200, 208, 218),
                        width=6)
    f = font(64, "bold")
    label = "DEMO 상품 이미지"
    d.text(((w - d.textlength(label, font=f)) / 2, h / 2 - 70), label, font=f, fill=(90, 104, 122))
    f2 = font(40, "regular")
    short = name.replace("[DEMO]", "").strip()[:18]
    d.text(((w - d.textlength(short, font=f2)) / 2, h / 2 + 20), short, font=f2, fill=(120, 132, 150))
    return img


def _room(size=(1080, 1920)) -> Image.Image:
    w, h = size
    img = vertical_gradient((w * S, h * S), (238, 233, 224), (222, 214, 200)).convert("RGBA")
    d = ImageDraw.Draw(img)
    d.rectangle(_s(0, 1350, w, h), fill=(181, 139, 94))
    for i, y in enumerate(range(1350, h, 72)):
        d.line(_s(0, y, w, y), fill=(160, 120, 80), width=3 * S)
        off = 140 if i % 2 else 0
        for x in range(off, w, 280):
            d.line(_s(x, y, x, y + 72), fill=(165, 126, 86), width=2 * S)
    d.rectangle(_s(0, 1332, w, 1352), fill=(246, 243, 237))
    d.rectangle(_s(690, 250, 940, 520), fill=(255, 255, 255))
    d.rectangle(_s(706, 266, 924, 504), fill=(200, 221, 236))
    d.polygon([_s(706, 504), _s(800, 400), _s(860, 450), _s(924, 380), _s(924, 504)], fill=(170, 198, 216))
    return img


def _desk(d: ImageDraw.ImageDraw) -> None:
    for x0 in (120, 920):
        d.ellipse(_s(x0 - 30, 1388, x0 + 70, 1412), fill=(140, 104, 70))
        d.rectangle(_s(x0, 800, x0 + 40, 1400), fill=(98, 72, 50))
    d.rectangle(_s(80, 760, 1000, 802), fill=(122, 90, 64))
    d.rectangle(_s(80, 760, 1000, 767), fill=(152, 116, 86))
    for mx in (160, 560):
        d.rounded_rectangle(_s(mx, 420, mx + 360, 650), radius=10 * S, fill=(30, 32, 38))
        d.rectangle(_s(mx + 12, 432, mx + 348, 638), fill=(48, 68, 98))
        d.rectangle(_s(mx + 12, 432, mx + 348, 470), fill=(60, 84, 120))
        d.rectangle(_s(mx + 165, 650, mx + 195, 722), fill=(44, 46, 52))
        d.ellipse(_s(mx + 110, 716, mx + 250, 744), fill=(44, 46, 52))
    d.rounded_rectangle(_s(360, 734, 720, 758), radius=8 * S, fill=(224, 226, 230))
    d.rounded_rectangle(_s(800, 690, 852, 758), radius=8 * S, fill=(250, 250, 250))


def _vacuum(d: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    d.ellipse(_s(cx - 95, cy - 30, cx + 95, cy + 40), fill=(150, 112, 76))
    d.ellipse(_s(cx - 90, cy - 50, cx + 90, cy + 25), fill=(58, 62, 72))
    d.ellipse(_s(cx - 60, cy - 42, cx + 60, cy + 4), fill=(78, 84, 96))
    d.ellipse(_s(cx - 12, cy - 30, cx + 12, cy - 14), fill=ORANGE)


def desk_scene(mode: str, product: Image.Image | None = None, seed: int = 7) -> Image.Image:
    """mode='mess' (문제 장면) | 'tidy' (사용 장면). 1080×1920 RGB."""
    img = _room()
    d = ImageDraw.Draw(img)
    _desk(d)
    rng = random.Random(seed)
    colors = [(36, 38, 44), (20, 20, 24), (226, 226, 230), (70, 74, 84)]
    if mode == "mess":
        tap = (390, 1470, 650, 1518)
        d.ellipse(_s(380, 1500, 660, 1535), fill=(150, 112, 76))
        d.rounded_rectangle(_s(*tap), radius=12 * S, fill=(244, 244, 244))
        for i in range(5):
            cx = 420 + i * 48
            d.ellipse(_s(cx, 1484, cx + 22, 1506), fill=(150, 150, 156))
        for i in range(11):
            x0 = rng.randint(220, 880)
            pts = bezier([(x0, 790), (x0 + rng.randint(-160, 160), 1150), (rng.randint(250, 850), 1700),
                          (rng.randint(420, 620), 1494)])
            d.line([_s(x, y) for x, y in pts], fill=colors[i % 4], width=7 * S, joint="curve")
        for i in range(5):
            y = rng.randint(1560, 1760)
            pts = bezier([(rng.randint(80, 300), y), (rng.randint(300, 600), y + 120), (rng.randint(500, 800), y - 90),
                          (rng.randint(750, 1020), y + rng.randint(-40, 40))])
            d.line([_s(x, y2) for x, y2 in pts], fill=colors[(i + 1) % 4], width=7 * S, joint="curve")
        for _ in range(9):
            cx, cy = rng.randint(120, 980), rng.randint(1430, 1820)
            for _ in range(5):
                r = rng.randint(6, 14)
                ox, oy = rng.randint(-14, 14), rng.randint(-8, 8)
                d.ellipse(_s(cx + ox - r, cy + oy - r, cx + ox + r, cy + oy + r), fill=(176, 170, 162))
        _vacuum(d, 210, 1660)
        pts = bezier([(120, 1600), (200, 1560), (260, 1700), (330, 1640)])
        d.line([_s(x, y) for x, y in pts], fill=(20, 20, 24), width=7 * S)
    else:
        # 깔끔: 트레이 안으로 선이 들어가고 한 가닥만 다리를 따라 내려감
        for x in (330, 420, 640, 700):
            d.line(_s(x, 740, x + 10, 812), fill=(36, 38, 44), width=6 * S)
        d.line(_s(905, 830, 905, 1330), fill=(36, 38, 44), width=7 * S)
        for y in (950, 1080, 1210):
            d.rounded_rectangle(_s(896, y, 914, y + 22), radius=4 * S, fill=ORANGE)
        d.rounded_rectangle(_s(880, 1290, 940, 1340), radius=6 * S, fill=(244, 244, 244))
        _vacuum(d, 560, 1650)
        for i in range(3):
            d.line(_s(400 - i * 40, 1625 + i * 22, 455 - i * 40, 1625 + i * 22), fill=(120, 90, 60), width=5 * S)
    out = img.resize((1080, 1920), Image.LANCZOS).convert("RGBA")
    if mode != "mess" and product is not None:
        pw = 560
        ph = int(product.height * pw / product.width)
        out.alpha_composite(product.resize((pw, ph), Image.LANCZOS), (260, 760))
    return out.convert("RGB")


def generic_scene(mode: str, seed: int = 3) -> Image.Image:
    rng = random.Random(seed)
    top, bottom = ((44, 58, 80), (18, 30, 50)) if mode == "mess" else ((232, 238, 245), (205, 216, 228))
    img = vertical_gradient((1080, 1920), top, bottom).convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(9):
        r = rng.randint(120, 320)
        cx, cy = rng.randint(0, 1080), rng.randint(200, 1700)
        col = (*SUB, 40) if mode == "mess" else (*CARD, 18)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(30)))
    return img.convert("RGB")


def endcard_background() -> Image.Image:
    return vertical_gradient((1080, 1920), (16, 34, 60), NAVY)
