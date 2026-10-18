"""Member 4 public callables (plan.md section 8).

    route_edit(EditRoutingRequest, Runtime) -> EditIntent
    generate_scene(SceneTask, Runtime) -> SceneBuild
    render_preview(PreviewRequest, Runtime) -> ScenePreviewOutcome
    render_final(FinalRenderRequest, Runtime) -> RenderResult

Each returns a validated model or raises StageFailure(PipelineError). Modules never
touch snapshot/event state; progress goes through runtime.report_progress.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from contracts.models import (
    AnimationCue,
    EditIntent,
    EditRoutingRequest,
    FinalRenderRequest,
    PipelineError,
    PreviewRequest,
    RenderResult,
    SceneBuild,
    SceneDraft,
    ScenePreviewOutcome,
    SceneTask,
    StageFailure,
)

from . import agent, router
from .timing import normalize_cues, scene_words
from .worker_client import RenderWorkerClient, setting

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
FIXTURE_SCENES = HERE / "fixtures" / "scenes"
FALLBACK_SOURCE = (HERE / "templates" / "fallback_scene.tsx").read_text()
SOURCE_MEDIA_TYPE = "text/plain"
# Worker failures attributable to the scene source (eligible for a code repair).
SCENE_FAULT_CODES = {"RENDER_FAILED", "FRAME_COUNT_MISMATCH"}


def _fail(code: str, stage: str, message: str, *, retryable: bool = False, scene_id: str | None = None) -> StageFailure:
    return StageFailure(PipelineError(code=code, stage=stage, message=message[:8000], retryable=retryable, scene_id=scene_id))


def _max_repairs(runtime: Any) -> int:
    return max(0, min(2, int(setting(runtime, "SCENE_REPAIR_ATTEMPTS", 2))))


def operation_dir(task: SceneTask) -> str:
    return f"projects/{task.project_id}/scenes/{task.slot.scene_id}/v{task.revision}/{task.job_id}"


def attempt_dir(task: SceneTask, attempt: int | str) -> str:
    """projects/<id>/scenes/<sid>/v<rev>/<operation_id>/a<n> (a fallback build uses 'afb')."""
    return f"{operation_dir(task)}/a{attempt}"


def worker_job_id(operation_id: str, build: SceneBuild) -> str:
    return f"{operation_id}-afb" if build.generation_mode == "fallback" else f"{operation_id}-a{build.repair_attempts}"


def _check_task(task: SceneTask) -> None:
    ctx_slot = next((s for s in task.context.timeline.scenes if s.scene_id == task.slot.scene_id), None)
    problems = []
    if task.project_id != task.context.project_id:
        problems.append("task.project_id != context.project_id")
    if ctx_slot != task.slot:
        problems.append(f"slot {task.slot.scene_id} does not match the context timeline")
    if task.previous_build is not None and task.previous_build.scene_id != task.slot.scene_id:
        problems.append("previous_build belongs to another scene")
    if task.previous_build is not None and task.previous_build.context_hash != task.context.context_hash:
        problems.append("previous_build was made for another context")
    if problems:
        raise _fail("SCENE_TASK_INVALID", "scene_generate", "; ".join(problems), scene_id=task.slot.scene_id)


def _default_cues(task: SceneTask) -> list[AnimationCue]:
    """One cue per turn on its first measured word (used for mock/fallback builds)."""
    words = scene_words(task.context, task.slot)
    turns = {t.dialogue_id: t for t in task.context.script.turns}
    cues = []
    for did in task.slot.dialogue_ids:
        first = next((w for w in words if w.dialogue_id == did), None)
        if first:
            cues.append(AnimationCue(cue_id=f"{did}_start", word_ids=[first.word_id], start_frame=first.start, end_frame=first.end, description=f"{turns[did].intent} turn begins", claim_ids=turns[did].claim_ids))
    return cues


async def _save_build(task: SceneTask, runtime: Any, dir_key: str, source: str, summary: str, cues: list[AnimationCue], mode: str, attempts: int, warnings: list[str]) -> SceneBuild:
    ref = await runtime.write_bytes(f"{dir_key}/Scene.tsx", source.encode(), SOURCE_MEDIA_TYPE)
    return SceneBuild(
        project_id=task.project_id, scene_id=task.slot.scene_id, revision=task.revision,
        context_hash=task.context.context_hash, timeline_hash=task.context.timeline_hash,
        source=ref, summary=summary, cues=cues, generation_mode=mode, repair_attempts=attempts, warnings=warnings,
    )


async def _validate(task: SceneTask, client: RenderWorkerClient, build: SceneBuild) -> list[str]:
    req = PreviewRequest(project_id=task.project_id, job_id=f"{task.job_id}-validate", context=task.context, slot=task.slot, build=build)
    res = await client.validate(req)
    return [] if res.valid else (res.diagnostics or ["validator returned invalid without diagnostics"])


_OUTPUT_PROBLEM_MARKERS = ("INVALID", "SCHEMA", "PARSE", "VALIDATION", "STRUCTURED", "MALFORMED", "JSON")
_TRANSPORT_MARKERS = ("UNAVAILABLE", "TIMEOUT", "AUTH", "FORBIDDEN", "PERMISSION", "RATE", "QUOTA", "NETWORK", "CONNECT", "CONFIG")


def _is_output_problem(error: PipelineError) -> bool:
    """A runtime.structured failure caused by the model's answer (counts as a repair attempt),
    as opposed to a provider/transport/config failure (raised as a stage error).
    Core's error codes are not fixed by the contract, so classify by marker, transport first."""
    code = error.code.upper()
    return not any(m in code for m in _TRANSPORT_MARKERS) and any(m in code for m in _OUTPUT_PROBLEM_MARKERS)


def _is_transport_error(e: BaseException) -> bool:
    names = {c.__name__ for c in type(e).__mro__}
    return bool(names & {"HTTPError", "APIConnectionError", "APITimeoutError", "AuthenticationError", "PermissionDeniedError", "RateLimitError", "InternalServerError", "NotFoundError", "TimeoutError", "ConnectError"})


async def _draft(task: SceneTask, runtime: Any, client: RenderWorkerClient, dir_key: str, previous_source: str | None, feedback: list[str] | None) -> SceneDraft:
    if agent.structured_mode(runtime) == "tool_calling":
        counter = {"n": 0}

        async def validate_candidate(source: str) -> list[str]:
            counter["n"] += 1
            build = await _save_build(task, runtime, f"{dir_key}/candidates/{counter['n']:02d}", source, "candidate", [], "agent", 0, [])
            return await _validate(task, client, build)

        return await agent.draft_with_tools(task, runtime, previous_source, feedback, validate_candidate)
    return await agent.draft_json_prompt(task, runtime, previous_source, feedback)


async def _fallback_build(task: SceneTask, runtime: Any, client: RenderWorkerClient, attempts: int, reason: str) -> SceneBuild:
    log.warning("scene %s rev %s: using deterministic fallback template: %s", task.slot.scene_id, task.revision, reason)
    dir_key = attempt_dir(task, "fb")
    build = await _save_build(
        task, runtime, dir_key, FALLBACK_SOURCE, f"Deterministic fallback layout for scene {task.slot.index} (agent output unusable).",
        _default_cues(task), "fallback", min(2, attempts), [f"FALLBACK: {reason}"[:2000]],
    )
    diags = await _validate(task, client, build)
    if diags:
        raise _fail("SCENE_FALLBACK_INVALID", "scene_generate", "fallback template failed validation: " + "; ".join(diags[:5]), scene_id=task.slot.scene_id)
    await runtime.write_json(f"{dir_key}/build.json", build)
    return build


async def _agent_loop(task: SceneTask, runtime: Any, client: RenderWorkerClient, start_attempt: int, previous_source: str | None, feedback: list[str] | None) -> SceneBuild:
    """Generate -> validate -> repair, at most two corrective attempts in total; fallback when exhausted."""
    max_repairs = _max_repairs(runtime)
    attempt = start_attempt
    diags: list[str] = list(feedback or [])
    while True:
        dir_key = attempt_dir(task, attempt)
        try:
            draft = await _draft(task, runtime, client, dir_key, previous_source, feedback)
        except StageFailure as e:
            if not _is_output_problem(e.error):
                raise
            diags = [f"model output was not a valid SceneDraft: {e.error.message}"]
            draft = None
        except Exception as e:
            if _is_transport_error(e):
                raise _fail("SCENE_AGENT_UNAVAILABLE", "scene_generate", f"Nemotron call failed: {e!r}", retryable=True, scene_id=task.slot.scene_id) from e
            diags = [f"scene agent did not produce a SceneDraft: {type(e).__name__}: {e}"[:2000]]
            draft = None
        if draft is not None:
            cues, cue_errors, cue_warnings = normalize_cues(draft.cues, task.context, task.slot)
            build = await _save_build(task, runtime, dir_key, draft.source_code, draft.summary, cues, "agent", attempt, cue_warnings)
            diags = cue_errors + await _validate(task, client, build)
            await runtime.write_json(f"{dir_key}/validation.json", {"valid": not diags, "diagnostics": diags, "warnings": cue_warnings})
            if not diags:
                await runtime.write_json(f"{dir_key}/build.json", build)
                return build
            previous_source = draft.source_code
        else:
            await runtime.write_json(f"{dir_key}/validation.json", {"valid": False, "diagnostics": diags})
        if attempt >= max_repairs:
            return await _fallback_build(task, runtime, client, attempt, f"agent output failed after {attempt} repair attempt(s): " + " | ".join(diags[:3]))
        attempt += 1
        feedback = diags


def _mock_source(task: SceneTask) -> tuple[str, str]:
    sid = task.slot.scene_id
    if task.edit_instruction:
        f = FIXTURE_SCENES / f"{sid}_edit.tsx"
        return (f.read_text() if f.exists() else FALLBACK_SOURCE), f"MOCK edit of {sid} (rev {task.revision}): {task.edit_instruction}"
    f = FIXTURE_SCENES / f"{sid}.tsx"
    return (f.read_text() if f.exists() else FALLBACK_SOURCE), f"MOCK fixture scene {task.slot.index}"


# ---------------------------------------------------------------- public callables
async def route_edit(request: EditRoutingRequest, runtime: Any) -> EditIntent:
    return await router.route(request, runtime)


async def generate_scene(request: SceneTask, runtime: Any) -> SceneBuild:
    task = request
    _check_task(task)
    client = RenderWorkerClient.from_runtime(runtime)
    # Recorded so a later preview repair of this operation keeps the user's correction.
    await runtime.write_json(f"{operation_dir(task)}/task.json", {
        "edit_instruction": task.edit_instruction,
        "previous_source": task.previous_build.source.key if task.previous_build else None,
    })
    if runtime.mock_mode:
        source, summary = _mock_source(task)
        dir_key = attempt_dir(task, 0)
        build = await _save_build(task, runtime, dir_key, source, summary, _default_cues(task), "mock", 0, ["MOCK mode: deterministic fixture source, no model call"])
        diags = await _validate(task, client, build)
        if diags:
            raise _fail("SCENE_SOURCE_INVALID", "scene_generate", "mock fixture source failed validation: " + "; ".join(diags[:5]), scene_id=task.slot.scene_id)
        await runtime.write_json(f"{dir_key}/build.json", build)
        return build
    previous_source = runtime.path(task.previous_build.source.key).read_text() if task.previous_build else None
    return await _agent_loop(task, runtime, client, 0, previous_source, None)


async def render_preview(request: PreviewRequest, runtime: Any) -> ScenePreviewOutcome:
    slot, op = request.slot, request.job_id
    build = request.build
    if build.scene_id != slot.scene_id or build.context_hash != request.context.context_hash or build.timeline_hash != request.context.timeline_hash:
        raise _fail("PREVIEW_REQUEST_INVALID", "scene_preview", "build does not match the slot/context/timeline", scene_id=slot.scene_id)
    client = RenderWorkerClient.from_runtime(runtime)
    expected = slot.end_frame - slot.start_frame

    async def progress(p: float) -> None:
        await runtime.report_progress(project_id=request.project_id, job_id=op, stage="scene_preview", progress=p, scene_id=slot.scene_id)

    task = SceneTask(project_id=request.project_id, job_id=op, context=request.context, slot=slot, revision=build.revision)
    recorded = runtime.path(f"{operation_dir(task)}/task.json")
    if recorded.exists():
        task = task.model_copy(update={"edit_instruction": json.loads(recorded.read_text()).get("edit_instruction")})
    while True:
        result = await client.run(request.model_copy(update={"job_id": worker_job_id(op, build), "build": build}), progress)
        if result.status == "completed":
            if result.video is None or result.duration_frames != expected:
                raise _fail("PREVIEW_OUTPUT_INVALID", "scene_preview", f"preview has {result.duration_frames} frames, expected {expected}", scene_id=slot.scene_id)
            return ScenePreviewOutcome(project_id=request.project_id, build=build, render=result)
        err = result.error or PipelineError(code="RENDER_FAILED", stage="scene_preview", message="worker reported failure without an error", retryable=True, scene_id=slot.scene_id)
        if err.code not in SCENE_FAULT_CODES:
            raise StageFailure(err)
        if build.generation_mode == "agent" and build.repair_attempts < _max_repairs(runtime) and not runtime.mock_mode:
            source = runtime.path(build.source.key).read_text()
            build = await _agent_loop(task, runtime, client, build.repair_attempts + 1, source, [f"Preview render failed ({err.code}): {err.message}"])
            continue
        if build.generation_mode != "fallback":
            build = await _fallback_build(task, runtime, client, build.repair_attempts, f"preview render failed: {err.code}: {err.message[:500]}")
            continue
        raise StageFailure(err)


async def render_final(request: FinalRenderRequest, runtime: Any) -> RenderResult:
    ctx = request.context
    ids = sorted(b.scene_id for b in request.builds)
    if ids != [s.scene_id for s in sorted(ctx.timeline.scenes, key=lambda s: s.index)]:
        raise _fail("FINAL_REQUEST_INVALID", "final", f"need one build per scene, got {ids}")
    stale = [b.scene_id for b in request.builds if b.context_hash != ctx.context_hash or b.timeline_hash != ctx.timeline_hash]
    if stale:
        raise _fail("FINAL_REQUEST_INVALID", "final", f"builds made for another context/timeline: {stale}")
    client = RenderWorkerClient.from_runtime(runtime)

    async def progress(p: float) -> None:
        await runtime.report_progress(project_id=request.project_id, job_id=request.job_id, stage="final", progress=p, scene_id=None)

    result = await client.run(request, progress)
    if result.status == "completed" and result.video is not None and result.duration_frames == 1800:
        return result
    raise StageFailure(result.error or PipelineError(code="FINAL_OUTPUT_INVALID", stage="final", message=f"final render returned {result.duration_frames} frames", retryable=True))
