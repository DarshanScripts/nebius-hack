from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

FPS = 30
SAMPLE_RATE = 48_000
SAMPLES_PER_FRAME = SAMPLE_RATE // FPS  # 1600
MAX_SPEEDUP = 1.08
SPEEDUP_STEP = 0.005


def _get(settings: Mapping[str, Any], name: str, default: Any = None) -> Any:
    for key in (name, name.lower(), name.upper()):
        value = settings.get(key)
        if value not in (None, ""):
            return value
    return default


@dataclass(frozen=True)
class VoiceSettings:
    voice_api_url: str
    voice_api_key: str
    voice_model: str
    voice_timeout: float
    alignment_api_url: str
    alignment_api_key: str
    alignment_timeout: float
    max_attempts: int = 3
    resynth_attempts: int = 1
    min_align_score: float = 0.2
    min_asr_similarity: float = 0.6

    @classmethod
    def from_mapping(cls, settings: Mapping[str, Any]) -> "VoiceSettings":
        return cls(
            voice_api_url=str(_get(settings, "VOICE_API_URL", "http://localhost:8002/v1/tts")),
            voice_api_key=str(_get(settings, "VOICE_API_KEY", "")),
            voice_model=str(_get(settings, "VOICE_MODEL", "chatterbox-turbo")),
            voice_timeout=float(_get(settings, "VOICE_TIMEOUT_SECONDS", 180)),
            alignment_api_url=str(_get(settings, "ALIGNMENT_API_URL", "http://localhost:8003/v1/align")),
            alignment_api_key=str(_get(settings, "ALIGNMENT_API_KEY", "")),
            alignment_timeout=float(_get(settings, "ALIGNMENT_TIMEOUT_SECONDS", 180)),
        )
