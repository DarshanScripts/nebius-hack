"""Coordinator checks use injected service doubles, not inference or video encoding."""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.core.fixtures import SERVICES
from backend.core.pipeline import Coordinator, RequestError
from backend.core.runtime import AppRuntime
from contracts.models import (
    EditIntent, EditRequest, PipelineError, ProjectCreate, RenderResult, SceneBuild,
    ScenePreviewOutcome, StageFailure,
)
from contracts.validation import (
    artifact_path, canonical_hash, validate_audio, validate_context, validate_timeline,
)


def settings(root, **kwargs):
    return Settings(_env_file=None, mock_mode=True, artifact_root=root, scene_agent_concurrency=6, **kwargs)


class SceneDoubles:
    def __init__(self):
        self.fail = set()
        self.fail_edits = False
        self.calls = []

    async def generate(self, request, runtime):
        self.calls.append((request.slot.scene_id, request.revision))
        await asyncio.sleep({3: .005, 1: .025, 6: .045, 2: .065, 5: .085, 4: .105}[request.slot.index])
        if request.slot.scene_id in self.fail or self.fail_edits and request.revision > 1:
            raise StageFailure(PipelineError(code="SCENE_TEST_FAILURE", stage="scenes", message="Explicit test failure", retryable=True))
        source = await runtime.write_bytes(
            f"projects/{request.project_id}/scenes/{request.slot.scene_id}/v{request.revision}/{request.job_id}/a0/Scene.tsx",
            b"export default function Scene() { return null; }", "text/plain")
        return SceneBuild(project_id=request.project_id, scene_id=request.slot.scene_id, revision=request.revision,
            context_hash=request.context.context_hash, timeline_hash=request.context.timeline_hash,
            source=source, summary="Fixture code", generation_mode="mock")

    async def preview(self, request, runtime):
        # A typed non-media fixture records the job without pretending to encode a video.
        artifact = await runtime.write_json(
            f"projects/{request.project_id}/scenes/{request.slot.scene_id}/v{request.build.revision}/{request.job_id}/a0/test-result.json",
            {"test_double": True})
        repaired = request.build.model_copy(update={"summary": "Preview-repaired build"})
        return ScenePreviewOutcome(project_id=request.project_id, build=repaired,
            render=RenderResult(project_id=request.project_id, job_id=f"{request.job_id}-a0", status="completed",
                                progress=1, video=artifact, duration_frames=request.slot.end_frame-request.slot.start_frame))

    async def route(self, request, runtime):
        return EditIntent(action="edit_scene", scene_id=request.selected_scene_id or "s06", instruction=request.message)

    async def final(self, request, runtime):
        await runtime.report_progress(project_id=request.project_id, job_id=request.job_id, stage="final", progress=.5)
        artifact = await runtime.write_json(f"projects/{request.project_id}/final/{request.job_id}/test-result.json",
                                            {"test_double": True})
        return RenderResult(project_id=request.project_id, job_id=request.job_id, status="completed",
                            progress=1, video=artifact, duration_frames=1800)

    def services(self):
        return {**SERVICES, "generate_scene": self.generate, "render_preview": self.preview,
                "route_edit": self.route, "render_final": self.final}


async def drain(coordinator):
    while coordinator._tasks:
        await asyncio.gather(*list(coordinator._tasks))


async def ready(root, doubles=None):
    doubles = doubles or SceneDoubles()
    coordinator = Coordinator(settings(root), doubles.services())
    created = coordinator.create(ProjectCreate(topic="Mock demonstration of calling infrastructure"))
    assert created.status == "created" and len(created.scenes) == 6
    await drain(coordinator)
    return coordinator, created.project_id, doubles


def test_frozen_models_match_plan():
    root = Path(__file__).resolve().parents[3]
    text = (root / "plan.md").read_text()
    block = text.split("\n<!-- CONTRACTS_START -->\n", 1)[1].split("\n<!-- CONTRACTS_END -->", 1)[0]
    expected = block.split("```python", 1)[1].split("```", 1)[0].strip() + "\n"
    assert (root / "contracts/models.py").read_text() == expected


def test_timeline_and_progressive_completion(tmp_path):
    async def check():
        coordinator, project_id, _ = await ready(tmp_path)
        snapshot = coordinator.repo.get(project_id)
        assert snapshot.status == "ready"
        assert [s.scene_id for s in snapshot.scenes] == [f"s{i:02}" for i in range(1, 7)]
        assert [0] + [s.end_frame for s in snapshot.timeline.scenes] == [0, 273, 543, 813, 1083, 1353, 1800]
        assert snapshot.timeline.utterances[-1].end_frame == 1611
        events = coordinator.repo.events(project_id).events
        order = [e.scene_id for e in events if e.type == "scene.ready"]
        assert order[0] == "s03" and order != sorted(order)
        assert [e.event_id for e in events] == list(range(1, len(events)+1))
        assert all(s.build.summary == "Preview-repaired build" for s in snapshot.scenes)
        context = coordinator.context(project_id)
        validate_context(context, root=tmp_path)
        invalid = snapshot.timeline.model_copy(deep=True)
        invalid.scenes[0].end_frame += 1
        with pytest.raises(ValueError):
            validate_timeline(invalid, snapshot.script, snapshot.audio)
        with pytest.raises(ValueError, match="Mock timings"):
            validate_audio(snapshot.audio, snapshot.script, live=True)
        invalid_audio = snapshot.audio.model_copy(deep=True)
        invalid_audio.utterances[0].words[0].text = "missing"
        with pytest.raises(ValueError, match="ALIGNMENT_INCOMPLETE"):
            validate_audio(invalid_audio, snapshot.script)
        invalid_audio = snapshot.audio.model_copy(deep=True)
        invalid_audio.utterances[0].sample_count -= 1
        with pytest.raises(ValueError, match="frame padded"):
            validate_audio(invalid_audio, snapshot.script)
        await coordinator.close()
    asyncio.run(check())


def test_targeted_edit_stale_progress_and_final(tmp_path):
    async def check():
        coordinator, project_id, _ = await ready(tmp_path)
        before = coordinator.repo.get(project_id)
        context_hash = coordinator.context(project_id).context_hash
        await coordinator.stitch(project_id)
        await drain(coordinator)
        assert coordinator.repo.get(project_id).status == "completed"
        editing = await coordinator.edit(project_id, EditRequest(message="Clarify scene six", scene_id="s06", expected_scene_revision=1))
        assert editing.scenes[-1].current_revision == 1 and editing.scenes[-1].preview == before.scenes[-1].preview
        assert editing.project_revision == 2 and editing.final_is_stale
        with pytest.raises(RequestError) as err:
            await coordinator.stitch(project_id)
        assert err.value.status == 409
        await drain(coordinator)
        after = coordinator.repo.get(project_id)
        assert after.scenes[-1].current_revision == 2
        assert after.scenes[:5] == before.scenes[:5]
        assert coordinator.context(project_id).context_hash == context_hash
        cursor = coordinator.repo.events(project_id).next_after
        await coordinator.report_progress(project_id=project_id, job_id="obsolete", stage="scene_preview", progress=.9, scene_id="s06")
        assert coordinator.repo.events(project_id).next_after == cursor
        with pytest.raises(RequestError) as err:
            await coordinator.edit(project_id, EditRequest(message="Again", scene_id="s06", expected_scene_revision=1))
        assert err.value.error.code == "STALE_REVISION"
        await coordinator.stitch(project_id)
        await drain(coordinator)
        done = coordinator.repo.get(project_id)
        assert done.final_project_revision == 2 and not done.final_is_stale
        await coordinator.close()
    asyncio.run(check())


@pytest.mark.parametrize("mode,attempts,suffix,accepted", [
    ("agent", 1, "a1", True),
    ("agent", 2, "a2", True),
    ("fallback", 2, "a2", True),
    ("agent", 1, "a0", False),
    ("fallback", 2, "afb", False),
])
def test_preview_job_matches_final_build(tmp_path, mode, attempts, suffix, accepted):
    class RepairedScenes(SceneDoubles):
        async def preview(self, request, runtime):
            outcome = await super().preview(request, runtime)
            outcome.build.generation_mode = mode
            outcome.build.repair_attempts = attempts
            outcome.render.job_id = f"{request.job_id}-{suffix}"
            return outcome

    async def check():
        coordinator, project_id, _ = await ready(tmp_path, RepairedScenes())
        try:
            snapshot = coordinator.repo.get(project_id)
            assert (snapshot.status == "ready") == accepted
            if not accepted:
                assert all(s.error.code == "CONTRACT_VALIDATION_FAILED" for s in snapshot.scenes)
        finally:
            await coordinator.close()
    asyncio.run(check())


def test_scene_retry_reuses_validated_build_from_interrupted_preview(tmp_path):
    class PreviewFailOnce(SceneDoubles):
        def __init__(self):
            super().__init__()
            self.preview_attempts = 0

        async def generate(self, request, runtime):
            build = await super().generate(request, runtime)
            await runtime.write_json(
                f"projects/{request.project_id}/scenes/{request.slot.scene_id}/v{request.revision}/{request.job_id}/a0/build.json",
                build,
            )
            return build

        async def preview(self, request, runtime):
            if request.slot.scene_id == "s01":
                self.preview_attempts += 1
                if self.preview_attempts == 1:
                    raise StageFailure(PipelineError(
                        code="RENDER_WORKER_UNAVAILABLE", stage="scene_preview",
                        message="Worker stalled on first preview", retryable=True, scene_id="s01"))
            return await super().preview(request, runtime)

    async def check():
        doubles = PreviewFailOnce()
        coordinator, project_id, _ = await ready(tmp_path, doubles)
        try:
            snapshot = coordinator.repo.get(project_id)
            assert snapshot.status == "failed"
            s01_calls_before = [c for c in doubles.calls if c[0] == "s01"]
            assert len(s01_calls_before) == 1
            await coordinator.retry(project_id, "scenes", "s01")
            await drain(coordinator)
            after = coordinator.repo.get(project_id)
            assert after.status == "ready"
            s01_calls_after = [c for c in doubles.calls if c[0] == "s01"]
            assert len(s01_calls_after) == 1
        finally:
            await coordinator.close()
    asyncio.run(check())


def test_failed_scene_and_failed_edit_preserve_outputs(tmp_path):
    async def check():
        doubles = SceneDoubles()
        doubles.fail.add("s03")
        coordinator, project_id, _ = await ready(tmp_path, doubles)
        snapshot = coordinator.repo.get(project_id)
        assert snapshot.status == "failed" and len([s for s in snapshot.scenes if s.status == "ready"]) == 5
        doubles.fail.clear()
        await coordinator.retry(project_id, "scenes", "s03")
        await drain(coordinator)
        before = coordinator.repo.get(project_id)
        assert before.status == "ready"
        doubles.fail_edits = True
        await coordinator.edit(project_id, EditRequest(message="Change scene six", scene_id="s06"))
        await drain(coordinator)
        after = coordinator.repo.get(project_id)
        assert after.scenes[-1].status == "ready" and after.scenes[-1].error
        assert after.scenes[-1].current_revision == 1
        assert after.scenes[-1].build == before.scenes[-1].build
        assert after.scenes[-1].preview == before.scenes[-1].preview
        await coordinator.close()
    asyncio.run(check())


def test_restart_recovers_interrupted_edit(tmp_path):
    async def check():
        coordinator, project_id, _ = await ready(tmp_path)
        async with coordinator.repo.lock(project_id):
            snapshot = coordinator.repo.get(project_id)
            snapshot.scenes[0].active_job_id = "interrupted"
            snapshot.scenes[0].status = "rendering"
            coordinator.repo.save(snapshot, "edit.accepted", "Interrupted edit")
        replacement = Coordinator(settings(tmp_path))
        replacement.recover()
        restored = replacement.repo.get(project_id)
        assert restored.scenes[0].status == "ready"
        assert restored.scenes[0].error.code == "JOB_INTERRUPTED"
        assert restored.scenes[0].active_job_id is None
        await coordinator.close()
        await replacement.close()
    asyncio.run(check())


def test_artifact_integrity_and_immutability(tmp_path):
    async def check():
        runtime = AppRuntime(settings(tmp_path))
        first = await runtime.write_bytes("projects/example/file.txt", b"fixture", "text/plain")
        assert await runtime.write_bytes(first.key, b"fixture", "text/plain") == first
        with pytest.raises(ValueError, match="immutable"):
            await runtime.write_bytes(first.key, b"changed", "text/plain")
        for key in ("../.env", "/etc/passwd", "projects/../private", "projects//file", "C:\\secret"):
            with pytest.raises(ValueError):
                artifact_path(tmp_path, key)
        (tmp_path / "outside-link").symlink_to(tmp_path.parent, target_is_directory=True)
        with pytest.raises(ValueError):
            artifact_path(tmp_path, "outside-link/secret")
    asyncio.run(check())


def test_http_contract_and_ranges(tmp_path):
    app = create_app(settings(tmp_path))
    artifact = tmp_path / "projects/example/file.wav"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"0123456789")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["mode"] == "mock"
        invalid = client.post("/api/projects", json={"topic": "x", "secret": "never echo"})
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "never echo" not in invalid.text
        response = client.post("/api/projects", json={"topic": "Mock topic with enough detail"})
        assert response.status_code == 202 and len(response.json()["scenes"]) == 6
        project_id = response.json()["project_id"]
        assert client.get(f"/api/projects/{project_id}").status_code == 200
        assert client.get("/api/projects/unknown").status_code == 404
        assert client.post(f"/api/projects/{project_id}/retry", json={"stage": "unknown"}).status_code == 422
        assert client.post(f"/api/projects/{project_id}/stitch", json={}).status_code == 409
        sliced = client.get("/api/artifacts/projects/example/file.wav", headers={"Range": "bytes=2-5"})
        assert sliced.status_code == 206 and sliced.content == b"2345"
        assert sliced.headers["content-range"] == "bytes 2-5/10"
        assert client.get("/api/artifacts/%2e%2e/.env").status_code == 404


def test_missing_module_reports_stage_failure(tmp_path):
    async def check():
        coordinator = Coordinator(settings(tmp_path))
        # Explicit missing injection is independent of whether teammate modules have merged.
        def missing(*args):
            raise ImportError("missing")
        import unittest.mock
        with unittest.mock.patch("backend.core.pipeline.importlib.import_module", side_effect=missing):
            created = coordinator.create(ProjectCreate(topic="Mock topic testing unavailable module"))
            await drain(coordinator)
        snapshot = coordinator.repo.get(created.project_id)
        assert snapshot.error.code == "MODULE_UNAVAILABLE" and snapshot.active_job_id is None
        assert snapshot.status == "failed"
        await coordinator.close()
    asyncio.run(check())


def test_stage_retry_reuses_completed_research(tmp_path):
    async def check():
        calls = {"research": 0, "dialogue": 0}
        async def research(request, runtime):
            calls["research"] += 1
            return await SERVICES["run_research"](request, runtime)
        async def dialogue(request, runtime):
            calls["dialogue"] += 1
            if calls["dialogue"] == 1:
                raise StageFailure(PipelineError(code="TEMPORARY", stage="dialogue", message="Explicit fixture failure", retryable=True))
            return await SERVICES["generate_dialogue"](request, runtime)
        doubles = SceneDoubles()
        coordinator = Coordinator(settings(tmp_path), {**doubles.services(), "run_research": research, "generate_dialogue": dialogue})
        created = coordinator.create(ProjectCreate(topic="Mock test of retry and paid task reuse"))
        await drain(coordinator)
        failed = coordinator.repo.get(created.project_id)
        assert failed.status == "failed" and failed.research and failed.script is None
        with pytest.raises(RequestError) as err:
            await coordinator.retry(created.project_id, "research")
        assert err.value.error.code == "RETRY_STAGE_MISMATCH"
        await coordinator.retry(created.project_id, "dialogue")
        await drain(coordinator)
        assert calls == {"research": 1, "dialogue": 2}
        assert coordinator.repo.get(created.project_id).status == "ready"
        await coordinator.close()
    asyncio.run(check())


def test_parallel_edits_remain_independent(tmp_path):
    async def check():
        coordinator, project_id, _ = await ready(tmp_path)
        await coordinator.edit(project_id, EditRequest(message="Change first diagram", scene_id="s01"))
        await coordinator.edit(project_id, EditRequest(message="Change second diagram", scene_id="s02"))
        with pytest.raises(RequestError) as err:
            await coordinator.edit(project_id, EditRequest(message="Change first again", scene_id="s01"))
        assert err.value.error.code == "SCENE_BUSY"
        await drain(coordinator)
        snapshot = coordinator.repo.get(project_id)
        assert snapshot.status == "ready" and snapshot.project_revision == 3
        assert [s.current_revision for s in snapshot.scenes] == [2, 2, 1, 1, 1, 1]
        await coordinator.close()
    asyncio.run(check())
