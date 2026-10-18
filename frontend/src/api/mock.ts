import { ApiError, type EditorApi } from './client'
import type { ArtifactRef, DialogueTurn, EventPage, ProjectEvent, ProjectSnapshot, ProjectSummary, SceneState, SceneSlot, UtteranceAudio } from '../types/contracts'

const storeKey = 'nebius-editor-mock-v1'
interface MockRecord { id: string; topic: string; created: number; editAt?: number; editMessage?: string; stitchAt?: number }
const read = (): MockRecord[] => { try { return JSON.parse(localStorage.getItem(storeKey) || '[]') as MockRecord[] } catch { return [] } }
const write = (records: MockRecord[]) => localStorage.setItem(storeKey, JSON.stringify(records))
const ref = (key: string, media_type: string): ArtifactRef => ({ key, media_type, sha256: '0'.repeat(64), size_bytes: 0 })
const fail = (message: string, status = 404): never => { throw new ApiError(status, { code: status === 404 ? 'NOT_FOUND' : 'VALIDATION_ERROR', stage: 'mock', message, retryable: false, scene_id: null }) }
const find = (id: string) => read().find(record => record.id === id) || fail('Mock project not found')
const sceneId = (index: number) => `s${String(index).padStart(2, '0')}`
const dialogueId = (order: number) => `d${String(order).padStart(3, '0')}`
const boundaries = [0, 273, 543, 813, 1083, 1353, 1800]
const completionOrder = [3, 1, 6, 2, 5, 4]
const lines = [
  'What happens when you start a WhatsApp voice call?',
  'This mock walkthrough traces the main stages, not private implementation details.',
  'Does the app first have to find the other person?',
  'Yes. Signaling helps the devices coordinate how a call can begin.',
  'So does every voice packet travel through one central server?',
  'Not necessarily. The network path depends on connectivity and call setup.',
  'What keeps a changing mobile network from ruining the call?',
  'Real time media systems adapt to delay, loss, and available bandwidth.',
  'Can we name the exact codec and routing for every call?',
  'No. Those details may vary, and this mock makes no verified claim.',
  'Then what is the reliable big picture?',
  'A call coordinates endpoints, carries audio, and adapts as conditions change.',
]
const turns: DialogueTurn[] = lines.map((text, i) => ({ dialogue_id: dialogueId(i + 1), order: i + 1, scene_index: Math.floor(i / 2) + 1, speaker_id: i % 2 ? 'jensen' : 'sundar', text, intent: i === 0 ? 'hook' : i === 11 ? 'takeaway' : i % 2 ? 'answer' : 'question', claim_ids: i % 2 ? [`c${String(Math.ceil((i + 1) / 2)).padStart(3, '0')}`] : [] }))
const timedUtterances = (() => { let cursor = 15; return turns.map((turn, index) => { const start_frame = cursor; const end_frame = cursor + 120; cursor = end_frame + (index % 2 === 0 ? 6 : 24); return { dialogue_id: turn.dialogue_id, start_frame, end_frame } }) })()
const slots: SceneSlot[] = Array.from({ length: 6 }, (_, i) => ({ scene_id: sceneId(i + 1), index: i + 1, start_frame: boundaries[i], end_frame: boundaries[i + 1], dialogue_ids: [dialogueId(i * 2 + 1), dialogueId(i * 2 + 2)], entry_state: 'clear_content', exit_state: 'clear_content' }))
const summary = ['Call setup', 'Finding a path', 'Moving packets', 'Handling change', 'What we know', 'The takeaway']
const mockVideo = 'mock-preview.mp4'
const event = (record: MockRecord, event_id: number, seconds: number, type: string, message: string, scene_id: string | null = null, revision: number | null = null, progress: number | null = null): ProjectEvent => ({ schema_version: '1.0', project_id: record.id, event_id, at: new Date(record.created + seconds * 1000).toISOString(), type, scene_id, revision, message, progress })

function scene(record: MockRecord, index: number, elapsed: number): SceneState {
  const id = sceneId(index)
  const position = completionOrder.indexOf(index)
  const started = 10 + position * 2
  const ready = started + 2
  const isEditing = index === 6 && record.editAt !== undefined
  const editElapsed = isEditing ? (Date.now() - record.editAt!) / 1000 : -1
  const revision = isEditing && editElapsed >= 5 ? 2 : elapsed >= ready ? 1 : 0
  const status = isEditing && editElapsed < 5 ? 'rendering' : elapsed >= ready ? 'ready' : elapsed >= started ? 'generating' : 'pending'
  return {
    scene_id: id, index, slot: elapsed >= 9 ? slots[index - 1] : null, status,
    current_revision: revision, requested_revision: isEditing ? 2 : 1,
    active_job_id: status === 'generating' || status === 'rendering' ? `mock-${id}-job` : null,
    progress: status === 'ready' ? 1 : status === 'generating' ? Math.min(.9, (elapsed - started) / 2) : status === 'rendering' ? Math.min(.9, editElapsed / 5) : 0,
    build: revision ? { schema_version: '1.0', project_id: record.id, scene_id: id, revision, context_hash: 'mock-context', timeline_hash: 'mock-timeline', source: ref(`projects/${record.id}/scenes/${id}/v${revision}/Scene.tsx`, 'text/typescript'), summary: revision === 2 ? `Revised: ${record.editMessage}` : summary[index - 1], cues: [], generation_mode: 'mock', repair_attempts: 0, warnings: [] } : null,
    preview: revision ? { schema_version: '1.0', project_id: record.id, job_id: `mock-preview-${id}-v${revision}`, status: 'completed', progress: 1, video: ref(`${id}/v${revision}/${mockVideo}`, 'video/mp4'), poster: ref(`mock-poster-${index}.svg`, 'image/svg+xml'), duration_frames: slots[index - 1].end_frame - slots[index - 1].start_frame, error: null } : null,
    error: null,
  }
}

function snapshot(record: MockRecord): ProjectSnapshot {
  const elapsed = (Date.now() - record.created) / 1000
  const scenes = Array.from({ length: 6 }, (_, i) => scene(record, i + 1, elapsed))
  const allReady = scenes.every(item => item.status === 'ready')
  const stitchElapsed = record.stitchAt === undefined ? -1 : (Date.now() - record.stitchAt) / 1000
  const finalComplete = stitchElapsed >= 7
  const final = record.stitchAt === undefined ? null : {
    schema_version: '1.0' as const, project_id: record.id, job_id: 'mock-final', status: finalComplete ? 'completed' as const : 'running' as const,
    progress: finalComplete ? 1 : Math.max(0, Math.min(.95, stitchElapsed / 7)), video: finalComplete ? ref(mockVideo, 'video/mp4') : null,
    poster: null, duration_frames: finalComplete ? 1800 : null, error: null,
  }
  const status = final ? finalComplete ? 'completed' : 'rendering' : allReady ? 'ready' : elapsed < 2 ? 'researching' : elapsed < 4 ? 'scripting' : elapsed < 6 ? 'finding_images' : elapsed < 9 ? 'voicing' : 'generating_scenes'
  const utterances: UtteranceAudio[] = turns.map(turn => {
    const words = turn.text.split(/\s+/).map((text, i, arr) => ({ word_id: `${turn.dialogue_id}_w${String(i + 1).padStart(3, '0')}`, text, start_ms: Math.floor(i * 3600 / arr.length), end_ms: Math.floor((i + 1) * 3600 / arr.length) }))
    return { dialogue_id: turn.dialogue_id, speaker_id: turn.speaker_id, wav: ref('mock-audio.wav', 'audio/wav'), transcript: turn.text, transcript_file: ref('mock-transcript.txt', 'text/plain'), words_file: ref('mock-words.json', 'application/json'), srt_file: ref('mock-subtitles.srt', 'text/plain'), duration_ms: 4000, frame_count: 120, sample_rate_hz: 48000, channels: 1, sample_count: 192000, words, timing_quality: 'mock' }
  })
  return {
    schema_version: '1.0', project_id: record.id, topic: record.topic, project_revision: record.editAt ? 2 : 1, mode: 'mock', status,
    created_at: new Date(record.created).toISOString(), updated_at: new Date(Date.now()).toISOString(), active_job_id: allReady ? null : 'mock-pipeline',
    research: elapsed >= 2 ? { schema_version: '1.0', project_id: record.id, topic: record.topic, tavily_request_id: 'mock-research', summary: 'Demonstration research for a voice calling explainer. These statements are fixture data.', report_markdown: 'Mock research: this preview demonstrates the workflow only.', sources: [1, 2].map(i => ({ source_id: `src00${i}`, title: `Mock source ${i}`, url: `https://example.com/mock-source-${i}`, favicon: null })), claims: Array.from({ length: 6 }, (_, i) => ({ claim_id: `c00${i + 1}`, text: `Mock demonstration claim for scene ${i + 1}`, source_ids: [i % 2 ? 'src002' : 'src001'], evidence_type: 'inference' as const, caveat: 'Fixture data only; not verified research.' })), uncertainties: ['This mock does not verify proprietary infrastructure.'], raw_response: ref('mock-research.json', 'application/json'), is_mock: true } : null,
    script: elapsed >= 4 ? { schema_version: '1.0', project_id: record.id, script_revision: 1, title: 'How a voice call comes together', language: 'en', turns } : null,
    images: elapsed >= 6 ? { schema_version: '1.0', project_id: record.id, script_revision: 1, selections: Array.from({ length: 6 }, (_, i) => ({ query: { scene_index: i + 1, dialogue_ids: [dialogueId(i * 2 + 1), dialogueId(i * 2 + 2)], query: `Mock visual for scene ${i + 1}`, reason: 'Frontend fixture' }, status: i === 2 ? 'selected' as const : 'unavailable' as const, asset: i === 2 ? ref('mock-poster-3.svg', 'image/svg+xml') : null, image_url: i === 2 ? 'https://example.com/mock-image.svg' : null, source_page_url: null, description: i === 2 ? 'Mock diagram' : null, reason: i === 2 ? null : 'Vector fallback in frontend fixture' })) } : null,
    audio: elapsed >= 8 ? { schema_version: '1.0', project_id: record.id, script_revision: 1, utterances, total_speech_frames: 1440 } : null,
    timeline: elapsed >= 9 ? { schema_version: '1.0', project_id: record.id, script_revision: 1, video: { width: 1080, height: 1920, fps: 30, duration_frames: 1800, scene_count: 6 }, utterances: timedUtterances, scenes: slots } : null,
    scenes, final, final_project_revision: record.stitchAt ? (record.editAt && record.editAt < record.stitchAt ? 2 : 1) : null,
    final_is_stale: Boolean(record.stitchAt && record.editAt && record.editAt > record.stitchAt), error: null,
  }
}

function events(record: MockRecord): ProjectEvent[] {
  const elapsed = (Date.now() - record.created) / 1000
  const entries = [
    event(record, 1, 0, 'project.created', 'Project created'),
    event(record, 2, 0, 'research.started', 'Research started'),
    event(record, 3, 2, 'research.ready', 'Mock research and sources are ready'),
    event(record, 4, 4, 'dialogue.ready', 'Twelve dialogue turns are ready'),
    event(record, 5, 6, 'images.ready', 'Visual references checked'),
    event(record, 6, 6, 'voice.started', 'Generating and aligning dialogue'),
    event(record, 7, 8, 'voice.ready', 'Twelve mock audio clips and word timings are ready'),
    event(record, 8, 9, 'timeline.ready', 'Six scene boundaries locked'),
  ]
  completionOrder.forEach((index, position) => {
    const start = 10 + position * 2
    entries.push(event(record, 9 + position * 2, start, 'scene.started', `Scene ${index} started`, sceneId(index), 1))
    entries.push(event(record, 10 + position * 2, start + 2, 'scene.ready', `Scene ${index} preview ready`, sceneId(index), 1))
  })
  if (record.editAt) {
    entries.push({ ...event(record, 21, 0, 'edit.accepted', 'Scene 6 correction accepted', 's06', 2), at: new Date(record.editAt).toISOString() })
    entries.push({ ...event(record, 22, 0, 'scene.ready', 'Scene 6 revised preview ready', 's06', 2), at: new Date(record.editAt + 5000).toISOString() })
  }
  if (record.stitchAt) {
    entries.push({ ...event(record, 23, 0, 'render.started', 'Final reel rendering'), at: new Date(record.stitchAt).toISOString() })
    entries.push({ ...event(record, 24, 0, 'render.completed', 'Final reel ready to download'), at: new Date(record.stitchAt + 7000).toISOString() })
  }
  return entries.filter(entry => Date.parse(entry.at) <= Date.now() && (entry.event_id > 20 || elapsed >= (Date.parse(entry.at) - record.created) / 1000)).sort((a, b) => Date.parse(a.at) - Date.parse(b.at) || a.event_id - b.event_id).map((entry, index) => ({ ...entry, event_id: index + 1 }))
}

export const mockApi: EditorApi = {
  async listProjects(): Promise<ProjectSummary[]> { return read().slice().reverse().map(record => ({ schema_version: '1.0', project_id: record.id, topic: record.topic, status: snapshot(record).status, updated_at: new Date(record.stitchAt || record.editAt || record.created).toISOString(), mode: 'mock' })) },
  async createProject(input) { if (input.topic.trim().length < 5) fail('Enter a topic with at least five characters', 422); const record = { id: `demo-${Date.now()}`, topic: input.topic.trim(), created: Date.now() }; write([...read(), record]); return snapshot(record) },
  async getProject(id) { return snapshot(find(id)) },
  async getEvents(id, after): Promise<EventPage> { const page = events(find(id)).filter(entry => entry.event_id > after); return { events: page, next_after: page.at(-1)?.event_id ?? after } },
  async editProject(id, input) { const records = read(); const record = records.find(item => item.id === id) || fail('Mock project not found'); if (input.scene_id !== 's06') fail('Select scene 6 for the mock correction', 422); if (input.expected_scene_revision !== 1) fail('Scene revision is stale', 409); if (snapshot(record).scenes[5].status !== 'ready') fail('Scene 6 is busy', 409); record.editAt = Date.now(); record.editMessage = input.message; write(records); return snapshot(record) },
  async retryProject(id) { return snapshot(find(id)) },
  async stitchProject(id) { const records = read(); const record = records.find(item => item.id === id) || fail('Mock project not found'); if (!snapshot(record).scenes.every(scene => scene.status === 'ready')) fail('Wait for all six previews', 409); record.stitchAt = Date.now(); write(records); return snapshot(record) },
  artifactUrl(ref) { if (ref.key.startsWith('mock-poster-')) return '/mock/mock-poster.svg'; if (ref.key.endsWith(mockVideo)) return `/mock/mock-preview.mp4?key=${encodeURIComponent(ref.key)}`; if (ref.key === 'mock-audio.wav') return '/mock/mock-audio.wav'; return '#' },
}
