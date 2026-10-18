"""Cross-field checks for content outputs. Each returns a list of problems; empty means valid."""
from __future__ import annotations

import re

from contracts.models import Claim, DialogueScript, ImageBundle, ResearchBundle

SPEAKERS = ("sundar", "jensen")
MIN_WORDS, MAX_WORDS = 110, 145  # target 120-135; small tolerance before forcing a repair
STAGE_DIRECTION = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]+\*|^\s*(sundar|jensen|pichai|huang)\b[^:]{0,20}:", re.I)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", text))


def claim_problems(claims: list[Claim], source_ids: set[str]) -> list[str]:
    problems = []
    seen = set()
    for c in claims:
        if c.claim_id in seen:
            problems.append(f"duplicate claim_id {c.claim_id}")
        seen.add(c.claim_id)
        unknown = set(c.source_ids) - source_ids
        if unknown:
            problems.append(f"{c.claim_id} cites unknown sources {sorted(unknown)}")
        if c.evidence_type == "inference" and not (c.caveat or "").strip():
            problems.append(f"{c.claim_id} is an inference and needs a caveat")
        if not c.text.strip():
            problems.append(f"{c.claim_id} has empty text")
    return problems


def script_problems(script: DialogueScript, research: ResearchBundle) -> list[str]:
    problems = []
    claim_ids = {c.claim_id for c in research.claims}
    for i, t in enumerate(script.turns, start=1):
        if t.dialogue_id != f"d{i:03d}" or t.order != i:
            problems.append(f"turn {i} must be d{i:03d} with order {i}")
        if t.scene_index != (i - 1) // 2 + 1:
            problems.append(f"{t.dialogue_id} must be in scene {(i - 1) // 2 + 1}")
        if t.speaker_id != SPEAKERS[(i - 1) % 2]:
            problems.append(f"{t.dialogue_id} must be spoken by {SPEAKERS[(i - 1) % 2]} (speakers alternate, Sundar first)")
        unknown = set(t.claim_ids) - claim_ids
        if unknown:
            problems.append(f"{t.dialogue_id} references unknown claims {sorted(unknown)}")
        # Same rule as core's contracts.validation.validate_script.
        if t.intent != "question" and not t.text.rstrip().endswith("?") and not t.claim_ids:
            problems.append(f"{t.dialogue_id} ({t.intent}) states something, so it must cite at least one claim_id "
                            "(only questions or turns ending with '?' may cite none)")
        if STAGE_DIRECTION.search(t.text):
            problems.append(f"{t.dialogue_id} contains stage directions or a speaker label; spoken words only")
    total = sum(word_count(t.text) for t in script.turns)
    if not MIN_WORDS <= total <= MAX_WORDS:
        problems.append(f"script has {total} spoken words; it must have 120-135")
    return problems


def image_problems(bundle: ImageBundle, script: DialogueScript) -> list[str]:
    problems = []
    if sorted(s.query.scene_index for s in bundle.selections) != [1, 2, 3, 4, 5, 6]:
        problems.append("selections must cover scenes 1-6 exactly once")
    for s in bundle.selections:
        expected = [t.dialogue_id for t in script.turns if t.scene_index == s.query.scene_index]
        if s.query.dialogue_ids != expected:
            problems.append(f"scene {s.query.scene_index} must reference {expected}")
        if s.status == "selected" and not (s.asset and s.image_url):
            problems.append(f"scene {s.query.scene_index} is selected without asset/image_url")
        if s.status == "unavailable" and (s.asset or not s.reason):
            problems.append(f"scene {s.query.scene_index} is unavailable and needs a reason and no asset")
    return problems
