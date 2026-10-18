// Internal render worker (plan.md section 8): POST /jobs, GET /jobs/{id},
// POST /validate, GET /health. Bounded FIFO queue; encoding never runs in a
// request handler.
import http from 'node:http';
import fs from 'node:fs/promises';
import {timingSafeEqual} from 'node:crypto';
import {InputError, artifactRoot, resolveKey, sha256File} from './artifacts';
import {JOB_ID_RE, checkRequest, executeJob, loadCompleted, newRecord, requestHash, runChild, workDir, type JobRecord} from './jobs';
import type {PreviewRequest, RenderJobRequest, SourceValidationResult} from './types/contracts';

const PORT = Number(process.env.RENDER_WORKER_PORT ?? 8001);
const HOST = process.env.RENDER_WORKER_HOST ?? '0.0.0.0';
const TOKEN = process.env.RENDER_WORKER_TOKEN ?? '';
const CONCURRENCY = Math.max(1, Number(process.env.RENDER_CONCURRENCY ?? 1));
const MAX_QUEUE = Number(process.env.RENDER_MAX_QUEUE ?? 32);
const MAX_BODY = 32 * 1024 * 1024;
const VALIDATE_TIMEOUT_MS = Number(process.env.RENDER_VALIDATE_TIMEOUT_SECONDS ?? 90) * 1000;

const jobs = new Map<string, JobRecord>();
const queue: JobRecord[] = [];
let running = 0;

const pump = () => {
  while (running < CONCURRENCY && queue.length) {
    const rec = queue.shift()!;
    running++;
    executeJob(rec)
      .catch((e) => console.error(`[worker] job ${rec.result.job_id} crashed:`, e))
      .finally(() => {
        running--;
        console.log(`[worker] job ${rec.result.job_id} ${rec.result.status}${rec.result.error ? `: ${rec.result.error.code}` : ''}`);
        pump();
      });
  }
};

const send = (res: http.ServerResponse, status: number, body: unknown) => {
  const data = JSON.stringify(body);
  res.writeHead(status, {'content-type': 'application/json', 'content-length': Buffer.byteLength(data)});
  res.end(data);
};

const errorBody = (code: string, message: string, stage = 'render_worker') => ({error: {code, stage, message, retryable: false, scene_id: null}});

const authorized = (req: http.IncomingMessage): boolean => {
  if (!TOKEN) return true;
  const got = Buffer.from(String(req.headers.authorization ?? ''));
  const want = Buffer.from(`Bearer ${TOKEN}`);
  return got.length === want.length && timingSafeEqual(got, want);
};

const readJson = (req: http.IncomingMessage): Promise<unknown> =>
  new Promise((resolve, reject) => {
    let size = 0;
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(new InputError('request body too large'));
        req.destroy();
      } else chunks.push(c);
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(new InputError('body is not valid JSON'));
      }
    });
    req.on('error', reject);
  });

/** Run the type-checker in a child process and parse its single JSON line. */
const validateInChild = async (file: string): Promise<SourceValidationResult> => {
  let parsed: SourceValidationResult | null = null;
  const outcome = await runChild(['src/source-check.ts', file, workDir()], VALIDATE_TIMEOUT_MS, (msg) => {
    if (typeof msg.valid === 'boolean') parsed = msg as unknown as SourceValidationResult;
  });
  if (parsed) return parsed;
  return {valid: false, diagnostics: [`validator failed: ${outcome.message ?? 'no result'} ${outcome.log.slice(-1000)}`]};
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://worker');
  try {
    if (req.method === 'GET' && url.pathname === '/health') {
      return send(res, 200, {status: 'ok', queued: queue.length, running, concurrency: CONCURRENCY, auth_required: !!TOKEN, artifact_root_ready: await fs.access(artifactRoot()).then(() => true, () => false)});
    }
    if (!authorized(req)) return send(res, 401, errorBody('UNAUTHORIZED', 'missing or invalid bearer token'));

    if (req.method === 'POST' && url.pathname === '/validate') {
      return send(res, 200, await handleValidate((await readJson(req)) as PreviewRequest));
    }
    if (req.method === 'POST' && url.pathname === '/jobs') {
      const body = (await readJson(req)) as RenderJobRequest;
      const problems = checkRequest(body);
      if (problems.length) return send(res, 422, errorBody('RENDER_INPUT_INVALID', problems.join('; ')));
      const hash = requestHash(body);
      const existing = jobs.get(body.job_id);
      if (existing) {
        if (existing.hash !== hash) return send(res, 409, errorBody('JOB_ID_CONFLICT', `job ${body.job_id} already exists with different input`));
        return send(res, 202, {job_id: body.job_id, status: existing.result.status});
      }
      const rec = newRecord(body, hash);
      const done = await loadCompleted(body, hash);
      if (done) {
        rec.result = done;
        jobs.set(body.job_id, rec);
        return send(res, 202, {job_id: body.job_id, status: done.status});
      }
      if (queue.length >= MAX_QUEUE) return send(res, 503, errorBody('QUEUE_FULL', 'render queue is full'));
      jobs.set(body.job_id, rec);
      queue.push(rec);
      setImmediate(pump);
      return send(res, 202, {job_id: body.job_id, status: 'queued'});
    }
    const m = /^\/jobs\/([^/]+)$/.exec(url.pathname);
    if (req.method === 'GET' && m) {
      const id = decodeURIComponent(m[1]);
      const rec = JOB_ID_RE.test(id) ? jobs.get(id) : undefined;
      if (!rec) return send(res, 404, errorBody('JOB_NOT_FOUND', `unknown job ${id}`));
      return send(res, 200, rec.result);
    }
    return send(res, 404, errorBody('NOT_FOUND', `${req.method} ${url.pathname}`));
  } catch (e) {
    if (e instanceof InputError) return send(res, 422, errorBody('RENDER_INPUT_INVALID', e.message));
    console.error('[worker] request error', e);
    return send(res, 500, errorBody('WORKER_ERROR', 'internal worker error'));
  }
});

const handleValidate = async (body: PreviewRequest): Promise<SourceValidationResult> => {
  if (!body || body.kind !== 'scene_preview' || !body.build?.source) return {valid: false, diagnostics: ['body must be a PreviewRequest with build.source']};
  const structural = checkRequest(body);
  if (structural.length) return {valid: false, diagnostics: structural.map((p) => `request: ${p}`)};
  try {
    const file = resolveKey(body.build.source.key);
    if ((await sha256File(file)) !== body.build.source.sha256) return {valid: false, diagnostics: ['request: build.source sha256 does not match the stored file']};
    return await validateInChild(file);
  } catch (e) {
    return {valid: false, diagnostics: [`request: ${(e as Error).message}`]};
  }
};
await fs.mkdir(workDir(), {recursive: true});
server.listen(PORT, HOST, () => {
  console.log(`[worker] listening on ${HOST}:${PORT} artifact_root=${artifactRoot()} work_dir=${workDir()} concurrency=${CONCURRENCY}`);
  if (!TOKEN) console.warn('[worker] WARNING: RENDER_WORKER_TOKEN is empty - job/validate endpoints are unauthenticated (local development only)');
});
