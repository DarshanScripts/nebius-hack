import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, liveApi } from './api/client'
import { mockApi } from './api/mock'
import type { EditorApi } from './api/client'
import type { ProjectEvent, ProjectSnapshot, ProjectSummary, RetryStage, SceneState } from './types/contracts'

const isFrontendMock = new URLSearchParams(window.location.search).get('mock') === '1'
const api: EditorApi = isFrontendMock ? mockApi : liveApi
const selectionKey = `nebius-selected-project-${isFrontendMock ? 'frontend-mock' : 'api'}`
const names = { sundar: 'Sundar Pichai', jensen: 'Jensen Huang' }
const stageLabels: Record<string, string> = { created: 'Starting', researching: 'Researching', scripting: 'Writing dialogue', finding_images: 'Finding visuals', voicing: 'Creating voice', planning: 'Planning timeline', generating_scenes: 'Generating scenes', ready: 'Ready to stitch', rendering: 'Rendering final', completed: 'Complete', failed: 'Needs attention' }
const retryStage = (snapshot: ProjectSnapshot): RetryStage => {
  if (snapshot.final?.status === 'failed') return 'final'
  if (snapshot.timeline && snapshot.error?.scene_id) return 'scenes'
  if (!snapshot.research) return 'research'
  if (!snapshot.script) return 'dialogue'
  if (!snapshot.images) return 'images'
  if (!snapshot.audio) return 'voice'
  return 'scenes'
}
const messageOf = (error: unknown) => error instanceof ApiError ? error.status === 409 ? `${error.message} Refreshing project state…` : error.message : error instanceof Error ? error.message : 'Something went wrong'
const time = (date: string) => new Date(date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const isActive = (project: ProjectSnapshot) => Boolean(project.active_job_id || project.scenes.some(scene => scene.active_job_id) || project.final?.status === 'queued' || project.final?.status === 'running')

export function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectId, setProjectId] = useState<string | null>(() => localStorage.getItem(selectionKey))
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null)
  const [events, setEvents] = useState<ProjectEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [topic, setTopic] = useState('How does WhatsApp voice calling infrastructure work?')
  const [message, setMessage] = useState('Please correct scene six: make the packet diagram clearer')
  const [selectedScene, setSelectedScene] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [researchOpen, setResearchOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState<'activity' | 'scenes'>('activity')
  const cursor = useRef(0)
  const generation = useRef(0)
  const inFlight = useRef<number | null>(null)
  const nextPollAt = useRef(0)

  const refreshList = useCallback(async () => setProjects(await api.listProjects()), [])
  const refresh = useCallback(async (id: string, requestGeneration: number) => {
    if (inFlight.current === requestGeneration) return
    inFlight.current = requestGeneration
    try {
      const [nextSnapshot, page] = await Promise.all([api.getProject(id), api.getEvents(id, cursor.current)])
      if (generation.current !== requestGeneration) return
      setSnapshot(nextSnapshot)
      nextPollAt.current = Date.now() + (isActive(nextSnapshot) ? 1000 : 5000)
      setProjects(previous => previous.map(item => item.project_id === id ? { ...item, status: nextSnapshot.status, updated_at: nextSnapshot.updated_at } : item))
      cursor.current = page.next_after
      setEvents(previous => {
        const byId = new Map(previous.map(item => [item.event_id, item]))
        page.events.forEach(item => byId.set(item.event_id, item))
        return [...byId.values()].sort((a, b) => a.event_id - b.event_id)
      })
    } catch (reason) { if (generation.current === requestGeneration) { setError(messageOf(reason)); nextPollAt.current = Date.now() + 5000 } }
    finally { if (inFlight.current === requestGeneration) inFlight.current = null; if (generation.current === requestGeneration) setLoading(false) }
  }, [])

  useEffect(() => { refreshList().catch(reason => { setError(messageOf(reason)); setLoading(false) }) }, [refreshList])
  useEffect(() => {
    const current = ++generation.current
    nextPollAt.current = 0
    cursor.current = 0
    setEvents([])
    setSnapshot(null)
    setLoading(Boolean(projectId))
    if (!projectId) { localStorage.removeItem(selectionKey); return }
    localStorage.setItem(selectionKey, projectId)
    void refresh(projectId, current)
    const timer = window.setInterval(() => { if (Date.now() >= nextPollAt.current) void refresh(projectId, current) }, 1000)
    return () => window.clearInterval(timer)
  }, [projectId, refresh])

  const applyResponse = (next: ProjectSnapshot) => {
    setSnapshot(next)
    nextPollAt.current = 0
    if (projectId !== next.project_id) setProjectId(next.project_id)
    void refreshList()
  }
  const submitTopic = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    const requestGeneration = generation.current
    try { const next = await api.createProject({ topic: topic.trim(), language: 'en' }); if (generation.current === requestGeneration) applyResponse(next) }
    catch (reason) { if (generation.current === requestGeneration) setError(messageOf(reason)) }
    finally { setBusy(false) }
  }
  const submitEdit = async (event: React.FormEvent) => {
    event.preventDefault(); if (!snapshot || !message.trim()) return
    setBusy(true); setError('')
    const requestGeneration = generation.current
    try {
      const scene = snapshot.scenes.find(item => item.scene_id === selectedScene)
      const next = await api.editProject(snapshot.project_id, { message: message.trim(), ...(scene ? { scene_id: scene.scene_id, expected_scene_revision: scene.current_revision } : {}) })
      if (generation.current === requestGeneration) { applyResponse(next); setMessage('') }
    } catch (reason) { if (generation.current === requestGeneration) { setError(messageOf(reason)); if (reason instanceof ApiError && reason.status === 409) void refresh(snapshot.project_id, requestGeneration) } }
    finally { setBusy(false) }
  }
  const stitch = async () => {
    if (!snapshot) return
    setBusy(true); setError('')
    const requestGeneration = generation.current
    try { const next = await api.stitchProject(snapshot.project_id); if (generation.current === requestGeneration) applyResponse(next) }
    catch (reason) { if (generation.current === requestGeneration) { setError(messageOf(reason)); if (reason instanceof ApiError && reason.status === 409) void refresh(snapshot.project_id, requestGeneration) } }
    finally { setBusy(false) }
  }
  const retry = async (stage: RetryStage, sceneId?: string) => {
    if (!snapshot) return
    setBusy(true); setError('')
    const requestGeneration = generation.current
    try { const next = await api.retryProject(snapshot.project_id, stage, sceneId); if (generation.current === requestGeneration) applyResponse(next) }
    catch (reason) { if (generation.current === requestGeneration) setError(messageOf(reason)) }
    finally { setBusy(false) }
  }
  const allReady = Boolean(snapshot?.timeline && snapshot.scenes.length === 6 && snapshot.scenes.every(scene => scene.status === 'ready' && scene.preview?.status === 'completed' && scene.active_job_id === null))
  const canStitch = allReady && !busy && snapshot?.status !== 'rendering' && (!snapshot?.final || snapshot.final_is_stale || snapshot.final.status === 'failed')
  const selected = snapshot?.scenes.find(scene => scene.scene_id === selectedScene)

  return <div className={`workspace ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">✦</div>{sidebarOpen && <div className="brand-copy"><strong>Reel Lab</strong><span>NEBIUS STUDIO</span></div>}<button className="icon-button sidebar-toggle" onClick={() => setSidebarOpen(value => !value)} aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'} title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}>{sidebarOpen ? '‹' : '›'}</button></div>
      <button className="new-button" aria-label="New reel" title="New reel" onClick={() => { setProjectId(null); setSelectedScene(null); setError('') }}><span>＋</span><span className="new-button-label">New reel</span></button>
      <div className="sidebar-label">YOUR PROJECTS</div>
      <div className="project-list">{projects.length ? projects.map(item => <button key={item.project_id} className={`project-item ${projectId === item.project_id ? 'active' : ''}`} title={item.topic} onClick={() => { setProjectId(item.project_id); setSelectedScene(null) }}><span className="project-icon">▣</span><span className="project-copy"><strong>{item.topic}</strong><small>{stageLabels[item.status] || item.status}</small></span></button>) : <div className="sidebar-empty"><div className="empty-folder" aria-hidden="true"><svg viewBox="0 0 32 32" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"><path d="M3 8.5a3 3 0 0 1 3-3h7l3.2 3.5H26a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3z" /></svg></div><strong>No reels yet.</strong><span>Start with a topic to<br />create your first reel.</span></div>}</div>
      <div className="sidebar-foot" title="Workspace ready"><span className="status-dot" /><span className="sidebar-foot-copy"><strong>Workspace ready</strong><small>All systems operational</small></span><span className="foot-arrow">›</span></div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div><div className="breadcrumb">Workspace <span>›</span> {snapshot ? 'Reel project' : 'New reel'}</div><h1>{snapshot ? snapshot.topic : 'Create a new reel'}</h1></div><div className="topbar-badges">{snapshot && <span className={`badge ${snapshot.mode === 'mock' ? 'mock' : ''}`}>{snapshot.mode.toUpperCase()}</span>}</div></header>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
      {!projectId ? <div className="creation-shell"><div className="new-workspace"><div className="hero-illustration" aria-hidden="true"><div className="illustration-card illustration-card-back"><i /><span /><span /></div><div className="illustration-card illustration-card-middle"><i /><span /><span /></div><div className="illustration-card illustration-card-front"><i>▷</i><span /><span /></div></div><div className="hero-icon">✦</div><span className="eyebrow">FROM QUESTION TO REEL</span><h2>What should we explain?</h2><p>Enter a topic. Research, dialogue, voice, and six editable scenes<br className="wide-only" /> will appear here as they finish.</p><form onSubmit={submitTopic}><div className="topic-label"><label htmlFor="topic">YOUR TOPIC</label><span>{topic.length}/1000</span></div><textarea id="topic" value={topic} onChange={event => setTopic(event.target.value)} minLength={5} maxLength={1000} rows={3} placeholder="How does … work?" /><button className="primary-button" disabled={busy || topic.trim().length < 5}><span aria-hidden="true">✦</span>{busy ? 'Creating…' : 'Create reel'} <span>→</span></button></form>{isFrontendMock && <p className="mock-hint"><span aria-hidden="true">ⓘ</span>Demo mode uses local fixture data and makes no API requests.</p>}</div></div> : loading && !snapshot ? <div className="center-state">Loading project…</div> : snapshot ? <>
        <div className="mobile-tabs"><button className={mobileTab === 'activity' ? 'active' : ''} onClick={() => setMobileTab('activity')}>Activity & dialogue</button><button className={mobileTab === 'scenes' ? 'active' : ''} onClick={() => setMobileTab('scenes')}>Scenes</button></div>
        <div className="content-grid"><section className={`activity-pane ${mobileTab === 'activity' ? 'mobile-active' : ''}`}><div className="section-heading"><div><span className="eyebrow">PROJECT ACTIVITY</span><h2>From idea to story</h2></div><span className="stage-pill"><span className="pulse-dot" />{stageLabels[snapshot.status] || snapshot.status}</span></div>
          <div className="activity-scroll">
            <div className="timeline-list">{events.length ? events.map(item => <div className="activity-event" key={item.event_id}><div className="event-node" /><div><small>{time(item.at)} · {item.type.replaceAll('.', ' / ')}</small><p>{item.message}</p></div></div>) : <div className="empty-card">Waiting for the first project update…</div>}</div>
            {snapshot.research && <div className="content-card research-card"><button className="card-toggle" onClick={() => setResearchOpen(value => !value)} aria-expanded={researchOpen}><span><span className="card-icon">⌕</span><strong>Research & sources</strong><small>{snapshot.research.sources.length} sources · {snapshot.research.claims.length} claims</small></span><span>{researchOpen ? '−' : '+'}</span></button><p>{snapshot.research.summary}</p>{researchOpen && <div className="research-body"><p>{snapshot.research.report_markdown}</p><div className="source-list">{snapshot.research.sources.map(source => <a key={source.source_id} href={source.url} target="_blank" rel="noreferrer"><span>{source.source_id}</span>{source.title}<span>↗</span></a>)}</div>{snapshot.research.uncertainties.map((value, i) => <small className="uncertainty" key={i}>{value}</small>)}</div>}</div>}
            {snapshot.script && <div className="dialogue-section"><div className="subheading"><span className="eyebrow">THE CONVERSATION</span><h3>{snapshot.script.title}</h3><p>12 turns · Sundar & Jensen</p></div>{snapshot.script.turns.slice().sort((a,b) => a.order-b.order).map(turn => { const audio = snapshot.audio?.utterances.find(item => item.dialogue_id === turn.dialogue_id); return <div className="dialogue-card" key={turn.dialogue_id}><div className={`avatar ${turn.speaker_id}`}>{turn.speaker_id === 'sundar' ? 'S' : 'J'}</div><div className="dialogue-copy"><div className="dialogue-meta"><strong>{names[turn.speaker_id]}</strong><span>SCENE {turn.scene_index} · {turn.dialogue_id}</span></div><p>{turn.text}</p>{audio && <details className="audio-details"><summary>Audio & word timing <span>{(audio.duration_ms/1000).toFixed(1)}s · {audio.words.length} words · {audio.timing_quality}</span></summary><audio controls preload="none" src={api.artifactUrl(audio.wav)} aria-label={`${names[turn.speaker_id]} audio ${turn.dialogue_id}`} /><div className="word-list">{audio.words.map(word => <span key={word.word_id} title={`${word.start_ms}–${word.end_ms} ms`}>{word.text}<small>{(word.start_ms/1000).toFixed(1)}s</small></span>)}</div><p className="transcript">Transcript: {audio.transcript}</p></details>}</div></div> })}</div>}
          </div><form className="composer" onSubmit={submitEdit}><div className="composer-target">{selected ? <>Editing <strong>Scene {selected.index}</strong> · revision {selected.current_revision}</> : 'Select a scene to target an edit, or name it in your message.'}{selectedScene && <button type="button" onClick={() => setSelectedScene(null)}>Clear selection</button>}</div><div className="composer-input"><textarea aria-label="Scene correction" value={message} onChange={event => setMessage(event.target.value)} placeholder="Ask for a change to one scene…" rows={2} disabled={!snapshot.timeline || busy || snapshot.status === 'rendering'} /><button type="submit" className="send-button" disabled={!snapshot.timeline || busy || !message.trim() || snapshot.status === 'rendering'} aria-label="Send correction">↗</button></div></form></section>
        <section className={`scenes-pane ${mobileTab === 'scenes' ? 'mobile-active' : ''}`}><div className="section-heading scenes-heading"><div><span className="eyebrow">VISUAL STORYBOARD</span><h2>Scenes <span>06</span></h2></div><span className="ready-count">{snapshot.scenes.filter(scene => scene.status === 'ready').length}/6 ready</span></div><div className="scenes-scroll">{snapshot.scenes.slice().sort((a,b) => a.index-b.index).map(scene => <SceneCard key={scene.scene_id} scene={scene} selected={selectedScene === scene.scene_id} onSelect={() => { setSelectedScene(scene.scene_id); setMobileTab('activity') }} onRetry={() => void retry('scenes', scene.scene_id)} busy={busy} api={api} />)}</div><div className="stitch-panel"><div className="stitch-copy"><strong>Final reel</strong><span>{snapshot.final_is_stale ? 'Your reel needs a new stitch after this edit.' : snapshot.final?.status === 'completed' ? isFrontendMock ? 'Mock placeholder video is ready.' : 'Your 60-second reel is ready.' : 'Combine all six scenes into one video.'}</span></div>{snapshot.final?.status === 'running' && <div className="render-progress"><div style={{ width: `${Math.round(snapshot.final.progress * 100)}%` }} /><span>Rendering {Math.round(snapshot.final.progress * 100)}%</span></div>}{snapshot.final?.status === 'completed' && snapshot.final.video && !snapshot.final_is_stale && <a className="download-button" href={api.artifactUrl(snapshot.final.video)} download="nebius-reel.mp4">↓ Download MP4</a>}{snapshot.final?.status === 'failed' && <p className="mini-error">{snapshot.final.error?.message}</p>}<button className="primary-button stitch-button" disabled={!canStitch} onClick={() => void stitch()}>{snapshot.final_is_stale ? 'Stitch latest scenes' : snapshot.final?.status === 'completed' ? 'Stitched' : snapshot.status === 'rendering' ? 'Rendering…' : 'Stitch reel'} <span>✦</span></button></div></section></div>
        {snapshot.error && <div className="floating-failure"><span>{snapshot.error.message}</span>{snapshot.error.retryable && <button onClick={() => { const stage = retryStage(snapshot); void retry(stage, stage === 'scenes' ? snapshot.error?.scene_id || undefined : undefined) }}>Retry stage</button>}</div>}
      </> : <div className="center-state">Project unavailable. Choose another reel or create a new one.</div>}
    </main>
  </div>
}

function SceneCard({ scene, selected, onSelect, onRetry, busy, api }: { scene: SceneState; selected: boolean; onSelect: () => void; onRetry: () => void; busy: boolean; api: EditorApi }) {
  const preview = scene.preview?.status === 'completed' ? scene.preview : null
  const inProgress = scene.status === 'generating' || scene.status === 'rendering'
  return <article className={`scene-card ${selected ? 'selected' : ''}`}><div className="scene-top"><button className="scene-select" onClick={onSelect} aria-pressed={selected}><span className="scene-number">{String(scene.index).padStart(2, '0')}</span><span><strong>{scene.build?.summary || `Scene ${scene.index}`}</strong><small>{scene.slot ? `${((scene.slot.end_frame-scene.slot.start_frame)/30).toFixed(1)}s` : 'Awaiting timeline'} · revision {scene.current_revision || '—'}</small></span></button><span className={`scene-status ${scene.status}`}>{scene.status}</span></div><div className="preview-shell">{preview?.video ? <video key={preview.video.key} controls preload="none" poster={preview.poster ? api.artifactUrl(preview.poster) : undefined} src={api.artifactUrl(preview.video)} aria-label={`Scene ${scene.index} preview`} /> : <div className="preview-placeholder"><span>✦</span><small>{scene.status === 'pending' ? 'Waiting for scene' : scene.status === 'failed' ? 'Preview failed' : 'Creating preview'}</small></div>}{inProgress && <div className="preview-progress"><div style={{ width: `${Math.round(scene.progress*100)}%` }} /></div>}</div>{scene.error && <div className="scene-error">{scene.error.message}{scene.status === 'failed' && scene.error.retryable && <button onClick={onRetry} disabled={busy}>Retry</button>}</div>}{selected && <div className="selected-hint">Selected for your next correction</div>}</article>
}
