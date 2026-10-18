from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, TypeVar
from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(Model):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str


class ArtifactRef(Model):
    key: str                       # Relative to ARTIFACT_ROOT; no ../ or absolute path.
    media_type: str
    sha256: str                     # 64 lowercase hex characters.
    size_bytes: int = Field(ge=0)


class VideoSpec(Model):
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps: Literal[30] = 30
    duration_frames: Literal[1800] = 1800
    scene_count: Literal[6] = 6


class ThemeSpec(Model):
    theme_id: Literal["notebook_v1"] = "notebook_v1"
    background: Literal["#FFFFFF"] = "#FFFFFF"
    dot_color: Literal["#D8DEE8"] = "#D8DEE8"
    dot_spacing: Literal[24] = 24
    dot_radius: Literal[1] = 1
    workboard_height: Literal[1344] = 1344
    character_region_y: Literal[1344] = 1344
    font_family: Literal["DejaVu Sans"] = "DejaVu Sans"
    boundary_frames: Literal[12] = 12


SpeakerId = Literal["sundar", "jensen"]


class CharacterSpec(Model):
    character_id: SpeakerId
    display_name: str
    image: ArtifactRef | None = None
    voice_reference: ArtifactRef | None = None
    reference_transcript: str | None = None
    voice_id: str | None = None


class ProjectCreate(Model):
    topic: str = Field(min_length=5, max_length=1000)
    language: Literal["en"] = "en"


class ResearchRequest(Envelope):
    topic: str


class Source(Model):
    source_id: str                 # src001, src002, ...
    title: str
    url: str
    favicon: str | None = None


class Claim(Model):
    claim_id: str                  # c001, c002, ...
    text: str
    source_ids: list[str] = Field(min_length=1)
    evidence_type: Literal["documented", "general_industry_practice", "inference"]
    caveat: str | None = None


class ResearchNotes(Model):
    summary: str
    claims: list[Claim]
    uncertainties: list[str] = Field(default_factory=list)


class ResearchBundle(Envelope):
    topic: str
    tavily_request_id: str
    summary: str
    report_markdown: str
    sources: list[Source]
    claims: list[Claim]
    uncertainties: list[str] = Field(default_factory=list)
    raw_response: ArtifactRef
    is_mock: bool = False


class DialogueTurn(Model):
    dialogue_id: str               # d001 ... d012
    order: int = Field(ge=1, le=12)
    scene_index: int = Field(ge=1, le=6)
    speaker_id: SpeakerId
    text: str = Field(min_length=1)
    intent: Literal["hook", "question", "answer", "challenge", "takeaway"]
    claim_ids: list[str] = Field(default_factory=list)


class DialogueScript(Envelope):
    script_revision: int = Field(ge=1)
    title: str
    language: Literal["en"] = "en"
    turns: list[DialogueTurn] = Field(min_length=12, max_length=12)


class DialogueRequest(Envelope):
    research: ResearchBundle
    characters: list[CharacterSpec] = Field(min_length=2, max_length=2)
    script_revision: int = 1
    previous_script: DialogueScript | None = None
    revision_instruction: str | None = None


class ImageQuery(Model):
    scene_index: int = Field(ge=1, le=6)
    dialogue_ids: list[str]
    query: str
    reason: str


class ImageQueryPlan(Model):
    queries: list[ImageQuery] = Field(min_length=6, max_length=6)


class ImageSelection(Model):
    query: ImageQuery
    status: Literal["selected", "unavailable"]
    asset: ArtifactRef | None = None
    image_url: str | None = None
    source_page_url: str | None = None
    description: str | None = None
    reason: str | None = None


class ImageRequest(Envelope):
    research: ResearchBundle
    script: DialogueScript


class ImageBundle(Envelope):
    script_revision: int
    selections: list[ImageSelection] = Field(min_length=6, max_length=6)


class VoiceRequest(Envelope):
    script: DialogueScript
    characters: list[CharacterSpec] = Field(min_length=2, max_length=2)
    max_speech_frames: Literal[1599] = 1599


class WordTiming(Model):
    word_id: str                   # e.g. d001_w001
    text: str
    start_ms: int = Field(ge=0)    # Clip-local, after final audio processing.
    end_ms: int = Field(ge=0)


class AlignmentResult(Model):
    dialogue_id: str
    audio_sha256: str
    transcript: str
    words: list[WordTiming] = Field(min_length=1)


class UtteranceAudio(Model):
    dialogue_id: str
    speaker_id: SpeakerId
    wav: ArtifactRef
    transcript: str
    transcript_file: ArtifactRef
    words_file: ArtifactRef
    srt_file: ArtifactRef
    duration_ms: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    sample_rate_hz: Literal[48000] = 48000
    channels: Literal[1] = 1
    sample_count: int = Field(gt=0)
    words: list[WordTiming] = Field(min_length=1)
    timing_quality: Literal["provider", "forced_alignment", "mock"]


class AudioBundle(Envelope):
    script_revision: int
    utterances: list[UtteranceAudio] = Field(min_length=12, max_length=12)
    total_speech_frames: int = Field(gt=0)


class TimedUtterance(Model):
    dialogue_id: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)


class SceneSlot(Model):
    scene_id: str                  # s01 ... s06
    index: int = Field(ge=1, le=6)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    dialogue_ids: list[str] = Field(min_length=2, max_length=2)
    entry_state: Literal["clear_content"] = "clear_content"
    exit_state: Literal["clear_content"] = "clear_content"


class Timeline(Envelope):
    script_revision: int
    video: VideoSpec = Field(default_factory=VideoSpec)
    utterances: list[TimedUtterance] = Field(min_length=12, max_length=12)
    scenes: list[SceneSlot] = Field(min_length=6, max_length=6)


class SceneContext(Envelope):
    research: ResearchBundle
    script: DialogueScript
    images: ImageBundle
    audio: AudioBundle
    timeline: Timeline
    characters: list[CharacterSpec]
    theme: ThemeSpec = Field(default_factory=ThemeSpec)
    timeline_hash: str
    context_hash: str


class AnimationCue(Model):
    cue_id: str
    word_ids: list[str] = Field(default_factory=list)
    start_frame: int = Field(ge=0)  # Scene-local, not global.
    end_frame: int = Field(gt=0)
    description: str
    claim_ids: list[str] = Field(default_factory=list)


class SceneDraft(Model):
    source_code: str
    summary: str
    cues: list[AnimationCue] = Field(default_factory=list)


class SourceValidationResult(Model):
    valid: bool
    diagnostics: list[str] = Field(default_factory=list)


class SceneBuild(Envelope):
    scene_id: str
    revision: int = Field(ge=1)
    context_hash: str
    timeline_hash: str
    source: ArtifactRef             # Complete validated Scene.tsx.
    summary: str
    cues: list[AnimationCue] = Field(default_factory=list)
    generation_mode: Literal["agent", "fallback", "mock"]
    repair_attempts: int = Field(default=0, ge=0, le=2)
    warnings: list[str] = Field(default_factory=list)


class SceneTask(Envelope):
    job_id: str
    context: SceneContext
    slot: SceneSlot
    revision: int = Field(ge=1)
    previous_build: SceneBuild | None = None
    edit_instruction: str | None = None


class PreviewRequest(Envelope):
    kind: Literal["scene_preview"] = "scene_preview"
    job_id: str
    context: SceneContext
    slot: SceneSlot
    build: SceneBuild


class FinalRenderRequest(Envelope):
    kind: Literal["final"] = "final"
    job_id: str
    project_revision: int
    context: SceneContext
    builds: list[SceneBuild] = Field(min_length=6, max_length=6)


class PipelineError(Model):
    code: str
    stage: str
    message: str
    retryable: bool = False
    scene_id: str | None = None


class RenderResult(Envelope):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: float = Field(ge=0, le=1)
    video: ArtifactRef | None = None
    poster: ArtifactRef | None = None
    duration_frames: int | None = None
    error: PipelineError | None = None


class ScenePreviewOutcome(Envelope):
    build: SceneBuild
    render: RenderResult


class StageFailure(Exception):
    def __init__(self, error: PipelineError):
        self.error = error
        super().__init__(error.message)


class EditRequest(Model):
    message: str = Field(min_length=1, max_length=4000)
    scene_id: str | None = None
    expected_scene_revision: int | None = None


class EditRoutingRequest(Envelope):
    message: str
    scene_ids: list[str]
    selected_scene_id: str | None = None


class EditIntent(Model):
    action: Literal["edit_scene", "unsupported"]
    scene_id: str | None = None
    instruction: str
    reason: str | None = None


class SceneState(Model):
    scene_id: str
    index: int
    slot: SceneSlot | None = None  # None until audio timeline is locked.
    status: Literal["pending", "generating", "rendering", "ready", "failed"] = "pending"
    current_revision: int = 0     # Last successfully previewed revision.
    requested_revision: int = 1
    active_job_id: str | None = None
    progress: float = Field(default=0, ge=0, le=1)
    build: SceneBuild | None = None
    preview: RenderResult | None = None
    error: PipelineError | None = None


class ProjectSnapshot(Envelope):
    topic: str
    project_revision: int = 1
    mode: Literal["mock", "live"]
    status: Literal[
        "created", "researching", "scripting", "finding_images", "voicing",
        "planning", "generating_scenes", "ready", "rendering", "completed", "failed"
    ]
    created_at: str                # UTC ISO 8601.
    updated_at: str
    active_job_id: str | None = None
    research: ResearchBundle | None = None
    script: DialogueScript | None = None
    images: ImageBundle | None = None
    audio: AudioBundle | None = None
    timeline: Timeline | None = None
    scenes: list[SceneState] = Field(min_length=6, max_length=6)
    final: RenderResult | None = None
    final_project_revision: int | None = None
    final_is_stale: bool = False
    error: PipelineError | None = None


class ProjectSummary(Envelope):
    topic: str
    status: str
    updated_at: str
    mode: Literal["mock", "live"]


class ProjectEvent(Envelope):
    event_id: int                  # Monotonically increasing per project.
    at: str
    type: str                     # Names enumerated in section 10.
    scene_id: str | None = None
    revision: int | None = None
    message: str
    progress: float | None = None


class EventPage(Model):
    events: list[ProjectEvent]
    next_after: int


T = TypeVar("T", bound=BaseModel)


class Runtime(Protocol):
    mock_mode: bool
    artifact_root: Path
    settings: Mapping[str, Any]    # Server-only configuration.
    llm: Any                      # Configured LangChain chat model for create_agent.

    def path(self, key: str) -> Path: ...

    async def write_bytes(
        self, key: str, data: bytes, media_type: str
    ) -> ArtifactRef: ...

    async def write_json(self, key: str, value: Any) -> ArtifactRef: ...

    async def structured(
        self, *, messages: list[dict[str, str]], schema: type[T]
    ) -> T: ...

    async def report_progress(
        self, *, project_id: str, job_id: str, stage: str,
        progress: float, scene_id: str | None = None
    ) -> None: ...
