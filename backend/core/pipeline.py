"""Deterministic coordinator. Modules own inference; only core mutates projects."""
import asyncio
import importlib
import mimetypes
from uuid import uuid4

from contracts.models import (
    CharacterSpec, DialogueRequest, EditRequest, EditRoutingRequest, FinalRenderRequest,
    ImageRequest, PipelineError, PreviewRequest, ProjectCreate, ProjectSnapshot,
    RenderResult, ResearchRequest, SceneContext, SceneState, SceneTask,
    StageFailure, VoiceRequest,
)
from contracts.validation import (
    canonical_hash, require, validate_artifacts, validate_audio, validate_build,
    validate_context, validate_images, validate_render, validate_research, validate_script,
)
from backend.core.config import Settings
from backend.core.repository import Repository, utc_now
from backend.core.runtime import AppRuntime
from backend.core.timeline import build_timeline


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.error = PipelineError(code=code, stage="api", message=message)
        super().__init__(message)


STAGES = {
    "run_research": "content", "generate_dialogue": "content", "find_images": "content",
    "synthesize_dialogue": "voice", "generate_scene": "scenes", "render_preview": "scenes",
    "route_edit": "scenes", "render_final": "scenes",
}


class Coordinator:
    def __init__(self, settings: Settings, services: dict | None = None):
        self.settings = settings
        self.repo = Repository(settings.artifact_root)
        self.runtime = AppRuntime(settings, self.report_progress)
        self._services = services or {}
        self._tasks: set[asyncio.Task] = set()
        self._scene_semaphore = asyncio.Semaphore(settings.scene_agent_concurrency)
        self._speech_semaphore = asyncio.Semaphore(settings.speech_gpu_pipeline_concurrency)

    def launch(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        # All expected stage failures have already been persisted. Retrieve any
        # unexpected exception so background tasks never fail silently.
        if not task.cancelled() and task.exception():
            import logging
            logging.getLogger(__name__).error("Background operation failed (%s)", type(task.exception()).__name__)

    async def close(self):
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def call(self, name, request):
        function = self._services.get(name)
        if function is None:
            module_name = f"backend.modules.{STAGES[name]}.service"
            try:
                module = importlib.import_module(module_name)
                function = getattr(module, name)
            except (ImportError, AttributeError) as exc:
                raise StageFailure(PipelineError(code="MODULE_UNAVAILABLE", stage=STAGES[name],
                    message=f"{module_name}.{name} is not installed yet", retryable=True)) from exc
        return await function(request, self.runtime)

    def recover(self):
        self.repo.recover()
        for summary in self.repo.list():
            snapshot = self.repo.get(summary.project_id)
            interrupted = bool(snapshot.active_job_id)
            for scene in snapshot.scenes:
                if scene.active_job_id or scene.status in ("generating", "rendering"):
                    interrupted = True
                    scene.active_job_id = None
                    scene.status = "ready" if scene.preview else "failed"
                    scene.requested_revision = scene.current_revision or 1
                    scene.error = PipelineError(code="JOB_INTERRUPTED", stage="scenes", scene_id=scene.scene_id,
                                                message="Scene job interrupted; retry to resume", retryable=True)
            if interrupted:
                if snapshot.final and snapshot.final.status in ("queued", "running"):
                    snapshot.final.status = "failed"
                    snapshot.final.error = PipelineError(code="JOB_INTERRUPTED", stage="final",
                                                        message="Final render interrupted", retryable=True)
                snapshot.active_job_id = None
                snapshot.status = "ready" if all(s.status == "ready" for s in snapshot.scenes) else "failed"
                snapshot.error = PipelineError(code="JOB_INTERRUPTED", stage="pipeline",
                                               message="API restarted; completed outputs preserved", retryable=True)
                self.repo.save(snapshot, "stage.failed", snapshot.error.message)

    def create(self, request: ProjectCreate) -> ProjectSnapshot:
        project_id, job_id = str(uuid4()), str(uuid4())
        snapshot = ProjectSnapshot(project_id=project_id, topic=request.topic,
            mode="mock" if self.settings.mock_mode else "live", status="created",
            created_at=utc_now(), updated_at=utc_now(), active_job_id=job_id,
            scenes=[SceneState(scene_id=f"s{i:02}", index=i) for i in range(1, 7)])
        snapshot = self.repo.save(snapshot, "project.created", "Project created; six scene slots reserved")
        self.launch(self.run(project_id, job_id))
        return snapshot

    async def characters(self, project_id: str) -> list[CharacterSpec]:
        key = f"projects/{project_id}/inputs/characters.json"
        if self.runtime.path(key).exists():
            import json
            return [CharacterSpec.model_validate(c) for c in json.loads(self.runtime.path(key).read_bytes())]
        characters = []
        for character_id, name in (("sundar", "Sundar Pichai"), ("jensen", "Jensen Huang")):
            char = CharacterSpec(character_id=character_id, display_name=name)
            for relative, field in ((f"characters/{character_id}.png", "image"),
                                    (f"voices/{character_id}/reference.wav", "voice_reference")):
                path = self.settings.assets_root / relative
                if path.is_file():
                    ref = await self.runtime.write_bytes(f"projects/{project_id}/inputs/{relative}",
                        path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    setattr(char, field, ref)
            transcript = self.settings.assets_root / f"voices/{character_id}/reference.txt"
            if transcript.is_file():
                char.reference_transcript = transcript.read_text()
            characters.append(char)
        await self.runtime.write_json(key, [c.model_dump(mode="json") for c in characters])
        return characters

    async def _publish(self, project_id, event, message, **changes):
        def mutate(snapshot):
            for key, value in changes.items():
                setattr(snapshot, key, value)
        return await self.repo.update(project_id, mutate, event, message)

    def error(self, exc: Exception, stage: str, scene_id=None) -> PipelineError:
        if isinstance(exc, StageFailure):
            return exc.error.model_copy(update={"stage": stage, "scene_id": scene_id})
        if isinstance(exc, ValueError):
            # Only our validators' messages, not arbitrary provider exception text.
            return PipelineError(code="CONTRACT_VALIDATION_FAILED", stage=stage,
                                 message="Stage output violated the shared contract", retryable=True, scene_id=scene_id)
        return PipelineError(code="STAGE_FAILED", stage=stage,
                             message=f"{stage} failed ({type(exc).__name__}); completed outputs preserved",
                             retryable=True, scene_id=scene_id)

    async def run(self, project_id, job_id):
        stage = "research"
        try:
            characters = await self.characters(project_id)
            snapshot = self.repo.get(project_id)
            if snapshot.research is None:
                await self._publish(project_id, "research.started", "Research started", status="researching")
                research = await self.call("run_research", ResearchRequest(project_id=project_id, topic=snapshot.topic))
                require(research.project_id == project_id and research.topic == snapshot.topic, "Research identity mismatch")
                validate_research(research)
                require(self.settings.mock_mode or not research.is_mock, "Live research cannot be mock")
                validate_artifacts(research, self.runtime.artifact_root, project_id)
                await self.runtime.write_json(f"projects/{project_id}/research/bundle.json", research)
                snapshot = await self._publish(project_id, "research.ready", "Grounded research ready", research=research)
            stage = "dialogue"
            if snapshot.script is None:
                await self._publish(project_id, "research.ready", "Generating grounded dialogue", status="scripting")
                script = await self.call("generate_dialogue", DialogueRequest(project_id=project_id,
                    research=snapshot.research, characters=characters))
                validate_script(script, snapshot.research)
                await self.runtime.write_json(f"projects/{project_id}/script/v{script.script_revision}/script.json", script)
                snapshot = await self._publish(project_id, "dialogue.ready", "Twelve dialogue turns ready", script=script)
            stage = "images"
            if snapshot.images is None:
                await self._publish(project_id, "dialogue.ready", "Searching relevant scene images", status="finding_images")
                images = await self.call("find_images", ImageRequest(project_id=project_id,
                    research=snapshot.research, script=snapshot.script))
                validate_images(images, snapshot.script)
                validate_artifacts(images, self.runtime.artifact_root, project_id)
                snapshot = await self._publish(project_id, "images.ready", "Image selections ready", images=images)
            stage = "voice"
            if snapshot.audio is None:
                await self._publish(project_id, "voice.started", "Generating speech and word timestamps", status="voicing")
                async with self._speech_semaphore:
                    try:
                        audio = await self.call("synthesize_dialogue", VoiceRequest(project_id=project_id,
                            script=snapshot.script, characters=characters))
                    except StageFailure as exc:
                        if exc.error.code != "AUDIO_DURATION_OUT_OF_RANGE" or snapshot.script.script_revision != 1:
                            raise
                        # One measured-duration-driven shortening pass before any timeline is frozen.
                        shorter = await self.call("generate_dialogue", DialogueRequest(project_id=project_id,
                            research=snapshot.research, characters=characters, script_revision=2,
                            previous_script=snapshot.script,
                            revision_instruction=f"Shorten to fit 1599 speech frames (53.3 seconds). {exc.error.message}"))
                        require(shorter.script_revision == 2, "Shortened script must be revision 2")
                        validate_script(shorter, snapshot.research)
                        await self.runtime.write_json(f"projects/{project_id}/script/v2/script.json", shorter)
                        snapshot = await self._publish(project_id, "dialogue.ready", "Script shortened for speech budget",
                                                       script=shorter, images=None)
                        images = await self.call("find_images", ImageRequest(project_id=project_id,
                            research=snapshot.research, script=shorter))
                        validate_images(images, shorter)
                        validate_artifacts(images, self.runtime.artifact_root, project_id)
                        snapshot = await self._publish(project_id, "images.ready", "Images updated for shortened script", images=images)
                        audio = await self.call("synthesize_dialogue", VoiceRequest(project_id=project_id,
                            script=shorter, characters=characters))
                validate_audio(audio, snapshot.script, live=not self.settings.mock_mode, root=self.runtime.artifact_root)
                validate_artifacts(audio, self.runtime.artifact_root, project_id)
                snapshot = await self._publish(project_id, "voice.ready", "Speech and word timestamps ready", audio=audio)
            stage = "scenes"
            if snapshot.timeline is None:
                await self._publish(project_id, "voice.ready", "Locking measured timeline", status="planning")
                timeline = build_timeline(snapshot.script, snapshot.audio)
                await self.runtime.write_json(f"projects/{project_id}/timeline.json", timeline)
                payload = dict(project_id=project_id, research=snapshot.research, script=snapshot.script,
                    images=snapshot.images, audio=snapshot.audio, timeline=timeline, characters=characters,
                    timeline_hash=canonical_hash(timeline), context_hash="")
                context = SceneContext(**payload)
                context.context_hash = canonical_hash(context.model_dump(mode="json", exclude={"context_hash"}))
                validate_context(context, live=not self.settings.mock_mode, root=self.runtime.artifact_root)
                await self.runtime.write_json(f"projects/{project_id}/context.json", context)
                def lock_timeline(s):
                    s.timeline = timeline
                    s.status = "generating_scenes"
                    for state, slot in zip(s.scenes, timeline.scenes):
                        state.slot = slot
                snapshot = await self.repo.update(project_id, lock_timeline, "timeline.ready", "Timeline locked at 1800 frames")
            context = self.context(project_id)
            tasks = []
            for state in snapshot.scenes:
                if state.status == "ready":
                    continue
                operation_id = str(uuid4())
                await self._reserve_scene(project_id, state.scene_id, operation_id, state.current_revision + 1)
                tasks.append(asyncio.create_task(self.scene_job(project_id, state.scene_id, operation_id, context)))
            try:
                for completed in asyncio.as_completed(tasks):
                    await completed
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            async with self.repo.lock(project_id):
                snapshot = self.repo.get(project_id)
                if snapshot.active_job_id == job_id:
                    snapshot.active_job_id = None
                    snapshot.status = self.scene_status(snapshot)
                    self.repo.save(snapshot, "timeline.ready", "Scene generation finished")
        except asyncio.CancelledError:
            raise  # Startup recovery marks interrupted operations on next launch.
        except Exception as exc:
            error = self.error(exc, stage)
            await self._publish(project_id, "stage.failed", error.message, status="failed", error=error, active_job_id=None)

    def context(self, project_id) -> SceneContext:
        context = SceneContext.model_validate_json(self.runtime.path(f"projects/{project_id}/context.json").read_bytes())
        validate_context(context, live=not self.settings.mock_mode, root=self.runtime.artifact_root)
        return context

    @staticmethod
    def scene_status(snapshot):
        if any(s.active_job_id for s in snapshot.scenes):
            return "generating_scenes"
        return "ready" if all(s.status == "ready" for s in snapshot.scenes) else "failed"

    async def _reserve_scene(self, project_id, scene_id, job_id, revision, instruction=None):
        def mutate(snapshot):
            scene = next(s for s in snapshot.scenes if s.scene_id == scene_id)
            scene.status, scene.active_job_id, scene.requested_revision = "generating", job_id, revision
            scene.progress, scene.error = 0, None
        await self.repo.update(project_id, mutate, "scene.started", instruction or "Generating scene",
                               scene_id=scene_id, revision=revision)

    async def scene_job(self, project_id, scene_id, job_id, context, instruction=None):
        try:
            async with self._scene_semaphore:
                snapshot = self.repo.get(project_id)
                scene = next(s for s in snapshot.scenes if s.scene_id == scene_id)
                revision, slot = scene.requested_revision, scene.slot
                task = SceneTask(project_id=project_id, job_id=job_id, context=context, slot=slot,
                                 revision=revision, previous_build=scene.build, edit_instruction=instruction)
                build = await self.call("generate_scene", task)
                validate_build(build, context, slot, revision)
                validate_artifacts(build, self.runtime.artifact_root, project_id)
                async with self.repo.lock(project_id):
                    snapshot = self.repo.get(project_id)
                    state = next(s for s in snapshot.scenes if s.scene_id == scene_id)
                    if state.active_job_id != job_id:
                        return
                    state.status = "rendering"
                    self.repo.save(snapshot, "scene.code_ready", "Scene code ready; rendering preview",
                                   scene_id=scene_id, revision=revision)
                outcome = await self.call("render_preview", PreviewRequest(project_id=project_id,
                    job_id=job_id, context=context, slot=slot, build=build))
                require(outcome.project_id == project_id, "Preview outcome project mismatch")
                validate_build(outcome.build, context, slot, revision)
                validate_render(outcome.render, project_id, slot.end_frame - slot.start_frame)
                require(outcome.render.job_id.startswith(f"{job_id}-a")
                        and outcome.render.job_id[len(job_id)+2:] in ("0", "1", "2"), "Preview job identity mismatch")
                validate_artifacts(outcome, self.runtime.artifact_root, project_id)
                async with self.repo.lock(project_id):
                    snapshot = self.repo.get(project_id)
                    state = next(s for s in snapshot.scenes if s.scene_id == scene_id)
                    if state.active_job_id != job_id:
                        return
                    state.build, state.preview = outcome.build, outcome.render
                    state.current_revision, state.requested_revision = revision, revision
                    state.status, state.progress, state.active_job_id, state.error = "ready", 1, None, None
                    snapshot.status = self.scene_status(snapshot)
                    if snapshot.status == "ready":
                        snapshot.error = None
                    self.repo.save(snapshot, "scene.ready", "Scene preview ready", scene_id=scene_id, revision=revision)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = self.error(exc, "scenes", scene_id)
            async with self.repo.lock(project_id):
                snapshot = self.repo.get(project_id)
                state = next(s for s in snapshot.scenes if s.scene_id == scene_id)
                if state.active_job_id != job_id:
                    return
                state.status = "ready" if state.preview else "failed"
                state.active_job_id, state.error = None, error
                state.requested_revision = state.current_revision or 1
                state.progress = 1 if state.preview else 0
                snapshot.status = self.scene_status(snapshot)
                if snapshot.status == "failed":
                    snapshot.error = error
                self.repo.save(snapshot, "scene.failed", error.message, scene_id=scene_id,
                               revision=state.current_revision)

    async def edit(self, project_id: str, request: EditRequest) -> ProjectSnapshot:
        initial = self.repo.get(project_id)
        if initial.timeline is None:
            raise RequestError(409, "TIMELINE_UNREADY", "Wait for the audio timeline before editing")
        if initial.active_job_id or initial.status == "rendering":
            raise RequestError(409, "PROJECT_BUSY", "Wait for the current pipeline/render operation")
        intent = await self.call("route_edit", EditRoutingRequest(project_id=project_id, message=request.message,
            scene_ids=[s.scene_id for s in initial.scenes], selected_scene_id=request.scene_id))
        if intent.action != "edit_scene" or intent.scene_id not in {s.scene_id for s in initial.scenes}:
            raise RequestError(422, "UNSUPPORTED_EDIT", intent.reason or "Select one scene and describe a visual correction")
        if request.scene_id and request.scene_id != intent.scene_id:
            raise RequestError(422, "CONFLICTING_SCENE", "Selected scene conflicts with the edit message")
        context = self.context(project_id)
        async with self.repo.lock(project_id):
            snapshot = self.repo.get(project_id)
            state = next(s for s in snapshot.scenes if s.scene_id == intent.scene_id)
            if snapshot.active_job_id or state.active_job_id:
                raise RequestError(409, "SCENE_BUSY", "Scene or project render is busy")
            if state.current_revision < 1:
                raise RequestError(409, "SCENE_UNREADY", "Retry the failed scene before editing")
            if request.expected_scene_revision is not None and request.expected_scene_revision != state.current_revision:
                raise RequestError(409, "STALE_REVISION", "Refresh the scene before editing")
            job_id = str(uuid4())
            state.active_job_id, state.requested_revision = job_id, state.current_revision + 1
            state.status, state.progress, state.error = "generating", 0, None
            snapshot.project_revision += 1
            snapshot.final_is_stale = snapshot.final is not None
            snapshot.status, snapshot.error = "generating_scenes", None
            snapshot = self.repo.save(snapshot, "edit.accepted", intent.instruction,
                                      scene_id=state.scene_id, revision=state.requested_revision)
        self.launch(self.scene_job(project_id, intent.scene_id, job_id, context, intent.instruction))
        return snapshot

    async def stitch(self, project_id) -> ProjectSnapshot:
        context = self.context(project_id) if self.repo.get(project_id).timeline else None
        async with self.repo.lock(project_id):
            snapshot = self.repo.get(project_id)
            if snapshot.active_job_id or context is None or any(s.status != "ready" or s.active_job_id for s in snapshot.scenes):
                raise RequestError(409, "SCENES_UNREADY", "All six scenes must be ready and idle before Stitch")
            if not self.settings.mock_mode and any(c.image is None for c in context.characters):
                raise RequestError(409, "CHARACTERS_MISSING", "Live final render requires both character PNGs")
            for state in snapshot.scenes:
                require(state.build is not None and state.preview is not None, "Ready scene lacks preview")
                validate_build(state.build, context, state.slot, state.current_revision)
                validate_render(state.preview, project_id, state.slot.end_frame - state.slot.start_frame)
                validate_artifacts(state.build, self.runtime.artifact_root, project_id)
            job_id = str(uuid4())
            request = FinalRenderRequest(project_id=project_id, job_id=job_id,
                project_revision=snapshot.project_revision, context=context, builds=[s.build for s in snapshot.scenes])
            await self.runtime.write_json(f"projects/{project_id}/final/{job_id}/manifest.json", request)
            snapshot.active_job_id, snapshot.status = job_id, "rendering"
            snapshot.final = RenderResult(project_id=project_id, job_id=job_id, status="queued", progress=0)
            snapshot.final_project_revision, snapshot.final_is_stale, snapshot.error = snapshot.project_revision, False, None
            snapshot = self.repo.save(snapshot, "render.started", "Rendering final reel")
        self.launch(self.final_job(request))
        return snapshot

    async def final_job(self, request):
        try:
            result = await self.call("render_final", request)
            validate_render(result, request.project_id, 1800)
            require(result.job_id == request.job_id, "Final job mismatch")
            validate_artifacts(result, self.runtime.artifact_root, request.project_id)
            async with self.repo.lock(request.project_id):
                snapshot = self.repo.get(request.project_id)
                if snapshot.active_job_id != request.job_id:
                    return
                snapshot.final, snapshot.status, snapshot.active_job_id = result, "completed", None
                snapshot.final_is_stale = snapshot.project_revision != request.project_revision
                self.repo.save(snapshot, "render.completed", "Final reel ready to download", progress=1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = self.error(exc, "final")
            async with self.repo.lock(request.project_id):
                snapshot = self.repo.get(request.project_id)
                if snapshot.active_job_id != request.job_id:
                    return
                snapshot.final.status, snapshot.final.error = "failed", error
                snapshot.status, snapshot.active_job_id, snapshot.error = "failed", None, error
                self.repo.save(snapshot, "stage.failed", error.message)

    async def report_progress(self, *, project_id, job_id, stage, progress, scene_id=None):
        async with self.repo.lock(project_id):
            snapshot = self.repo.get(project_id)
            if scene_id:
                state = next((s for s in snapshot.scenes if s.scene_id == scene_id), None)
                if not state or state.active_job_id != job_id:
                    return
                if progress < state.progress:
                    return
                state.progress = progress
            else:
                if snapshot.active_job_id != job_id or snapshot.final is None or snapshot.final.job_id != job_id:
                    return
                if progress < snapshot.final.progress:
                    return
                snapshot.final.status, snapshot.final.progress = "running", progress
            self.repo.save(snapshot, "render.progress", f"{stage} progress", scene_id=scene_id, progress=progress)

    async def retry(self, project_id, stage, scene_id=None):
        if stage == "final":
            if self.repo.get(project_id).final is None or self.repo.get(project_id).final.status != "failed":
                raise RequestError(409, "RETRY_UNAVAILABLE", "No failed final render to retry")
            return await self.stitch(project_id)
        async with self.repo.lock(project_id):
            snapshot = self.repo.get(project_id)
            if snapshot.active_job_id or any(s.active_job_id for s in snapshot.scenes):
                raise RequestError(409, "PROJECT_BUSY", "Wait for active work before retrying")
            if stage == "scenes" and snapshot.timeline is not None:
                state = next((s for s in snapshot.scenes if s.scene_id == scene_id), None)
                if not state or not state.error or snapshot.timeline is None:
                    raise RequestError(409, "RETRY_UNAVAILABLE", "Select one failed scene to retry")
                context = self.context(project_id)
                job_id = str(uuid4())
                state.active_job_id, state.requested_revision = job_id, state.current_revision + 1
                state.status, state.error, state.progress = "generating", None, 0
                snapshot.status, snapshot.error = "generating_scenes", None
                # Retrying a failed edit can change previously completed final inputs.
                if state.current_revision:
                    snapshot.project_revision += 1
                    snapshot.final_is_stale = snapshot.final is not None
                snapshot = self.repo.save(snapshot, "scene.started", "Retrying scene", scene_id=scene_id,
                                          revision=state.requested_revision)
                self.launch(self.scene_job(project_id, scene_id, job_id, context))
                return snapshot
            if snapshot.status != "failed" or snapshot.timeline is not None:
                raise RequestError(409, "RETRY_UNAVAILABLE", "Only a failed unlocked stage can be retried")
            first_missing = next((name for name, field in (("research", "research"), ("dialogue", "script"),
                                  ("images", "images"), ("voice", "audio"), ("scenes", "timeline"))
                                  if getattr(snapshot, field) is None), None)
            if stage != first_missing:
                raise RequestError(409, "RETRY_STAGE_MISMATCH", f"Retry the first incomplete stage: {first_missing}")
            job_id = str(uuid4())
            snapshot.active_job_id, snapshot.status, snapshot.error = job_id, "created", None
            snapshot = self.repo.save(snapshot, "project.created", f"Resuming from {stage}")
        self.launch(self.run(project_id, job_id))
        return snapshot
