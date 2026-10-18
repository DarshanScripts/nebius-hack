"""Scene-local word timing and cue normalisation (plan.md section 7/9).

Audio offsets are authoritative: a cue that names word ids gets its frames
recomputed from the measured words; the LLM cannot move them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from contracts.models import AnimationCue, SceneContext, SceneSlot

FPS = 30


@dataclass(frozen=True)
class LocalWord:
    word_id: str
    text: str
    dialogue_id: str
    start: int  # scene-local frames, half-open
    end: int


def scene_words(context: SceneContext, slot: SceneSlot) -> list[LocalWord]:
    timing = {u.dialogue_id: u for u in context.timeline.utterances}
    out: list[LocalWord] = []
    for utt in context.audio.utterances:
        if utt.dialogue_id not in slot.dialogue_ids:
            continue
        t = timing[utt.dialogue_id]
        for w in utt.words:
            gs = min(t.end_frame - 1, t.start_frame + math.floor(w.start_ms * FPS / 1000))
            ge = max(gs + 1, min(t.end_frame, t.start_frame + math.ceil(w.end_ms * FPS / 1000)))
            out.append(LocalWord(w.word_id, w.text, utt.dialogue_id, gs - slot.start_frame, ge - slot.start_frame))
    return out


def normalize_cues(cues: list[AnimationCue], context: SceneContext, slot: SceneSlot) -> tuple[list[AnimationCue], list[str], list[str]]:
    """Returns (normalised cues, errors, warnings)."""
    duration = slot.end_frame - slot.start_frame
    words = {w.word_id: w for w in scene_words(context, slot)}
    claims = {c.claim_id for c in context.research.claims}
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    out: list[AnimationCue] = []
    for c in cues:
        if c.cue_id in seen:
            errors.append(f"cue {c.cue_id}: duplicate cue_id")
            continue
        seen.add(c.cue_id)
        unknown_claims = [x for x in c.claim_ids if x not in claims]
        if unknown_claims:
            errors.append(f"cue {c.cue_id}: unknown claim ids {unknown_claims}")
        if c.word_ids:
            missing = [w for w in c.word_ids if w not in words]
            if missing:
                errors.append(f"cue {c.cue_id}: word ids not in this scene's dialogue: {missing}")
                continue
            start = min(words[w].start for w in c.word_ids)
            end = max(words[w].end for w in c.word_ids)
            if (start, end) != (c.start_frame, c.end_frame):
                warnings.append(f"cue {c.cue_id}: frames recomputed from measured words ({c.start_frame},{c.end_frame}) -> ({start},{end})")
            c = c.model_copy(update={"start_frame": start, "end_frame": end})
        elif not (0 <= c.start_frame < c.end_frame <= duration):
            errors.append(f"cue {c.cue_id}: untimed cue must satisfy 0 <= start < end <= {duration}")
            continue
        out.append(c)
    return out, errors, warnings
