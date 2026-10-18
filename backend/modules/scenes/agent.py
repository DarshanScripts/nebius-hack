"""One isolated scene agent invocation (plan.md section 8).

Strategy follows the member-1 capability decision in NEMOTRON_STRUCTURED_MODE:
- ``tool_calling``: LangChain ``create_agent`` with Nemotron (``runtime.llm``), scoped tools
  ``read_scene_context`` / ``read_previous_source`` / ``validate_scene_source`` and a
  ``ToolStrategy(SceneDraft)`` structured response (the submit step).
- ``json_prompt``: one ``runtime.structured(schema=SceneDraft)`` call; validation feedback
  is handled by the bounded repair loop in ``service.py``.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from contracts.models import SceneDraft, SceneTask

from .timing import scene_words
from .worker_client import setting

AUTHORING_GUIDE = (Path(__file__).parent / "scene_authoring.md").read_text()
MAX_AGENT_STEPS = 14


def scene_brief(task: SceneTask) -> dict[str, Any]:
    """Everything the agent may know about its scene, from the immutable context only."""
    ctx, slot = task.context, task.slot
    words = scene_words(ctx, slot)
    turns = []
    for t in ctx.script.turns:
        entry: dict[str, Any] = {"dialogue_id": t.dialogue_id, "scene_index": t.scene_index, "speaker": t.speaker_id, "intent": t.intent, "text": t.text, "claim_ids": t.claim_ids}
        if t.dialogue_id in slot.dialogue_ids:
            entry["words"] = [{"word_id": w.word_id, "text": w.text, "start": w.start, "end": w.end} for w in words if w.dialogue_id == t.dialogue_id]
        turns.append(entry)
    image = next((s for s in ctx.images.selections if s.query.scene_index == slot.index), None)
    return {
        "topic": ctx.research.topic,
        "reel_title": ctx.script.title,
        "scene": {"scene_id": slot.scene_id, "index": slot.index, "of": 6, "duration_frames": slot.end_frame - slot.start_frame, "fps": 30, "interior": [12, slot.end_frame - slot.start_frame - 12], "dialogue_ids": slot.dialogue_ids},
        "dialogue": turns,
        "claims": [c.model_dump(mode="json") for c in ctx.research.claims],
        "uncertainties": ctx.research.uncertainties,
        "image": None if image is None else {"status": image.status, "description": image.description, "reason": image.reason},
    }


def _user_message(task: SceneTask, previous_source: str | None, feedback: list[str] | None, include_context: bool) -> str:
    parts = [f"Write Scene.tsx for scene {task.slot.scene_id} (index {task.slot.index} of 6)."]
    if include_context:
        parts.append("Scene brief (word frames are scene-local, half-open):\n" + json.dumps(scene_brief(task), ensure_ascii=False))
    if task.edit_instruction:
        parts.append(f"USER CORRECTION for this scene only (keep timing, dialogue and audio unchanged): {task.edit_instruction}")
    if previous_source:
        parts.append("Previous source of this scene (revise it, do not start over unless needed):\n```tsx\n" + previous_source + "\n```")
    if feedback:
        parts.append("The last candidate FAILED validation/rendering. Fix every issue:\n- " + "\n- ".join(feedback[:40]))
    parts.append("Return a SceneDraft: complete source_code, one-sentence summary, and cues.")
    return "\n\n".join(parts)


async def draft_json_prompt(task: SceneTask, runtime: Any, previous_source: str | None, feedback: list[str] | None) -> SceneDraft:
    messages = [
        {"role": "system", "content": AUTHORING_GUIDE},
        {"role": "user", "content": _user_message(task, previous_source, feedback, include_context=True)},
    ]
    return await runtime.structured(messages=messages, schema=SceneDraft)


async def draft_with_tools(
    task: SceneTask,
    runtime: Any,
    previous_source: str | None,
    feedback: list[str] | None,
    validate: Callable[[str], Awaitable[list[str]]],
) -> SceneDraft:
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy
    from langchain_core.tools import tool

    brief = json.dumps(scene_brief(task), ensure_ascii=False)

    @tool
    def read_scene_context() -> str:
        """Read this scene's brief: slot, duration, all dialogue (with this scene's measured word frames), claims, image."""
        return brief

    @tool
    def read_previous_source() -> str:
        """Read the previous source of THIS scene (for edits/repairs), or 'none'."""
        return previous_source or "none"

    @tool
    async def validate_scene_source(source_code: str) -> str:
        """Compile and type-check a candidate Scene.tsx in the renderer. Returns 'OK' or the diagnostics."""
        diags = await validate(source_code)
        return "OK" if not diags else "INVALID:\n" + "\n".join(diags[:40])

    agent = create_agent(
        model=runtime.llm,
        tools=[read_scene_context, read_previous_source, validate_scene_source],
        system_prompt=AUTHORING_GUIDE + "\n\nCall read_scene_context first. Validate your source with validate_scene_source before submitting the SceneDraft.",
        response_format=ToolStrategy(SceneDraft),
    )
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": _user_message(task, previous_source, feedback, include_context=False)}]},
        config={"recursion_limit": 2 * MAX_AGENT_STEPS + 1},
    )
    draft = result.get("structured_response")
    if not isinstance(draft, SceneDraft):
        raise ValueError("scene agent finished without a SceneDraft structured response")
    return draft


def structured_mode(runtime: Any) -> str:
    return str(setting(runtime, "NEMOTRON_STRUCTURED_MODE", "json_prompt")).strip().lower()
