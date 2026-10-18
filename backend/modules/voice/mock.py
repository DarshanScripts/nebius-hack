from __future__ import annotations

import numpy as np

from contracts.models import AlignmentResult, WordTiming

from .audio import sha256_hex
from .config import SAMPLE_RATE
from .text import tokenize

MOCK_CLIP_MS = 4000
MOCK_LEAD_MS = 120
MOCK_TAIL_MS = 120
SPEAKER_HZ = {"sundar": 190.0, "jensen": 125.0}


def mock_word_spans(transcript: str, clip_ms: int = MOCK_CLIP_MS) -> list[tuple[str, int, int]]:
    """Deterministic, explicitly synthetic clip-local timings: words share the speech span by length."""
    tokens = [t for t in tokenize(transcript) if t.meaningful]
    weights = [len(t.norm) + 2 for t in tokens]
    span = clip_ms - MOCK_LEAD_MS - MOCK_TAIL_MS
    gap = 20
    usable = span - gap * (len(tokens) - 1)
    out, cursor, acc = [], MOCK_LEAD_MS, 0
    for tok, weight in zip(tokens, weights):
        acc += weight
        end = MOCK_LEAD_MS + round(usable * acc / sum(weights)) + gap * (len(out))
        out.append((tok.text, cursor, max(end, cursor + 1)))
        cursor = end + gap
    return out


def mock_audio(speaker_id: str, transcript: str) -> np.ndarray:
    """4000 ms of speech-like tone bursts that follow the mock word timings (not real speech)."""
    n = SAMPLE_RATE * MOCK_CLIP_MS // 1000
    t = np.arange(n) / SAMPLE_RATE
    f0 = SPEAKER_HZ.get(speaker_id, 150.0)
    tone = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3))
    env = np.zeros(n)
    for i, (_, start, end) in enumerate(mock_word_spans(transcript)):
        a, b = start * SAMPLE_RATE // 1000, end * SAMPLE_RATE // 1000
        ramp = min((b - a) // 4, SAMPLE_RATE // 100)
        shape = np.ones(b - a)
        if ramp:
            shape[:ramp] = np.linspace(0, 1, ramp)
            shape[-ramp:] = np.linspace(1, 0, ramp)
        env[a:b] = shape * (0.8 + 0.2 * np.sin(i))
    return (0.3 * env * tone).astype(np.float32)


def mock_alignment(dialogue_id: str, transcript: str, wav: bytes) -> AlignmentResult:
    words = [
        WordTiming(word_id=f"{dialogue_id}_w{i:03d}", text=text, start_ms=s, end_ms=e)
        for i, (text, s, e) in enumerate(mock_word_spans(transcript), 1)
    ]
    return AlignmentResult(dialogue_id=dialogue_id, audio_sha256=sha256_hex(wav), transcript=transcript, words=words)
