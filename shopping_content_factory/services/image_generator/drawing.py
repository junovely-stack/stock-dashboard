"""그리기 공용 도구: 폰트, 한글 줄바꿈, 그라디언트, 둥근 상자, 베지어 곡선.

폰트는 assets/fonts 의 Pretendard(OFL) → SCF_FONT_PATH → OS 한글 폰트 순으로 찾는다.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config.settings import BASE_DIR

NAVY = (10, 26, 47)
ORANGE = (255, 107, 26)
CARD = (22, 38, 61)
SUB = (170, 183, 196)
WHITE = (255, 255, 255)

_WEIGHT_FILES = {
    "regular": ["Pretendard-Regular.ttf"],
    "bold": ["Pretendard-Bold.ttf"],
    "extrabold": ["Pretendard-ExtraBold.ttf", "Pretendard-Bold.ttf"],
}
_SYSTEM_FALLBACKS = [
    "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]


@lru_cache(maxsize=64)
def font(size: int, weight: str = "bold") -> ImageFont.FreeTypeFont:
    candidates: list[Path] = []
    env = os.environ.get("SCF_FONT_PATH")
    if env:
        candidates.append(Path(env))
    for name in _WEIGHT_FILES.get(weight, _WEIGHT_FILES["bold"]):
        candidates.append(BASE_DIR / "assets" / "fonts" / name)
    candidates += [Path(p) for p in _SYSTEM_FALLBACKS]
    for c in candidates:
        if c.exists():
            return ImageFont.truetype(str(c), size)
    raise FileNotFoundError("한글 폰트를 찾지 못했습니다. assets/fonts 에 Pretendard 를 두거나 SCF_FONT_PATH 지정")


def text_width(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=f)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """어절(공백) 단위로 줄바꿈 — 'keep-all'. 한 어절이 너무 길 때만 글자 단위로 자른다."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        line = ""
        for w in words:
            cand = f"{line} {w}".strip()
            if text_width(draw, cand, f) <= max_width:
                line = cand
                continue
            if line:
                lines.append(line)
            if text_width(draw, w, f) <= max_width:
                line = w
            else:
                chunk = ""
                for ch in w:
                    if text_width(draw, chunk + ch, f) > max_width:
                        lines.append(chunk)
                        chunk = ch
                    else:
                        chunk += ch
                line = chunk
        lines.append(line)
    return [ln for ln in lines if ln != ""] or [""]


def wrap_smart(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """쉼표·물음표 뒤에서 끊어 각 조각이 한 줄에 들어가면 그걸 쓰고, 아니면 어절 줄바꿈."""
    if "\n" not in text:
        for sep in (", ", "? ", ". ", " — "):
            if sep in text:
                parts = [x.strip() for x in text.split(sep)]
                parts = [x + sep.strip() if i < len(parts) - 1 else x for i, x in enumerate(parts)]
                if all(text_width(draw, x, f) <= max_width for x in parts):
                    return parts
    return wrap_text(draw, text, f, max_width)


def vertical_gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return base.resize((w, h))


def rounded_box(draw: ImageDraw.ImageDraw, box, radius: int, fill, outline=None, width: int = 0) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def bezier(points: list[tuple[float, float]], steps: int = 60) -> list[tuple[float, float]]:
    """3차 베지어 (p0, c1, c2, p1)."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = points
    out = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        out.append((a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3))
    return out


def draw_text_lines(draw: ImageDraw.ImageDraw, lines: list[str], f: ImageFont.FreeTypeFont, x: float, y: float,
                    fill, line_height: float, align: str = "left", width: float | None = None,
                    label_color=None, labels: tuple[str, ...] = ()) -> float:
    """여러 줄 그리기. labels 로 시작하는 줄은 앞 어절을 label_color 로 강조."""
    for ln in lines:
        lx = x
        if align == "center" and width is not None:
            lx = x + (width - text_width(draw, ln, f)) / 2
        hit = next((lb for lb in labels if ln.startswith(lb)), None)
        if hit and label_color:
            draw.text((lx, y), hit, font=f, fill=label_color)
            draw.text((lx + text_width(draw, hit, f), y), ln[len(hit):], font=f, fill=fill)
        else:
            draw.text((lx, y), ln, font=f, fill=fill)
        y += line_height
    return y
