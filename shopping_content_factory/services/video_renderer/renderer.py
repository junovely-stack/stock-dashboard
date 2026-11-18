"""Python(Pillow) 프레임 생성 → FFmpeg(libx264) 파이프 인코딩.

- 1080×1920, 9:16, 30fps(기본), H.264 yuv420p + AAC, moov 앞쪽(faststart)
- 장면별 배경 천천히 확대(Ken Burns) + 자막 카드 페이드인 + 장면 간 0.35초 크로스페이드
- 광고 표시: 전 장면 좌상단 '광고' 배지, 첫 장면 문구, 마지막 장면 전체 문구
- 플랫폼 UI 가림 영역 회피: 위 150px·아래 약 20%·오른쪽 아이콘 열 비움
- 산출물: reel_final.mp4, shorts_final.mp4, captions.srt, content_manifest.json
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

from adapters.tts.providers import get_narration
from app.models import Content
from config.settings import get_settings
from services.common.db import session_scope
from services.common.logging_utils import get_logger
from services.common.timeutil import now_utc
from services.image_generator.drawing import (CARD, NAVY, ORANGE, SUB, WHITE, draw_text_lines, font, wrap_smart,
                                              wrap_text)

log = get_logger(__name__)
W, H = 1080, 1920
FADE = 0.35
LABELS = ("좋은 점", "확인할 점", "맞는 분", "안 맞는 분")


class RenderError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RenderError("ffmpeg 가 PATH 에 없습니다 (README 설치 절차 참조)")
    return path


def _badge(d: ImageDraw.ImageDraw, text: str, x: int, y: int) -> None:
    f = font(38, "bold")
    w = d.textlength(text, font=f)
    d.rounded_rectangle((x, y, x + w + 34, y + 60), radius=14, fill=(*ORANGE, 255))
    d.text((x + 17, y + 9), text, font=f, fill=WHITE)


def scene_overlay(scene: dict, script: dict, platform: str, is_demo: bool, product_img: Image.Image | None) -> Image.Image:
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    disc = script["disclosure"]
    _badge(d, disc["badge"], 48, 160)
    if is_demo:
        f = font(28, "bold")
        label = "DEMO 예시 · 실제 상품 아님"
        tw = d.textlength(label, font=f)
        d.rounded_rectangle((W - tw - 150, 166, W - 118, 216), radius=12, fill=(0, 0, 0, 120))
        d.text((W - tw - 134, 175), label, font=f, fill=(255, 255, 255, 235))
    if scene.get("show_disclosure"):
        f = font(36, "bold")
        lines = wrap_text(d, disc["opening"], f, 900)
        hh = 36 * 1.35 * len(lines) + 30
        d.rounded_rectangle((48, 238, 48 + 940, 238 + hh), radius=16, fill=(*NAVY, 215))
        draw_text_lines(d, lines, f, 72, 252, WHITE, 36 * 1.35)

    text = scene.get("on_screen_text", "")
    if platform == "youtube":
        text = text.replace("프로필 링크", "채널 프로필 링크")
    role = scene["role"]
    if role == "hook":
        f = font(88, "extrabold")
        lines = wrap_smart(d, text, f, 860)
        y0 = 560
        hh = 88 * 1.3 * len(lines) + 70
        d.rounded_rectangle((60, y0 - 35, 1000, y0 - 35 + hh), radius=28, fill=(*NAVY, 200))
        draw_text_lines(d, lines, f, 60, y0, WHITE, 88 * 1.3, align="center", width=940)
    elif role == "cta":
        ov_bg = Image.new("RGBA", (W, H), (*NAVY, 235))
        ov = Image.alpha_composite(ov_bg, ov)
        d = ImageDraw.Draw(ov)
        if product_img is not None:
            pw = 620
            ph = int(product_img.height * pw / product_img.width)
            ov.alpha_composite(product_img.resize((pw, ph), Image.LANCZOS), ((W - pw) // 2, 330))
        f = font(56, "bold")
        lines = wrap_text(d, text, f, 900)
        y = draw_text_lines(d, lines, f, 90, 820, WHITE, 56 * 1.45, label_color=ORANGE, labels=LABELS)
        f2 = font(32, "regular")
        dl = wrap_text(d, disc["endcard"], f2, 900)
        y = max(y + 40, 1260)
        d.rounded_rectangle((70, y - 20, 1010, y + 32 * 1.45 * len(dl) + 20), radius=16, fill=(*CARD, 255))
        draw_text_lines(d, dl, f2, 96, y, SUB, 32 * 1.45)
    else:
        f = font(62, "bold")
        lines = wrap_text(d, text, f, 830)
        lh = 62 * 1.4
        hh = lh * len(lines) + 70
        y0 = 1420 - hh
        if role == "pros_cautions":
            y0 = max(y0, 980)
        d.rounded_rectangle((60, y0, 990, y0 + hh), radius=28, fill=(*NAVY, 222))
        draw_text_lines(d, lines, f, 100, y0 + 33, WHITE, lh, label_color=ORANGE, labels=LABELS)
        if role == "how":
            chips = [r for r in scene.get("fact_refs", [])][:3]
            spec_map = {s["key"]: f"{s['key']} {s['value']}{s.get('unit') or ''}" for s in script.get("_specs", [])}
            cx, cy = 60, y0 - 90
            cf = font(34, "bold")
            for key in chips:
                label = spec_map.get(key)
                if not label:
                    continue
                if len(label) > 26:
                    label = label[:25] + "…"
                tw = d.textlength(label, font=cf)
                if cx + tw + 40 > 1020:
                    cx, cy = 60, cy - 72
                d.rounded_rectangle((cx, cy, cx + tw + 40, cy + 58), radius=29, fill=(*ORANGE, 235))
                d.text((cx + 20, cy + 9), label, font=cf, fill=WHITE)
                cx += tw + 56
    return ov


def _ken_burns(img: Image.Image, t: float, dur: float) -> Image.Image:
    z = 1.0 + 0.06 * (t / max(dur, 0.01))
    cw, ch = W / z, H / z
    x0, y0 = (W - cw) / 2, (H - ch) / 2
    return img.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


def _fade_alpha(ov: Image.Image, a: float) -> Image.Image:
    if a >= 1:
        return ov
    r, g, b, al = ov.split()
    al = al.point(lambda v: int(v * a))
    return Image.merge("RGBA", (r, g, b, al))


def write_srt(scenes: list[dict], path: Path, platform: str) -> None:
    def ts(sec: float) -> str:
        ms = int(round(sec * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    rows = []
    for i, sc in enumerate(scenes, 1):
        text = sc.get("narration") or sc.get("on_screen_text", "")
        if platform == "youtube":
            text = text.replace("프로필 링크", "채널 프로필 링크")
        rows.append(f"{i}\n{ts(sc['start'])} --> {ts(sc['start'] + sc['duration'])}\n{text}\n")
    path.write_text("\n".join(rows), encoding="utf-8")


def render_video(script: dict, images_dir: Path, out_path: Path, platform: str, is_demo: bool,
                 audio_path: Path | None, fps: int) -> dict:
    scenes = script["scenes"]
    total = sum(sc["duration"] for sc in scenes)
    bgs = {}
    for key in {sc["visual"] for sc in scenes}:
        f = images_dir / f"{key}.png"
        img = Image.open(f).convert("RGB").resize((W, H))
        if key in ("problem_scene",):
            img = ImageEnhance.Brightness(img).enhance(0.92)
        bgs[key] = img
    product_img = None
    if (images_dir / "product_original.png").exists():
        product_img = Image.open(images_dir / "product_original.png").convert("RGBA")
    overlays = [scene_overlay(sc, script, platform, is_demo, product_img) for sc in scenes]

    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-"]
    if audio_path:
        cmd += ["-i", str(audio_path)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-level", "4.1", "-r", str(fps), "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    prev_last: np.ndarray | None = None
    try:
        for idx, sc in enumerate(scenes):
            n = int(round(sc["duration"] * fps))
            bg = bgs[sc["visual"]]
            ov = overlays[idx]
            frame = None
            for i in range(n):
                t = i / fps
                base = _ken_burns(bg, t, sc["duration"]).convert("RGBA")
                alpha = min(1.0, t / 0.3) if sc["role"] != "cta" else min(1.0, t / 0.2)
                frame = np.asarray(Image.alpha_composite(base, _fade_alpha(ov, alpha)).convert("RGB"))
                if prev_last is not None and t < FADE:
                    a = t / FADE
                    frame = (frame.astype(np.float32) * a + prev_last.astype(np.float32) * (1 - a)).astype(np.uint8)
                proc.stdin.write(frame.tobytes())
            prev_last = frame
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        code = proc.wait()
    except BrokenPipeError as exc:
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
        raise RenderError(f"ffmpeg 파이프 종료: {err[:500]}") from exc
    if code != 0:
        raise RenderError(f"ffmpeg 실패({code}): {err[:500]}")
    return probe(out_path)


def probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"probed": False}
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate:format=duration,size",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    return {"probed": True, "width": v.get("width"), "height": v.get("height"), "codec": v.get("codec_name"),
            "pix_fmt": v.get("pix_fmt"), "fps": round(int(num) / int(den), 2) if int(den) else 0,
            "duration": round(float(data["format"]["duration"]), 2), "size_bytes": int(data["format"]["size"]),
            "has_audio": a is not None, "audio_codec": a.get("codec_name") if a else None}


def render_content(content_id: str) -> dict:
    settings = get_settings()
    with session_scope() as s:
        c = s.get(Content, content_id)
        p = c.product
        out = Path(c.output_dir)
        script = dict(c.script)
        script["_specs"] = list(p.verified_specs or [])
        narration = get_narration(settings.tts_provider, out)
        results = {}
        variants = ["A", "B"] if settings.render_both_variants else [c.primary_variant]
        files = {}
        for variant in variants:
            sc_script = json.loads(json.dumps(script, ensure_ascii=False))
            hook = sc_script["variants"][variant]["hook"]
            sc_script["scenes"][0]["on_screen_text"] = hook
            sc_script["scenes"][0]["narration"] = hook
            suffix = "" if variant == c.primary_variant else f"_{variant}"
            for platform, name in (("instagram", "reel_final"), ("youtube", "shorts_final")):
                path = out / f"{name}{suffix}.mp4"
                info = render_video(sc_script, out, path, platform, p.is_demo, narration.path, settings.render_fps)
                results[f"{name}{suffix}"] = info
                files[f"{name}{suffix}"] = path.name
            write_srt(sc_script["scenes"], out / f"captions{suffix}.srt", "instagram")
            files[f"captions{suffix}"] = f"captions{suffix}.srt"
        manifest = {
            "content_id": content_id, "product_id": p.id, "is_demo": p.is_demo, "created_at": now_utc().isoformat(),
            "variant_primary": c.primary_variant, "variants_rendered": variants,
            "files": {k: {"file": v, "sha256_16": hashlib.sha256((out / v).read_bytes()).hexdigest()[:16]}
                      for k, v in files.items()},
            "video_info": results,
            "narration": {"provider": narration.provider, "ai_voice": narration.ai_voice, "note": narration.note},
            "music": {"used": False, "note": "배경음 미사용 — 권리 확인된 음원만 추가 가능"},
            "disclosure": script["disclosure"], "generator": script.get("generator"),
            "fact_check_passed": (c.fact_check or {}).get("passed"),
            "cost_estimate_krw": script.get("cost_estimate_krw"),
            "manual_steps_before_publish": [
                "Instagram: 제휴(수수료) 게시물 → 앱에서 '유료 파트너십' 라벨 적용 여부 확인 (Meta 정책)",
                "YouTube: 유료 프로모션 표시가 켜졌는지 Studio 에서 확인",
            ],
        }
        (out / "content_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
        assets = dict(c.assets or {})
        assets["videos"] = files
        assets["content_manifest"] = "content_manifest.json"
        c.assets = assets
        return {"rendered": list(files), "info": results}
