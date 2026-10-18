import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, liveApi } from './api/client'
import { mockApi } from './api/mock'
import { BrandMark, Icon } from './components/Icon'
import { NewReel } from './components/NewReel'
import type { EditorApi } from './api/client'
import type { ProjectEvent, ProjectSnapshot, ProjectSummary, RetryStage, SceneState } from './types/contracts'

const isFrontendMock = new URLSearchParams(window.location.search).get('mock') === '1'
const api: EditorApi = isFrontendMock ? mockApi : liveApi
const selectionKey = `nebius-selected-project-${isFrontendMock ? 'frontend-mock' : 'api'}`
const names = { sundar: 'Sundar Pichai', jensen: 'Jensen Huang' }
const stageLabels: Record<string, string> = {
  created: 'Starting', researching: 'Researching', scripting: 'Writing dialogue', finding_images: 'Finding visuals',
  voicing: 'Creating voice', planning: 'Planning timeline', generating_scenes: 'Generating scenes',
  ready: 'Ready to stitch', rendering: 'Rendering final', completed: 'Complete', failed: 'Needs attention',
}
const retryStage = (snapshot: ProjectSnapshot): RetryStage => {
  if (snapshot.final?.status === 'failed') return 'final'
  if (snapshot.timeline && snapshot.error?.scene_id) return 'scenes'
  if (!snapshot.research) return 'research'
  if (!snapshot.script) return 'dialogue'
  if (!snapshot.images) return 'images'
  if (!snapshot.audio) return 'voice'
  return 'scenes'
}
const messageOf = (error: unknown) => error instanceof ApiError
  ? error.status === 409 ? `${error.message} Refreshing project state…` : error.message
  : error instanceof Error ? error.message : 'Something went wrong'
const time = (date: string) => new Date(date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const isActive = (project: ProjectSnapshot) => Boolean(project.active_job_id || project.scenes.some(scene => scene.active_job_id) || project.final?.status === 'queued' || project.final?.status === 'running')

export function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectId, setProjectId] = useState<string | null>(() => localStorage.getItem(selectionKey))
  const [view, setView] = useState<'overview' | 'new' | 'reel'>(() => localStorage.getItem(selectionKey) ? 'reel' : 'new')
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null)
  const [events, setEvents] = useState<ProjectEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [topic, setTopic] = useState('')
  const [message, setMessage] = useState('')
  const [selectedScene, setSelectedScene] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [researchOpen, setResearchOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState<'activity' | 'scenes'>('activity')
  const [theme, setTheme] = useState<'dark' | 'light'>(() => localStorage.getItem('researchreel-theme') === 'light' ? 'light' : 'dark')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'progress' | 'complete'>('all')
  const help = useRef<HTMLDialogElement>(null)
  const cursor = useRef(0)
  const generation = useRef(0)
  const inFlight = useRef<number | null>(null)
  const nextPollAt = useRef(0)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('researchreel-theme', theme)
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#080b0f' : '#f5f6f8')
  }, [theme])

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
    } catch (reason) {
      if (generation.current === requestGeneration) { setError(messageOf(reason)); nextPollAt.current = Date.now() + 5000 }
    } finally {
      if (inFlight.current === requestGeneration) inFlight.current = null
      if (generation.current === requestGeneration) setLoading(false)
    }
  }, [])

  useEffect(() => { refreshList().catch(reason => { setError(messageOf(reason)); setLoading(false) }) }, [refreshList])
  useEffect(() => {
    const current = ++generation.current
    nextPollAt.current = 0
    cursor.current = 0
    setEvents([])
    setSnapshot(null)
    setResearchOpen(false)
    setLoading(Boolean(projectId))
    if (!projectId) { localStorage.removeItem(selectionKey); return }
    localStorage.setItem(selectionKey, projectId)
    void refresh(projectId, current)
    const timer = window.setInterval(() => { if (Date.now() >= nextPollAt.current) void refresh(projectId, current) }, 1000)
    return () => window.clearInterval(timer)
  }, [projectId, refresh])

  const applyResponse = (next: ProjectSnapshot) => {
    setSnapshot(next)
    setView('reel')
    nextPollAt.current = 0
    if (projectId !== next.project_id) setProjectId(next.project_id)
    void refreshList().catch(reason => setError(messageOf(reason)))
  }
  const submitTopic = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy || topic.trim().length < 5) return
    setBusy(true); setError('')
    const requestGeneration = generation.current
    try {
      const next = await api.createProject({ topic: topic.trim(), language: 'en' })
      if (generation.current === requestGeneration) { setMobileTab('activity'); applyResponse(next) }
    } catch (reason) { if (generation.current === requestGeneration) setError(messageOf(reason)) }
    finally { setBusy(false) }
  }
  const submitEdit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!snapshot || !message.trim()) return
    setBusy(true); setError('')
    const requestGeneration = generation.current
    try {
      const scene = snapshot.scenes.find(item => item.scene_id === selectedScene)
      const next = await api.editProject(snapshot.project_id, {
        message: message.trim(), ...(scene ? { scene_id: scene.scene_id, expected_scene_revision: scene.current_revision } : {}),
      })
      if (generation.current === requestGeneration) { applyResponse(next); setMessage('') }
    } catch (reason) {
      if (generation.current === requestGeneration) { setError(messageOf(reason)); if (reason instanceof ApiError && reason.status === 409) void refresh(snapshot.project_id, requestGeneration) }
    } finally { setBusy(false) }
  }
  const stitch = async () => {
    if (!snapshot) return
    setBusy(true); setError('')
    const requestGeneration = generation.current
    try { const next = await api.stitchProject(snapshot.project_id); if (generation.current === requestGeneration) applyResponse(next) }
    catch (reason) {
      if (generation.current === requestGeneration) { setError(messageOf(reason)); if (reason instanceof ApiError && reason.status === 409) void refresh(snapshot.project_id, requestGeneration) }
    } finally { setBusy(false) }
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
  const showNew = () => { setProjectId(null); setView('new'); setSelectedScene(null); setError('') }
  const openProject = (id: string, tab: 'activity' | 'scenes' = 'activity') => {
    setProjectId(id); setView('reel'); setMobileTab(tab); setSelectedScene(null); setError('')
  }
  const openCurrentReel = () => { const id = projectId || projects[0]?.project_id; if (id) openProject(id, 'scenes') }
  const visibleProjects = projects.filter(item =>
    item.topic.toLowerCase().includes(search.toLowerCase()) &&
    (filter === 'all' || (filter === 'complete' ? item.status === 'completed' : item.status !== 'completed')),
  )

  return <div className={`app-shell view-${view}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="app-header">
      <button className="brand" onClick={showNew} aria-label="ResearchReel home"><BrandMark /><span>ResearchReel</span></button>
      <nav className="header-actions" aria-label="Main navigation">
        <button className={`nav-projects ${view === 'overview' ? 'active' : ''}`} onClick={() => setView('overview')} aria-current={view === 'overview' ? 'page' : undefined}>Projects <span>{projects.length ? String(projects.length).padStart(2, '0') : ''}</span></button>
        <div className="header-divider" />
        <div className="theme-switch" role="group" aria-label="Color theme">
          <button aria-label="Light theme" aria-pressed={theme === 'light'} onClick={() => setTheme('light')} title="Light theme"><Icon name="sun" size={16} /></button>
          <button aria-label="Dark theme" aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')} title="Dark theme"><Icon name="moon" size={15} /></button>
        </div>
        <button className="help-button icon-button" aria-label="How ResearchReel works" onClick={() => help.current?.showModal()}><Icon name="help" size={21} /></button>
      </nav>
    </header>

    <div className={`workspace ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
      {view !== 'new' && <aside className="sidebar" aria-label="Reel projects">
        <div className="sidebar-heading"><span className="eyebrow">Your workspace</span><button className="sidebar-toggle icon-button" onClick={() => setSidebarOpen(value => !value)} aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'} title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}><Icon name="panel" size={18} /></button></div>
        <button className="new-button" aria-label="New reel" title="New reel" onClick={showNew}><Icon name="plus" size={18} /><span className="new-button-label">New reel</span><Icon name="diagonal" size={15} /></button>
        <nav className={sidebarOpen ? 'sidebar-nav' : 'sidebar-rail-nav'} aria-label="Workspace navigation">
          <button className={`rail-item ${view === 'overview' ? 'active' : ''}`} aria-label="Project overview" aria-current={view === 'overview' ? 'page' : undefined} onClick={() => setView('overview')} title="Project overview"><Icon name="grid" size={18} /><span>All projects</span><small>{projects.length}</small></button>
          <button className={`rail-item ${view === 'reel' ? 'active' : ''}`} aria-label="Current reel" disabled={!projects.length} onClick={openCurrentReel} title="Current reel"><Icon name="film" size={18} /><span>Current reel</span></button>
        </nav>
        <div className="sidebar-label">Recent projects <span>{String(projects.length).padStart(2, '0')}</span></div>
        <div className="project-list">
          {projects.length ? projects.map(item => <button key={item.project_id}
            className={`project-item ${projectId === item.project_id && view === 'reel' ? 'active' : ''}`}
            title={item.topic} aria-label={item.topic} onClick={() => openProject(item.project_id)}>
            <span className="project-icon"><Icon name="film" size={16} /></span>
            <span className="project-copy"><strong>{item.topic}</strong><small><i className={`project-dot ${item.status}`} />{stageLabels[item.status] || item.status}</small></span>
          </button>) : <div className="sidebar-empty"><Icon name="film" size={28} /><p>Your next story<br />starts with a question.</p></div>}
        </div>
        <div className="sidebar-foot"><span className="status-dot" /><span className="sidebar-foot-copy"><strong>{isFrontendMock ? 'Demo workspace' : 'ResearchReel studio'}</strong><small>{isFrontendMock ? 'Explore with sample content' : 'Made for curious minds'}</small></span></div>
      </aside>}

      <main id="main-content" className="main-panel">
        {error && <div className="error-banner" role="alert"><Icon name="help" size={18} /><span>{error}</span><button className="icon-button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={18} /></button></div>}
        {view === 'new' ? <NewReel topic={topic} onTopic={setTopic} onSubmit={submitTopic} busy={busy} mock={isFrontendMock} />
          : view === 'overview' ? <section className="overview-shell">
            <div className="overview-head"><div><span className="eyebrow">Your collection</span><h1>Ideas in motion<span>.</span></h1><p>A home for your questions. A canvas for your stories.</p></div><button className="primary-button" onClick={showNew}><Icon name="plus" size={18} />New reel</button></div>
            <div className="library-toolbar">
              <div className="library-filters" role="group" aria-label="Filter projects">
                {(['all', 'progress', 'complete'] as const).map(value => <button key={value} onClick={() => setFilter(value)} aria-pressed={filter === value}>{value === 'all' ? 'All projects' : value === 'progress' ? 'In progress' : 'Completed'}{value === 'all' && <span>{projects.length}</span>}</button>)}
              </div>
              <label className="library-search"><Icon name="search" size={16} /><input aria-label="Search projects" placeholder="Find a story…" value={search} onChange={event => setSearch(event.target.value)} /></label>
            </div>
            {visibleProjects.length ? <div className="overview-grid">
              {visibleProjects.map((item, index) => <button key={item.project_id} className="overview-project" onClick={() => openProject(item.project_id)}>
                <div className={`project-art art-${index % 3}`} aria-hidden="true"><span className="art-orbit" /><span className="art-core" /><span className="art-number">{String(index + 1).padStart(2, '0')}</span><Icon name="diagonal" /></div>
                <div className="overview-project-copy"><span className={`project-state ${item.status}`}><i />{stageLabels[item.status] || item.status}</span><h2>{item.topic}</h2><div className="project-card-footer"><span>{new Date(item.updated_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}</span><span>{item.mode === 'mock' ? 'Demo' : 'Film'}<Icon name="arrow" size={16} /></span></div></div>
              </button>)}
              <button className="new-project-card" onClick={showNew}><span><Icon name="plus" size={24} /></span><strong>The next great question?</strong><small>Make something worth sharing.</small></button>
            </div> : <div className="overview-empty"><span className="empty-orbit"><Icon name={projects.length ? 'search' : 'film'} size={30} /></span><h2>{projects.length ? 'No stories found.' : 'Every great film starts somewhere.'}</h2><p>{projects.length ? 'Try a different search or filter.' : 'Bring a question. We’ll help you tell its story.'}</p><button className="primary-button" onClick={projects.length ? () => { setSearch(''); setFilter('all') } : showNew}>{projects.length ? 'Clear filters' : 'Create your first reel'}<Icon name="arrow" size={18} /></button></div>}
            <footer className="library-footer"><span>Research. Narration. Film.</span><span>Made for the stories worth telling.</span></footer>
          </section>
          : loading && !snapshot ? <div className="center-state" role="status"><span className="loading-orbit" /><h2>Opening your story…</h2><p>Picking up where you left off.</p></div>
          : snapshot ? <>
            <header className="topbar">
              <div className="project-heading"><div className="breadcrumb"><button onClick={() => setView('overview')}>Projects</button><Icon name="chevron" size={12} /><span>Film workspace</span></div><h1 title={snapshot.topic}>{snapshot.topic}</h1></div>
              <div className="topbar-badges"><span className={`badge ${snapshot.mode === 'mock' ? 'mock' : ''}`}>{snapshot.mode === 'mock' ? 'Demo' : 'Live'}</span><span className="format-badge">9:16 <i /> 60 sec</span></div>
            </header>
            <div className="pipeline-strip" aria-label="Film production stages">
              {[
                ['Research', Boolean(snapshot.research)], ['Dialogue', Boolean(snapshot.script)], ['Voice', Boolean(snapshot.audio)],
                ['Scenes', allReady], ['Film', snapshot.final?.status === 'completed' && !snapshot.final_is_stale],
              ].map(([label, done], i, list) => {
                const current = !done && list.slice(0, i).every(item => item[1])
                return <div key={String(label)} className={`pipeline-step ${done ? 'done' : ''} ${current ? 'current' : ''}`}><span>{done ? <Icon name="check" size={12} /> : String(i + 1).padStart(2, '0')}</span>{label}</div>
              })}
              <span className="pipeline-state" role="status"><i className={isActive(snapshot) ? 'working' : ''} />{stageLabels[snapshot.status]}</span>
            </div>
            <div className="mobile-tabs"><button className={mobileTab === 'activity' ? 'active' : ''} onClick={() => setMobileTab('activity')}>Activity & dialogue</button><button className={mobileTab === 'scenes' ? 'active' : ''} onClick={() => setMobileTab('scenes')}>Scenes</button></div>
            <div className="content-grid">
              <section className={`activity-pane ${mobileTab === 'activity' ? 'mobile-active' : ''}`} aria-label="Research and dialogue">
                <div className="section-heading"><div><span className="eyebrow">The narrative</span><h2>From idea to story</h2></div><Icon name="book" size={20} /></div>
                <div className="activity-scroll">
                  <details className="activity-log"><summary><span><span className={`status-dot ${isActive(snapshot) ? 'working' : ''}`} />Activity <small>{events.length} updates</small></span><Icon name="chevron" size={14} /></summary>
                    <div className="timeline-list">{events.length ? events.map(item => <div className="activity-event" key={item.event_id}><div className="event-node" /><div><small>{time(item.at)} · {item.type.replaceAll('.', ' / ')}</small><p>{item.message}</p></div></div>) : <p className="empty-card">Waiting for the first project update…</p>}</div>
                  </details>
                  {snapshot.research ? <div className="content-card research-card">
                    <button className="card-toggle" onClick={() => setResearchOpen(value => !value)} aria-expanded={researchOpen}><span><span className="card-icon"><Icon name="search" size={18} /></span><span><strong>Research & sources</strong><small>{snapshot.research.sources.length} sources · {snapshot.research.claims.length} grounded claims</small></span></span><Icon name={researchOpen ? 'close' : 'plus'} size={16} /></button>
                    <p>{snapshot.research.summary}</p>
                    {researchOpen && <div className="research-body"><p>{snapshot.research.report_markdown}</p><div className="source-list">{snapshot.research.sources.map(source => <a key={source.source_id} href={source.url} target="_blank" rel="noreferrer"><span>{source.source_id}</span>{source.title}<Icon name="diagonal" size={14} /></a>)}</div>{snapshot.research.uncertainties.map((value, i) => <small className="uncertainty" key={i}>{value}</small>)}</div>}
                  </div> : <div className="research-waiting"><Icon name="search" size={24} /><h3>Following your curiosity.</h3><p>Research and sources will appear here as your story takes shape.</p><div className="skeleton-line" /><div className="skeleton-line short" /></div>}
                  {snapshot.script && <div className="dialogue-section">
                    <div className="subheading"><span className="eyebrow">The conversation</span><h3>{snapshot.script.title}</h3><p><span className="mini-avatars"><i>S</i><i>J</i></span>12 turns · Sundar & Jensen</p></div>
                    {snapshot.script.turns.slice().sort((a, b) => a.order - b.order).map(turn => {
                      const audio = snapshot.audio?.utterances.find(item => item.dialogue_id === turn.dialogue_id)
                      return <div className="dialogue-card" key={turn.dialogue_id}>
                        <div className={`avatar ${turn.speaker_id}`}>{turn.speaker_id === 'sundar' ? 'S' : 'J'}</div>
                        <div className="dialogue-copy"><div className="dialogue-meta"><strong>{names[turn.speaker_id]}</strong><span>Scene {String(turn.scene_index).padStart(2, '0')}</span></div><p>{turn.text}</p>
                          {audio && <details className="audio-details"><summary><span><Icon name="audio" size={15} />Audio & word timing</span><span>{(audio.duration_ms / 1000).toFixed(1)}s<Icon name="chevron" size={12} /></span></summary>
                            <audio controls preload="none" src={api.artifactUrl(audio.wav)} aria-label={`${names[turn.speaker_id]} audio ${turn.dialogue_id}`} />
                            <p className="timing-note">{audio.words.length} words · {audio.timing_quality === 'mock' ? 'Demo timing' : 'Aligned to speech'}</p>
                            <div className="word-list">{audio.words.map(word => <span key={word.word_id} title={`${word.start_ms}–${word.end_ms} ms`}>{word.text}<small>{(word.start_ms / 1000).toFixed(1)}s</small></span>)}</div><p className="transcript">Transcript: {audio.transcript}</p>
                          </details>}
                        </div>
                      </div>
                    })}
                  </div>}
                </div>
                <form className="composer" onSubmit={submitEdit}>
                  <div className="composer-target"><span>{selected ? <>Refining <strong>Scene {selected.index}</strong><span className="revision-label">v{selected.current_revision}</span></> : 'Your story. Your direction.'}</span>{selectedScene && <button type="button" onClick={() => setSelectedScene(null)}>Clear selection</button>}</div>
                  <div className="composer-input"><textarea aria-label="Scene correction" value={message} onChange={event => setMessage(event.target.value)} placeholder={selected ? `What would you change about scene ${selected.index}?` : 'Choose a scene and tell us what to change…'} rows={2} disabled={!snapshot.timeline || busy || snapshot.status === 'rendering'} /><button type="submit" className="send-button" disabled={!snapshot.timeline || busy || !message.trim() || snapshot.status === 'rendering'} aria-label="Send correction"><Icon name="arrow" size={19} /></button></div>
                  <span className="composer-note">A fresh take on one scene. The rest of your story stays yours.</span>
                </form>
              </section>
              <section className={`scenes-pane ${mobileTab === 'scenes' ? 'mobile-active' : ''}`} aria-label="Scene storyboard">
                <div className="section-heading scenes-heading"><div><span className="eyebrow">The visual story</span><h2>Storyboard <span>06</span></h2></div><span className="ready-count">{snapshot.scenes.filter(scene => scene.status === 'ready').length}/6 ready</span></div>
                <div className="scenes-scroll">{snapshot.scenes.slice().sort((a, b) => a.index - b.index).map(scene => <SceneCard key={scene.scene_id} scene={scene} selected={selectedScene === scene.scene_id} onSelect={() => { setSelectedScene(scene.scene_id); setMobileTab('activity') }} onRetry={() => void retry('scenes', scene.scene_id)} busy={busy} api={api} />)}</div>
                <div className="stitch-panel">
                  <div className="stitch-copy"><span className="stitch-icon"><Icon name="film" /></span><div><strong>Your final film</strong><span>{snapshot.final_is_stale ? 'A new take is ready to stitch.' : snapshot.final?.status === 'completed' ? snapshot.mode === 'mock' ? 'Your demo film is ready.' : 'Your 60-second story is ready.' : 'Six scenes. One seamless story.'}</span></div><span className="film-duration">60s</span></div>
                  {(snapshot.final?.status === 'running' || snapshot.final?.status === 'queued') && <div className="render-progress" role="progressbar" aria-label="Final render" aria-valuenow={Math.round(snapshot.final.progress * 100)} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${Math.round(snapshot.final.progress * 100)}%` }} /><span>Rendering {Math.round(snapshot.final.progress * 100)}%</span></div>}
                  {snapshot.final?.status === 'completed' && snapshot.final.video && !snapshot.final_is_stale && <a className="download-button" href={api.artifactUrl(snapshot.final.video)} download="researchreel.mp4"><Icon name="download" size={18} />Download MP4<Icon name="diagonal" size={15} /></a>}
                  {snapshot.final?.status === 'failed' && <p className="mini-error">{snapshot.final.error?.message}</p>}
                  {!(snapshot.final?.status === 'completed' && !snapshot.final_is_stale) && <button className="primary-button stitch-button" disabled={!canStitch} onClick={() => void stitch()}>{snapshot.final_is_stale ? 'Stitch latest scenes' : snapshot.status === 'rendering' ? 'Rendering…' : 'Stitch reel'}<Icon name="spark" size={17} /></button>}
                </div>
              </section>
            </div>
            {snapshot.error && <div className="floating-failure" role="alert"><Icon name="help" size={18} /><span>{snapshot.error.message}</span>{snapshot.error.retryable && <button disabled={busy} onClick={() => { const stage = retryStage(snapshot); void retry(stage, stage === 'scenes' ? snapshot.error?.scene_id || undefined : undefined) }}>Retry stage <Icon name="arrow" size={14} /></button>}</div>}
          </> : <div className="center-state"><Icon name="film" size={32} /><h2>Let’s find your story.</h2><p>This project isn’t available. Open another or start something new.</p><button className="primary-button" onClick={() => setView('overview')}>Back to projects <Icon name="arrow" size={18} /></button></div>}
      </main>
    </div>
    <dialog ref={help} className="help-dialog" aria-labelledby="guide-title" onClick={event => { if (event.target === help.current) help.current.close() }}>
      <button className="dialog-close icon-button" aria-label="Close guide" onClick={() => help.current?.close()}><Icon name="close" /></button>
      <div className="dialog-copy"><span className="eyebrow">From curiosity to cinema</span><h2 id="guide-title">A question.<br />A whole new perspective.</h2><p>ResearchReel turns your curiosity into a one-minute educational film.</p>
        <ol className="guide-steps"><li><Icon name="search" /><div><strong>Find the story</strong><span>Start with a topic. Explore the research and sources behind it.</span></div></li><li><Icon name="audio" /><div><strong>Give it a voice</strong><span>Follow the conversation, narration, and word timing.</span></div></li><li><Icon name="film" /><div><strong>Make it yours</strong><span>Select a scene to refine it. Stitch all six when you’re ready.</span></div></li></ol>
        <button className="primary-button" onClick={() => help.current?.close()}>Got it <Icon name="arrow" size={18} /></button>
      </div>
    </dialog>
  </div>
}

function SceneCard({ scene, selected, onSelect, onRetry, busy, api }: {
  scene: SceneState; selected: boolean; onSelect: () => void; onRetry: () => void; busy: boolean; api: EditorApi
}) {
  const preview = scene.preview?.status === 'completed' ? scene.preview : null
  const inProgress = scene.status === 'generating' || scene.status === 'rendering'
  return <article className={`scene-card ${selected ? 'selected' : ''}`}>
    <div className="scene-top">
      <button className="scene-select" onClick={onSelect} aria-pressed={selected}>
        <span className="scene-number">{String(scene.index).padStart(2, '0')}</span><span><strong>{scene.build?.summary || `Scene ${scene.index}`}</strong><small>{scene.slot ? `${((scene.slot.end_frame - scene.slot.start_frame) / 30).toFixed(1)}s` : 'Awaiting timeline'}<i />{scene.current_revision ? `Version ${scene.current_revision}` : 'Finding its shape'}</small></span>
      </button>
      <span className={`scene-status ${scene.status}`} title={scene.status}><i />{scene.status === 'ready' ? <><Icon name="check" size={13} /><span className="sr-only">Ready</span></> : scene.status}</span>
    </div>
    <div className="preview-shell">
      {preview?.video ? <video key={preview.video.key} controls playsInline preload="none" poster={preview.poster ? api.artifactUrl(preview.poster) : undefined} src={api.artifactUrl(preview.video)} aria-label={`Scene ${scene.index} preview`} /> : <div className={`preview-placeholder ${inProgress ? 'in-progress' : ''}`}><span className="placeholder-orbit"><Icon name={scene.status === 'failed' ? 'help' : 'spark'} size={22} /></span><small>{scene.status === 'pending' ? 'A story waiting to unfold' : scene.status === 'failed' ? 'This scene needs another take' : 'Bringing your idea to life'}</small></div>}
      {inProgress && <div className="preview-progress" role="progressbar" aria-label={`Scene ${scene.index} progress`} aria-valuenow={Math.round(scene.progress * 100)} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${Math.round(scene.progress * 100)}%` }} /></div>}
    </div>
    {scene.error && <div className="scene-error">{scene.error.message}{scene.status === 'failed' && scene.error.retryable && <button onClick={onRetry} disabled={busy}>Retry <Icon name="arrow" size={14} /></button>}</div>}
    {selected && <div className="selected-hint"><Icon name="check" size={13} />Selected for your next correction</div>}
  </article>
}
