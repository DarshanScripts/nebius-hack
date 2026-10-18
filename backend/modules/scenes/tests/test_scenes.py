"""Offline tests for the scenes module (no render worker, no model calls).

Run: PYTHONPATH="$PWD/.bootstrap:$PWD" .venv/bin/python -m pytest backend/modules/scenes/tests -q
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from contracts.models import (
    AnimationCue,
    EditIntent,
    EditRoutingRequest,
    PipelineError,
    PreviewRequest,
    RenderResult,
    SceneDraft,
    SceneTask,
    SourceValidationResult,
    StageFailure,
)
from backend.modules.scenes import service
from backend.modules.scenes.fixtures.context import build_fixture_context
from backend.modules.scenes.fixtures.runtime import FixtureRuntime
from backend.modules.scenes.router import route_deterministic
from backend.modules.scenes.timing import normalize_cues, scene_words
from backend.modules.scenes.worker_client import RenderWorkerClient

IDS = ["s01", "s02", "s03", "s04", "s05", "s06"]
REPO = Path(__file__).resolve().parents[4]


def run(coro):
    return asyncio.run(coro)


def req(message: str, selected: str | None = None) -> EditRoutingRequest:
    return EditRoutingRequest(project_id="p", message=message, scene_ids=IDS, selected_scene_id=selected)


# ---------------------------------------------------------------- router
@pytest.mark.parametrize("message,target", [
    ("Please correct scene six: make the packet diagram clearer", "s06"),
    ("scene 6 needs bigger labels", "s06"),
    ("In s06 make the arrows thicker", "s06"),
    ("SCENE FOUR: add a lock icon", "s04"),
    ("Scene #3 should show the firewall earlier", "s03"),
    ("the sixth scene is cluttered", "s06"),
    ("scene number 2 - highlight the relay", "s02"),
])
def test_router_explicit_targets(message, target):
    intent = route_deterministic(req(message))
    assert (intent.action, intent.scene_id) == ("edit_scene", target)
    assert intent.instruction == message


@pytest.mark.parametrize("message,selected", [
    ("make scenes 2 and 3 clearer", None),
    ("scene 2 and scene 5 need colour", None),
    ("make the audio louder in scene 3", None),
    ("change the dialogue in scene 1", None),
    ("make all scenes blue", None),
    ("make scene 4 shorter", None),
    ("fix the captions in scene 2", None),
    ("make the arrows thicker", None),          # no target and no selection
    ("scene 7 needs work", None),               # out of range -> no valid reference
    ("scene 5: bigger boxes", "s02"),           # explicit conflict with selection
    ("bigger boxes", "s09"),                    # unknown selection
])
def test_router_unsupported(message, selected):
    intent = route_deterministic(req(message, selected))
    assert intent.action == "unsupported" and intent.scene_id is None and intent.reason


def test_router_selected_scene_wins_without_mention():
    assert route_deterministic(req("make the packet diagram clearer", "s03")).scene_id == "s03"
    assert route_deterministic(req("scene 3: clearer", "s03")).scene_id == "s03"


class _RetargetRuntime:
    mock_mode = False

    def __init__(self, intent: EditIntent | Exception):
        self.intent = intent

    async def structured(self, *, messages, schema):
        if isinstance(self.intent, Exception):
            raise self.intent
        return self.intent


def test_router_llm_cannot_retarget_and_failure_keeps_deterministic(caplog):
    r = req("scene six: clearer packets")
    out = run(service.route_edit(r, _RetargetRuntime(EditIntent(action="edit_scene", scene_id="s02", instruction="x"))))
    assert out.scene_id == "s06" and out.instruction == r.message
    assert "keeping s06" in caplog.text
    out = run(service.route_edit(r, _RetargetRuntime(RuntimeError("boom"))))
    assert out.scene_id == "s06"
    out = run(service.route_edit(r, _RetargetRuntime(EditIntent(action="edit_scene", scene_id="s06", instruction="Make packet arrows thicker and label them"))))
    assert out.instruction == "Make packet arrows thicker and label them"
    out = run(service.route_edit(r, _RetargetRuntime(EditIntent(action="unsupported", instruction="x", reason="needs audio change"))))
    assert out.action == "unsupported" and out.reason == "needs audio change"


# ---------------------------------------------------------------- fixtures + timing
@pytest.fixture()
def ctx_rt(tmp_path):
    rt = FixtureRuntime(tmp_path, mock_mode=False, settings={"RENDER_WORKER_URL": "http://unused"})
    return run(build_fixture_context(rt)), rt


def test_fixture_context_recipe(ctx_rt):
    ctx, rt = ctx_rt
    assert [s.start_frame for s in ctx.timeline.scenes] + [1800] == [0, 273, 543, 813, 1083, 1353, 1800]
    assert ctx.timeline.utterances[-1].end_frame == 1611
    assert all(u.sample_count == u.frame_count * 1600 == 192000 for u in ctx.audio.utterances)
    for u in ctx.audio.utterances:  # hashes are of real files
        assert rt.path(u.wav.key).stat().st_size == u.wav.size_bytes
    assert sum(1 for s in ctx.images.selections if s.status == "selected") == 1


def test_normalize_cues_recomputes_from_words_and_rejects_bad(ctx_rt):
    ctx, _ = ctx_rt
    slot = ctx.timeline.scenes[5]
    w = [x for x in scene_words(ctx, slot) if x.dialogue_id == "d012"][0]
    cues = [
        AnimationCue(cue_id="a", word_ids=[w.word_id], start_frame=0, end_frame=5, description="x", claim_ids=["c006"]),
        AnimationCue(cue_id="b", start_frame=10, end_frame=20, description="untimed ok"),
        AnimationCue(cue_id="c", word_ids=["d001_w001"], start_frame=0, end_frame=5, description="other scene word"),
        AnimationCue(cue_id="d", start_frame=10, end_frame=9999, description="out of range"),
        AnimationCue(cue_id="e", start_frame=1, end_frame=2, description="bad claim", claim_ids=["c999"]),
        AnimationCue(cue_id="a", start_frame=1, end_frame=2, description="duplicate"),
    ]
    out, errors, warnings = normalize_cues(cues, ctx, slot)
    assert [c.cue_id for c in out][:2] == ["a", "b"]
    assert (out[0].start_frame, out[0].end_frame) == (w.start, w.end)
    assert any("recomputed" in x for x in warnings)
    joined = "\n".join(errors)
    for needle in ("cue c", "cue d", "c999", "duplicate"):
        assert needle in joined


# ---------------------------------------------------------------- repair loop / fallback (fake worker)
class FakeWorker:
    """Validates by policy-ish rule (no setTimeout) and scripts render outcomes."""

    def __init__(self, render_outcomes: list[str] | None = None):
        self.render_outcomes = list(render_outcomes or [])
        self.validated: list[str] = []
        self.jobs: list[str] = []

    async def validate(self, request: PreviewRequest) -> SourceValidationResult:
        self.validated.append(request.build.source.key)
        src = Path(self.root, request.build.source.key).read_text()
        bad = "setTimeout" in src
        return SourceValidationResult(valid=not bad, diagnostics=["Scene.tsx:1 'setTimeout' is not allowed"] if bad else [])

    async def run(self, request, on_progress=None) -> RenderResult:
        self.jobs.append(request.job_id)
        outcome = self.render_outcomes.pop(0) if self.render_outcomes else "ok"
        if on_progress:
            await on_progress(0.5)
        if outcome == "ok":
            dur = request.slot.end_frame - request.slot.start_frame
            ref = request.build.source.model_copy(update={"key": request.build.source.key.replace("Scene.tsx", "preview.mp4"), "media_type": "video/mp4"})
            return RenderResult(project_id=request.project_id, job_id=request.job_id, status="completed", progress=1, video=ref, duration_frames=dur)
        return RenderResult(project_id=request.project_id, job_id=request.job_id, status="failed", progress=0.3,
                            error=PipelineError(code=outcome, stage="scene_preview", message=f"{outcome}: TypeError in Scene", retryable=True, scene_id=request.slot.scene_id))


@pytest.fixture()
def fake_worker(monkeypatch, tmp_path):
    fw = FakeWorker()
    fw.root = str(tmp_path)
    monkeypatch.setattr(RenderWorkerClient, "from_runtime", classmethod(lambda cls, rt: fw))
    return fw


GOOD = (REPO / "backend/modules/scenes/fixtures/scenes/s02.tsx").read_text()
BAD = "import React from 'react';\nexport default function Scene() { setTimeout(() => {}, 1); return <div/>; }\n"


def scripted(*sources: str):
    calls = {"n": 0, "messages": []}

    def handler(messages, schema):
        calls["messages"].append(messages)
        src = sources[min(calls["n"], len(sources) - 1)]
        calls["n"] += 1
        return SceneDraft(source_code=src, summary="s", cues=[])
    return handler, calls


def make_task(ctx, idx=1, rev=1, job="op1", **kw):
    return SceneTask(project_id=ctx.project_id, job_id=job, context=ctx, slot=ctx.timeline.scenes[idx], revision=rev, **kw)


def test_exhausted_repairs_fall_back_with_visible_metadata(tmp_path, fake_worker):
    handler, calls = scripted(BAD)
    rt = FixtureRuntime(tmp_path, mock_mode=False, settings={"NEMOTRON_STRUCTURED_MODE": "json_prompt"}, structured_handler=handler)
    ctx = run(build_fixture_context(rt))
    build = run(service.generate_scene(make_task(ctx), rt))
    assert build.generation_mode == "fallback" and build.repair_attempts == 2
    assert build.warnings and build.warnings[0].startswith("FALLBACK:")
    assert calls["n"] == 3  # initial + two corrective attempts, no more
    assert "setTimeout" in calls["messages"][1][-1]["content"]  # feedback reached the repair prompt
    base = tmp_path / "projects" / ctx.project_id / "scenes" / "s02" / "v1" / "op1"
    assert {p.name for p in base.iterdir()} == {"a0", "a1", "a2", "afb"}
    assert (base / "a0" / "validation.json").exists() and (base / "afb" / "build.json").exists()


def test_repair_succeeds_on_second_attempt(tmp_path, fake_worker):
    handler, calls = scripted(BAD, GOOD)
    rt = FixtureRuntime(tmp_path, mock_mode=False, structured_handler=handler)
    ctx = run(build_fixture_context(rt))
    build = run(service.generate_scene(make_task(ctx), rt))
    assert (build.generation_mode, build.repair_attempts) == ("agent", 1)
    assert build.source.key.endswith("/op1/a1/Scene.tsx")


def test_transport_error_is_a_stage_failure_not_a_fallback(tmp_path, fake_worker):
    import httpx

    def handler(messages, schema):
        raise httpx.ConnectError("nemotron down")
    rt = FixtureRuntime(tmp_path, mock_mode=False, structured_handler=handler)
    ctx = run(build_fixture_context(rt))
    with pytest.raises(StageFailure) as e:
        run(service.generate_scene(make_task(ctx), rt))
    assert e.value.error.code == "SCENE_AGENT_UNAVAILABLE" and e.value.error.retryable


def test_preview_render_failure_repairs_with_attempt_job_ids(tmp_path, fake_worker):
    handler, _ = scripted(GOOD)
    rt = FixtureRuntime(tmp_path, mock_mode=False, structured_handler=handler)
    ctx = run(build_fixture_context(rt))
    task = make_task(ctx)
    build = run(service.generate_scene(task, rt))
    fake_worker.render_outcomes = ["RENDER_FAILED", "ok"]
    out = run(service.render_preview(PreviewRequest(project_id=ctx.project_id, job_id="op1", context=ctx, slot=task.slot, build=build), rt))
    assert fake_worker.jobs == ["op1-a0", "op1-a1"]
    assert out.build.repair_attempts == 1 and out.render.job_id == "op1-a1" and out.render.status == "completed"
    assert all(e["job_id"] == "op1" and e["stage"] == "scene_preview" for e in rt.progress_events)


def test_preview_infra_failure_is_raised_not_repaired(tmp_path, fake_worker):
    handler, calls = scripted(GOOD)
    rt = FixtureRuntime(tmp_path, mock_mode=False, structured_handler=handler)
    ctx = run(build_fixture_context(rt))
    task = make_task(ctx)
    build = run(service.generate_scene(task, rt))
    fake_worker.render_outcomes = ["RENDER_TIMEOUT"]
    with pytest.raises(StageFailure) as e:
        run(service.render_preview(PreviewRequest(project_id=ctx.project_id, job_id="op1", context=ctx, slot=task.slot, build=build), rt))
    assert e.value.error.code == "RENDER_TIMEOUT" and calls["n"] == 1


def test_mock_generation_and_mock_edit(tmp_path, fake_worker):
    rt = FixtureRuntime(tmp_path, mock_mode=True)
    ctx = run(build_fixture_context(rt))
    b1 = run(service.generate_scene(make_task(ctx, idx=5), rt))
    b2 = run(service.generate_scene(make_task(ctx, idx=5, rev=2, job="op2", previous_build=b1, edit_instruction="clearer packets"), rt))
    assert b1.generation_mode == b2.generation_mode == "mock"
    assert b1.source.sha256 != b2.source.sha256 and "/v2/op2/a0/" in b2.source.key
    assert b2.timeline_hash == b1.timeline_hash and "MOCK edit" in b2.summary


def test_task_for_another_context_is_rejected(tmp_path, fake_worker):
    rt = FixtureRuntime(tmp_path, mock_mode=True)
    ctx = run(build_fixture_context(rt))
    moved = ctx.timeline.scenes[1].model_copy(update={"end_frame": 999})
    with pytest.raises(StageFailure):
        run(service.generate_scene(SceneTask(project_id=ctx.project_id, job_id="x", context=ctx, slot=moved, revision=1), rt))


# ---------------------------------------------------------------- real validator on shipped sources
@pytest.mark.skipif(not (REPO / "renderer/node_modules").exists() or shutil.which("node") is None, reason="renderer deps not installed")
def test_authoring_guide_example_and_templates_pass_real_validator(tmp_path):
    guide = (REPO / "backend/modules/scenes/scene_authoring.md").read_text()
    example = guide.split("## Working example", 1)[1].split("```tsx", 1)[1].split("```", 1)[0]
    (tmp_path / "example.tsx").write_text(example)
    files = [tmp_path / "example.tsx", REPO / "backend/modules/scenes/templates/fallback_scene.tsx", *sorted((REPO / "backend/modules/scenes/fixtures/scenes").glob("*.tsx"))]
    for f in files:
        out = subprocess.run([str(REPO / "renderer/node_modules/.bin/tsx"), "src/source-check.ts", str(f)], cwd=REPO / "renderer", capture_output=True, text=True, timeout=120)
        assert '"valid":true' in out.stdout, (f.name, out.stdout, out.stderr[-500:])
