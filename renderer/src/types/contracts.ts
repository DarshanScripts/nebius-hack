// Renderer-used mirror of contracts/models.py (plan.md section 9).
// Field names are the snake_case wire names; never rename them here.

export type SpeakerId = 'sundar' | 'jensen';

export interface ArtifactRef {
  key: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
}

export interface VideoSpec {
  width: 1080;
  height: 1920;
  fps: 30;
  duration_frames: 1800;
  scene_count: 6;
}

export interface ThemeSpec {
  theme_id: 'notebook_v1';
  background: '#FFFFFF';
  dot_color: '#D8DEE8';
  dot_spacing: 24;
  dot_radius: 1;
  workboard_height: 1344;
  character_region_y: 1344;
  font_family: 'DejaVu Sans';
  boundary_frames: 12;
}

export interface CharacterSpec {
  character_id: SpeakerId;
  display_name: string;
  image: ArtifactRef | null;
  voice_reference: ArtifactRef | null;
  reference_transcript: string | null;
  voice_id: string | null;
}

export interface Source {
  source_id: string;
  title: string;
  url: string;
  favicon: string | null;
}

export interface Claim {
  claim_id: string;
  text: string;
  source_ids: string[];
  evidence_type: 'documented' | 'general_industry_practice' | 'inference';
  caveat: string | null;
}

export interface ResearchBundle {
  schema_version: '1.0';
  project_id: string;
  topic: string;
  tavily_request_id: string;
  summary: string;
  report_markdown: string;
  sources: Source[];
  claims: Claim[];
  uncertainties: string[];
  raw_response: ArtifactRef;
  is_mock: boolean;
}

export interface DialogueTurn {
  dialogue_id: string;
  order: number;
  scene_index: number;
  speaker_id: SpeakerId;
  text: string;
  intent: 'hook' | 'question' | 'answer' | 'challenge' | 'takeaway';
  claim_ids: string[];
}

export interface DialogueScript {
  schema_version: '1.0';
  project_id: string;
  script_revision: number;
  title: string;
  language: 'en';
  turns: DialogueTurn[];
}

export interface ImageQuery {
  scene_index: number;
  dialogue_ids: string[];
  query: string;
  reason: string;
}

export interface ImageSelection {
  query: ImageQuery;
  status: 'selected' | 'unavailable';
  asset: ArtifactRef | null;
  image_url: string | null;
  source_page_url: string | null;
  description: string | null;
  reason: string | null;
}

export interface ImageBundle {
  schema_version: '1.0';
  project_id: string;
  script_revision: number;
  selections: ImageSelection[];
}

export interface WordTiming {
  word_id: string;
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface UtteranceAudio {
  dialogue_id: string;
  speaker_id: SpeakerId;
  wav: ArtifactRef;
  transcript: string;
  transcript_file: ArtifactRef;
  words_file: ArtifactRef;
  srt_file: ArtifactRef;
  duration_ms: number;
  frame_count: number;
  sample_rate_hz: 48000;
  channels: 1;
  sample_count: number;
  words: WordTiming[];
  timing_quality: 'provider' | 'forced_alignment' | 'mock';
}

export interface AudioBundle {
  schema_version: '1.0';
  project_id: string;
  script_revision: number;
  utterances: UtteranceAudio[];
  total_speech_frames: number;
}

export interface TimedUtterance {
  dialogue_id: string;
  start_frame: number;
  end_frame: number;
}

export interface SceneSlot {
  scene_id: string;
  index: number;
  start_frame: number;
  end_frame: number;
  dialogue_ids: string[];
  entry_state: 'clear_content';
  exit_state: 'clear_content';
}

export interface Timeline {
  schema_version: '1.0';
  project_id: string;
  script_revision: number;
  video: VideoSpec;
  utterances: TimedUtterance[];
  scenes: SceneSlot[];
}

export interface SceneContext {
  schema_version: '1.0';
  project_id: string;
  research: ResearchBundle;
  script: DialogueScript;
  images: ImageBundle;
  audio: AudioBundle;
  timeline: Timeline;
  characters: CharacterSpec[];
  theme: ThemeSpec;
  timeline_hash: string;
  context_hash: string;
}

export interface AnimationCue {
  cue_id: string;
  word_ids: string[];
  start_frame: number;
  end_frame: number;
  description: string;
  claim_ids: string[];
}

export interface SceneBuild {
  schema_version: '1.0';
  project_id: string;
  scene_id: string;
  revision: number;
  context_hash: string;
  timeline_hash: string;
  source: ArtifactRef;
  summary: string;
  cues: AnimationCue[];
  generation_mode: 'agent' | 'fallback' | 'mock';
  repair_attempts: number;
  warnings: string[];
}

export interface PreviewRequest {
  schema_version: '1.0';
  project_id: string;
  kind: 'scene_preview';
  job_id: string;
  context: SceneContext;
  slot: SceneSlot;
  build: SceneBuild;
}

export interface FinalRenderRequest {
  schema_version: '1.0';
  project_id: string;
  kind: 'final';
  job_id: string;
  project_revision: number;
  context: SceneContext;
  builds: SceneBuild[];
}

export type RenderJobRequest = PreviewRequest | FinalRenderRequest;

export interface SourceValidationResult {
  valid: boolean;
  diagnostics: string[];
}

export interface PipelineError {
  code: string;
  stage: string;
  message: string;
  retryable: boolean;
  scene_id: string | null;
}

export interface RenderResult {
  schema_version: '1.0';
  project_id: string;
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress: number;
  video: ArtifactRef | null;
  poster: ArtifactRef | null;
  duration_frames: number | null;
  error: PipelineError | null;
}

/** Props passed from the worker into the Remotion bundle (not a wire contract). */
export type RenderInputProps = {
  context: SceneContext;
  builds: SceneBuild[];
  /** Artifact key -> path relative to the job's public dir (resolved with staticFile). */
  assets: Record<string, string>;
  /** Set for previews: the single scene to render. */
  preview_scene_id: string | null;
};
