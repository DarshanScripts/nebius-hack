import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const origin = process.env.SMOKE_URL || 'http://127.0.0.1:5173'
const browser = await chromium.launch({ channel: process.env.SMOKE_BROWSER || 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const projectId = 'api-smoke-project'
const topic = 'How does WhatsApp voice calling infrastructure work?'
const now = new Date().toISOString()
const scenes = Array.from({ length: 6 }, (_, index) => ({
  scene_id: `s${String(index + 1).padStart(2, '0')}`,
  index: index + 1,
  slot: null,
  status: 'pending',
  current_revision: 0,
  requested_revision: 1,
  active_job_id: null,
  progress: 0,
  build: null,
  preview: null,
  error: null,
}))
const research = {
  schema_version: '1.0', project_id: projectId, topic, tavily_request_id: 'fixture-request',
  summary: 'HTTP fixture research arrived after project creation.', report_markdown: 'Fixture report.',
  sources: [{ source_id: 'src001', title: 'Fixture source', url: 'https://example.com/fixture', favicon: null }],
  claims: [], uncertainties: [],
  raw_response: { key: `projects/${projectId}/research/raw.json`, media_type: 'application/json', sha256: '0'.repeat(64), size_bytes: 0 },
  is_mock: true,
}
const snapshot = ready => ({
  schema_version: '1.0', project_id: projectId, topic, project_revision: 1, mode: 'mock',
  status: ready ? 'scripting' : 'researching', created_at: now, updated_at: now, active_job_id: 'fixture-job',
  research: ready ? research : null, script: null, images: null, audio: null, timeline: null,
  scenes, final: null, final_project_revision: null, final_is_stale: false, error: null,
})
let created = false
let projectReads = 0
const requests = []
let showFailure = false
let delayedRead = false
let releaseRead
const readGate = new Promise(resolve => { releaseRead = resolve })
await mkdir('.artifacts', { recursive: true })

// Vite dev also serves /src/api/*.ts modules; only intercept backend routes.
await page.route(/\/api\/(?:projects|health|artifacts)(?:\/|\?|$)/, async route => {
  const request = route.request()
  const url = new URL(request.url())
  const path = url.pathname
  requests.push(`${request.method()} ${path}`)
  const reply = (status, body) => route.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(body) })
  if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'content-type' } })
  if (path === '/api/projects' && request.method() === 'GET') return reply(200, { projects: created ? [{ schema_version: '1.0', project_id: projectId, topic, status: 'scripting', updated_at: now, mode: 'mock' }] : [] })
  if (path === '/api/projects' && request.method() === 'POST') {
    assert.deepEqual(request.postDataJSON(), { topic, language: 'en' })
    created = true
    return reply(202, snapshot(false))
  }
  if (path === `/api/projects/${projectId}` && request.method() === 'GET') {
    if (delayedRead) await readGate
    const next = snapshot(++projectReads >= 2)
    if (showFailure) Object.assign(next, {
      status: 'failed', active_job_id: null,
      error: { code: 'LLM_UNAVAILABLE', stage: 'dialogue', message: 'The dialogue service is taking a little longer. Please try again.', retryable: true, scene_id: null },
    })
    return reply(200, next)
  }
  if (path === `/api/projects/${projectId}/retry` && request.method() === 'POST') {
    assert.deepEqual(request.postDataJSON(), { stage: 'dialogue' })
    showFailure = false
    return reply(202, snapshot(true))
  }
  if (path === `/api/projects/${projectId}/events` && request.method() === 'GET') {
    const after = Number(url.searchParams.get('after'))
    return reply(200, { events: after ? [] : [{ schema_version: '1.0', project_id: projectId, event_id: 1, at: now, type: 'research.ready', scene_id: null, revision: null, message: 'Research ready', progress: null }], next_after: 1 })
  }
  return reply(404, { error: { code: 'NOT_FOUND', stage: 'api', message: path, retryable: false, scene_id: null } })
})

try {
  await page.goto(origin)
  assert.equal(await page.locator('.demo-mode-banner').count(), 0)
  await page.getByLabel('Your topic').fill(topic)
  await page.getByRole('button', { name: 'Create reel' }).click()
  await page.getByText('HTTP fixture research arrived after project creation.').waitFor({ timeout: 10000 })
  assert.equal(await page.locator('.scene-card').count(), 6)
  await page.reload()
  await page.getByText('HTTP fixture research arrived after project creation.').waitFor({ timeout: 10000 })
  assert.equal(await page.getByText('Research ready').count(), 1)
  assert.ok(requests.includes('POST /api/projects'))
  assert.ok(requests.includes(`GET /api/projects/${projectId}`))
  assert.ok(requests.includes(`GET /api/projects/${projectId}/events`))
  // The loading and recoverable error surfaces use the same theme as the editor.
  delayedRead = true
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: 'Opening your story…' }).waitFor()
  await page.screenshot({ path: '.artifacts/theme-loading.png' })
  delayedRead = false
  releaseRead()
  await page.getByText('HTTP fixture research arrived after project creation.').waitFor()
  showFailure = true
  await page.reload()
  await page.getByRole('button', { name: 'Retry stage' }).waitFor()
  await page.screenshot({ path: '.artifacts/theme-stage-error.png' })
  await page.getByRole('button', { name: 'Retry stage' }).click()
  await page.getByRole('button', { name: 'Retry stage' }).waitFor({ state: 'hidden' })
  assert.ok(requests.includes(`POST /api/projects/${projectId}/retry`))
  console.log(JSON.stringify({ http_create: true, progressive_snapshot: true, refresh_restored: true, event_deduplicated: true, scene_slots: 6, loading_state: true, stage_error_retry: true }))
} finally {
  await browser.close()
}
