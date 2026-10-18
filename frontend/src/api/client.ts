import type { ArtifactRef, EditRequest, EventPage, PipelineError, ProjectCreate, ProjectSnapshot, ProjectSummary, RetryStage } from '../types/contracts'

export interface EditorApi {
  listProjects(): Promise<ProjectSummary[]>
  createProject(input: ProjectCreate): Promise<ProjectSnapshot>
  getProject(id: string): Promise<ProjectSnapshot>
  getEvents(id: string, after: number): Promise<EventPage>
  editProject(id: string, input: EditRequest): Promise<ProjectSnapshot>
  retryProject(id: string, stage: RetryStage, sceneId?: string): Promise<ProjectSnapshot>
  stitchProject(id: string): Promise<ProjectSnapshot>
  artifactUrl(ref: ArtifactRef): string
}

export class ApiError extends Error {
  constructor(public status: number, public detail: PipelineError) { super(detail.message) }
}

const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
const endpoint = (path: string) => `${base}/api${path}`
const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(endpoint(path), {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  })
  if (!response.ok) {
    let detail: PipelineError = { code: 'HTTP_ERROR', stage: 'api', message: `Request failed (${response.status})`, retryable: response.status >= 500, scene_id: null }
    try { detail = (await response.json() as { error: PipelineError }).error || detail } catch { /* invalid error body */ }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export const liveApi: EditorApi = {
  async listProjects() { return (await request<{ projects: ProjectSummary[] }>('/projects')).projects },
  createProject: input => request('/projects', { method: 'POST', body: JSON.stringify(input) }),
  getProject: id => request(projectPath(id)),
  getEvents: (id, after) => request(`${projectPath(id)}/events?after=${after}`),
  editProject: (id, input) => request(`${projectPath(id)}/edits`, { method: 'POST', body: JSON.stringify(input) }),
  retryProject: (id, stage, sceneId) => request(`${projectPath(id)}/retry`, { method: 'POST', body: JSON.stringify({ stage, ...(sceneId ? { scene_id: sceneId } : {}) }) }),
  stitchProject: id => request(`${projectPath(id)}/stitch`, { method: 'POST', body: '{}' }),
  artifactUrl: ref => endpoint(`/artifacts/${ref.key.split('/').map(encodeURIComponent).join('/')}`),
}
