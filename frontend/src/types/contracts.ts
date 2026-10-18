export type SpeakerId = 'sundar' | 'jensen'
export type ProjectStatus = 'created' | 'researching' | 'scripting' | 'finding_images' | 'voicing' | 'planning' | 'generating_scenes' | 'ready' | 'rendering' | 'completed' | 'failed'
export type SceneStatus = 'pending' | 'generating' | 'rendering' | 'ready' | 'failed'

export interface PipelineError { code: string; stage: string; message: string; retryable: boolean; scene_id: string | null }
export interface ArtifactRef { key: string; media_type: string; sha256: string; size_bytes: number }
export interface Source { source_id: string; title: string; url: string; favicon: string | null }
export interface Claim { claim_id: string; text: string; source_ids: string[]; evidence_type: 'documented' | 'general_industry_practice' | 'inference'; caveat: string | null }
export interface ResearchBundle { schema_version: '1.0'; project_id: string; topic: string; tavily_request_id: string; summary: string; report_markdown: string; sources: Source[]; claims: Claim[]; uncertainties: string[]; raw_response: ArtifactRef; is_mock: boolean }
export interface DialogueTurn { dialogue_id: string; order: number; scene_index: number; speaker_id: SpeakerId; text: string; intent: 'hook' | 'question' | 'answer' | 'challenge' | 'takeaway'; claim_ids: string[] }
export interface DialogueScript { schema_version: '1.0'; project_id: string; script_revision: number; title: string; language: 'en'; turns: DialogueTurn[] }
export interface WordTiming { word_id: string; text: string; start_ms: number; end_ms: number }
export interface UtteranceAudio { dialogue_id: string; speaker_id: SpeakerId; wav: ArtifactRef; transcript: string; transcript_file: ArtifactRef; words_file: ArtifactRef; srt_file: ArtifactRef; duration_ms: number; frame_count: number; sample_rate_hz: 48000; channels: 1; sample_count: number; words: WordTiming[]; timing_quality: 'provider' | 'forced_alignment' | 'mock' }
export interface AudioBundle { schema_version: '1.0'; project_id: string; script_revision: number; utterances: UtteranceAudio[]; total_speech_frames: number }
export interface SceneSlot { scene_id: string; index: number; start_frame: number; end_frame: number; dialogue_ids: string[]; entry_state: 'clear_content'; exit_state: 'clear_content' }
export interface Timeline { schema_version: '1.0'; project_id: string; script_revision: number; video: { width: 1080; height: 1920; fps: 30; duration_frames: 1800; scene_count: 6 }; utterances: { dialogue_id: string; start_frame: number; end_frame: number }[]; scenes: SceneSlot[] }
export interface SceneBuild { schema_version: '1.0'; project_id: string; scene_id: string; revision: number; context_hash: string; timeline_hash: string; source: ArtifactRef; summary: string; generation_mode: 'agent' | 'fallback' | 'mock'; repair_attempts: number; warnings: string[] }
export interface RenderResult { schema_version: '1.0'; project_id: string; job_id: string; status: 'queued' | 'running' | 'completed' | 'failed'; progress: number; video: ArtifactRef | null; poster: ArtifactRef | null; duration_frames: number | null; error: PipelineError | null }
export interface SceneState { scene_id: string; index: number; slot: SceneSlot | null; status: SceneStatus; current_revision: number; requested_revision: number; active_job_id: string | null; progress: number; build: SceneBuild | null; preview: RenderResult | null; error: PipelineError | null }
export interface ProjectSnapshot { schema_version: '1.0'; project_id: string; topic: string; project_revision: number; mode: 'mock' | 'live'; status: ProjectStatus; created_at: string; updated_at: string; active_job_id: string | null; research: ResearchBundle | null; script: DialogueScript | null; images: unknown | null; audio: AudioBundle | null; timeline: Timeline | null; scenes: SceneState[]; final: RenderResult | null; final_project_revision: number | null; final_is_stale: boolean; error: PipelineError | null }
export interface ProjectSummary { schema_version: '1.0'; project_id: string; topic: string; status: string; updated_at: string; mode: 'mock' | 'live' }
export interface ProjectEvent { schema_version: '1.0'; project_id: string; event_id: number; at: string; type: string; scene_id: string | null; revision: number | null; message: string; progress: number | null }
export interface EventPage { events: ProjectEvent[]; next_after: number }
export interface ProjectCreate { topic: string; language: 'en' }
export interface EditRequest { message: string; scene_id?: string; expected_scene_revision?: number }
export type RetryStage = 'research' | 'dialogue' | 'images' | 'voice' | 'scenes' | 'final'
