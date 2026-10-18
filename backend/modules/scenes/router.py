"""Edit router: message -> EditIntent. Never executes the change.

The target scene is decided deterministically (explicit "scene six" / "scene 6" /
"s06" mention or the UI-selected scene). In live mode Nemotron structured output may
refine the instruction or flag an unsupported global edit, but it can never pick or
change the target: a model-proposed scene that disagrees is rejected.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from contracts.models import EditIntent, EditRoutingRequest

log = logging.getLogger(__name__)

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "last": 6, "final": 6}
_NUM = r"(?:[1-6]|one|two|three|four|five|six)"
_SCENE_REF = re.compile(
    rf"\bscenes?\s*(?:no\.?|number|#)?\s*(?P<num>{_NUM})\b"
    rf"|\b(?P<ord>first|second|third|fourth|fifth|sixth|last|final)\s+scene\b"
    r"|\bs0?(?P<sid>[1-6])\b",
    re.IGNORECASE,
)
_MULTI = re.compile(rf"\bscenes\s+{_NUM}\s*(?:,|and|&|to|-)\s*{_NUM}\b", re.IGNORECASE)
_GLOBAL = re.compile(
    r"\b(all|every|each)\s+scenes?\b|\b(whole|entire)\s+(video|reel)\b|\bvoices?\b|\baudio\b|\bdialogue\b|\bscript\b"
    r"|\bnarrat\w*|\bmusic\b|\bduration\b|\blonger\b|\bshorter\b|\btiming\b|\bspeed\b|\bcaptions?\b|\bsubtitles?\b"
    r"|\bcharacters?\b|\btheme\b|\bnew reel\b",
    re.IGNORECASE,
)


def mentioned_scenes(message: str) -> list[str]:
    found: list[str] = []
    for m in _SCENE_REF.finditer(message):
        if m.group("num"):
            n = m.group("num").lower()
            idx = int(n) if n.isdigit() else NUMBER_WORDS[n]
        elif m.group("ord"):
            idx = ORDINALS[m.group("ord").lower()]
        else:
            idx = int(m.group("sid"))
        sid = f"s{idx:02d}"
        if sid not in found:
            found.append(sid)
    return found


def _unsupported(message: str, reason: str) -> EditIntent:
    return EditIntent(action="unsupported", scene_id=None, instruction=message, reason=reason)


def route_deterministic(request: EditRoutingRequest) -> EditIntent:
    msg = request.message.strip()
    valid = set(request.scene_ids)
    if not msg:
        return _unsupported(msg, "Empty message.")
    if _MULTI.search(msg):
        return _unsupported(msg, "This edit names several scenes. Select one scene to change, or create a new reel.")
    mentioned = mentioned_scenes(msg)
    if g := _GLOBAL.search(msg):
        return _unsupported(msg, f"'{g.group(0)}' affects audio, timing or the shared reel layout, which are locked. Scene edits can only change one scene's visuals; create a new reel for this.")
    if len(mentioned) > 1:
        return _unsupported(msg, f"This message mentions {', '.join(mentioned)}. Select exactly one scene to change.")
    selected = request.selected_scene_id
    if selected is not None and selected not in valid:
        return _unsupported(msg, f"Selected scene {selected} does not exist.")
    if selected and mentioned and mentioned[0] != selected:
        return _unsupported(msg, f"The selected scene is {selected} but the message refers to {mentioned[0]}. Select the scene you mean.")
    target = selected or (mentioned[0] if mentioned else None)
    if target is None:
        return _unsupported(msg, "Which scene? Select a scene or say e.g. 'scene 6'.")
    if target not in valid:
        return _unsupported(msg, f"{target} is not one of this reel's scenes.")
    return EditIntent(action="edit_scene", scene_id=target, instruction=msg)


async def route(request: EditRoutingRequest, runtime: Any) -> EditIntent:
    decided = route_deterministic(request)
    if runtime.mock_mode or decided.action != "edit_scene":
        return decided
    messages = [
        {"role": "system", "content": (
            "You route a user's correction for a 6-scene educational video. The target scene is ALREADY decided; "
            "do not change it. Rewrite the user's message as a precise visual instruction for that one scene's animation "
            "(diagram, labels, motion, emphasis). If the request needs changing spoken audio, dialogue, captions, timing, "
            "characters, the theme, or more than one scene, return action 'unsupported' with a short reason."
        )},
        {"role": "user", "content": f"Target scene: {decided.scene_id}\nValid scenes: {', '.join(request.scene_ids)}\nUser message: {request.message}"},
    ]
    try:
        refined: EditIntent = await runtime.structured(messages=messages, schema=EditIntent)
    except Exception as e:  # refinement is optional; the deterministic intent is complete and valid
        log.warning("edit-router refinement failed, using the raw instruction for %s: %r", decided.scene_id, e)
        return decided
    if refined.action == "unsupported":
        return _unsupported(request.message, refined.reason or "This change cannot be made as a single-scene visual edit.")
    if refined.scene_id not in (None, decided.scene_id):
        log.warning("edit-router model proposed %s for a message targeting %s; keeping %s", refined.scene_id, decided.scene_id, decided.scene_id)
        return decided
    instruction = refined.instruction.strip() or decided.instruction
    return EditIntent(action="edit_scene", scene_id=decided.scene_id, instruction=instruction)
