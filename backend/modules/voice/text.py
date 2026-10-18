from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from contracts.models import WordTiming

from .errors import fail

_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'"})


@dataclass(frozen=True)
class Token:
    text: str
    norm: str

    @property
    def meaningful(self) -> bool:
        return bool(self.norm)


def normalize_transcript(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _norm(token: str) -> str:
    token = unicodedata.normalize("NFKC", token).translate(_APOSTROPHES).lower()
    return "".join(ch for ch in token if ch.isalnum() or ch == "'").strip("'")


def tokenize(text: str) -> list[Token]:
    return [Token(t, _norm(t)) for t in normalize_transcript(text).split(" ") if t]


def _similar(a: str, b: str) -> bool:
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def match_words(expected: list[Token], got: list[WordTiming]) -> dict[int, WordTiming]:
    """Map expected-token index -> aligner word, tolerating punctuation/tokenization differences."""
    matcher = difflib.SequenceMatcher(
        None, [t.norm for t in expected], [_norm(w.text) for w in got], autojunk=False
    )
    mapping: dict[int, WordTiming] = {}
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            mapping.update({a0 + k: got[b0 + k] for k in range(a1 - a0)})
        elif tag == "replace" and a1 - a0 == b1 - b0:
            for k in range(a1 - a0):
                if _similar(expected[a0 + k].norm, _norm(got[b0 + k].text)):
                    mapping[a0 + k] = got[b0 + k]
    return mapping


def build_words(
    dialogue_id: str, transcript: str, got: list[WordTiming], duration_ms: int
) -> tuple[list[WordTiming], list[WordTiming]]:
    """Return (canonical words, provider words) after validating coverage and timing.

    Canonical words carry the intended transcript text, contiguous IDs, ordered non-overlapping
    clip-local millisecond times and fit inside the clip. Provider words are untouched.
    """
    tokens = tokenize(transcript)
    mapping = match_words(tokens, got)
    missing = [t.text for i, t in enumerate(tokens) if t.meaningful and i not in mapping]
    if missing:
        raise fail(
            "ALIGNMENT_INCOMPLETE",
            f"{dialogue_id}: aligner omitted {len(missing)} spoken word(s): {', '.join(missing[:8])}",
            retryable=True,
        )
    words: list[WordTiming] = []
    cursor = 0
    for i, token in enumerate(tokens):
        if not token.meaningful:
            continue
        src = mapping[i]
        start = max(src.start_ms, cursor)
        end = min(max(src.end_ms, start + 1), duration_ms)
        if start >= end:
            raise fail(
                "ALIGNMENT_INVALID",
                f"{dialogue_id}: word '{token.text}' falls outside the {duration_ms} ms clip "
                f"(provider {src.start_ms}-{src.end_ms} ms)",
                retryable=True,
            )
        words.append(
            WordTiming(
                word_id=f"{dialogue_id}_w{len(words) + 1:03d}", text=token.text, start_ms=start, end_ms=end
            )
        )
        cursor = end
    if not words:
        raise fail("ALIGNMENT_INCOMPLETE", f"{dialogue_id}: transcript has no alignable words", retryable=True)
    return words, got


def _ts(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list[WordTiming], max_words: int = 6, max_ms: int = 2500) -> str:
    cues: list[list[WordTiming]] = []
    for word in words:
        cur = cues[-1] if cues else None
        if (
            cur is None
            or len(cur) >= max_words
            or word.end_ms - cur[0].start_ms > max_ms
            or re.search(r"[.!?]$", cur[-1].text)
        ):
            cues.append([word])
        else:
            cur.append(word)
    blocks = [
        f"{i}\n{_ts(c[0].start_ms)} --> {_ts(c[-1].end_ms)}\n{' '.join(w.text for w in c)}\n"
        for i, c in enumerate(cues, 1)
    ]
    return "\n".join(blocks)
