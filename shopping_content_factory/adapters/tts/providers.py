"""내레이션 음원 공급.

- none: 무음 트랙 + 자막만 (기본값, 비용 0, 권리 문제 없음)
- user_file: 사용자가 녹음한 파일을 outputs/<content_id>/narration.(wav|mp3|m4a) 로 넣으면 사용
- 유료 TTS 는 모델 종료 일정·단가 미확인으로 MVP 에서 보류 (docs/COST_MODEL.md)
  OpenAI 정책상 AI 음성은 '사람 목소리가 아님'을 청취자에게 고지해야 한다.
"""
from __future__ import annotations

from pathlib import Path


class TTSResult:
    def __init__(self, path: Path | None, provider: str, ai_voice: bool, note: str = ""):
        self.path = path
        self.provider = provider
        self.ai_voice = ai_voice
        self.note = note


def get_narration(provider: str, content_dir: Path) -> TTSResult:
    if provider == "user_file":
        for ext in ("wav", "mp3", "m4a"):
            p = content_dir / f"narration.{ext}"
            if p.exists():
                return TTSResult(p, "user_file", ai_voice=False, note="사용자 제공 음원")
        return TTSResult(None, "user_file", ai_voice=False, note="narration 파일 없음 → 무음 + 자막")
    return TTSResult(None, "none", ai_voice=False, note="무음 + 자막 (TTS 미사용)")
