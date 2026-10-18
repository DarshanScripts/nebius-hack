// Render job preparation and execution: renderer-input checks, isolated job
// bundle with only validated sources and verified local assets, a child
// render process with timeout, and atomic publication of outputs.
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  InputError,
  RENDERER_DIR,
  canonicalJson,
  publishFile,
  resolveKey,
  sha256Text,
  verifyRef,
  writeJsonAtomic,
} from './artifacts';
import {staticCheck} from './source-check';
import type {JobSpec} from './render-job';
import type {
  ArtifactRef,
  PipelineError,
  RenderInputProps,
  RenderJobRequest,
  RenderResult,
  SceneBuild,
  SceneContext,
  SceneSlot,
} from './types/contracts';

export const JOB_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const BUNDLE_FILES = ['index.ts', 'Root.tsx', 'Reel.tsx', 'ScenePreview.tsx', 'shell.tsx', 'scene-kit.tsx', 'types/contracts.ts'];

export const workDir = (): string => path.resolve(RENDERER_DIR, process.env.RENDER_WORK_DIR ?? '.jobs');

export const stageOf = (req: RenderJobRequest): string => (req.kind === 'final' ? 'final' : 'scene_preview');

export const pipelineError = (req: RenderJobRequest, code: string, message: string, retryable: boolean): PipelineError => ({
  code,
  stage: stageOf(req),
  message: message.slice(0, 8000),
  retryable,
  scene_id: req.kind === 'scene_preview' ? req.build?.scene_id ?? null : null,
});

export const requestHash = (req: RenderJobRequest): string => sha256Text(canonicalJson(req));

// ---------------------------------------------------------------- input checks
const checkContext = (ctx: SceneContext, projectId: string): string[] => {
  const p: string[] = [];
  if (!ctx || typeof ctx !== 'object') return ['context missing'];
  if (ctx.project_id !== projectId) p.push('context.project_id does not match request project_id');
  const v = ctx.timeline?.video;
  if (!v || v.width !== 1080 || v.height !== 1920 || v.fps !== 30 || v.duration_frames !== 1800) p.push('timeline.video must be 1080x1920@30fps, 1800 frames');
  const slots = (ctx.timeline?.scenes ?? []).slice().sort((a, b) => a.index - b.index);
  if (slots.length !== 6) p.push('timeline must have exactly 6 scenes');
  let cursor = 0;
  slots.forEach((s, i) => {
    if (s.index !== i + 1 || s.scene_id !== `s0${i + 1}`) p.push(`scene ${i + 1} has id ${s.scene_id}/index ${s.index}`);
    if (s.start_frame !== cursor) p.push(`scene ${s.scene_id} starts at ${s.start_frame}, expected ${cursor} (contiguous ranges)`);
    if (s.end_frame <= s.start_frame) p.push(`scene ${s.scene_id} has an empty range`);
    cursor = s.end_frame;
  });
  if (slots.length === 6 && cursor !== 1800) p.push(`scenes end at ${cursor}, expected 1800`);
  const audioIds = new Set((ctx.audio?.utterances ?? []).map((u) => u.dialogue_id));
  for (const u of ctx.timeline?.utterances ?? []) {
    if (!audioIds.has(u.dialogue_id)) p.push(`no audio for timeline utterance ${u.dialogue_id}`);
    if (u.start_frame < 0 || u.end_frame > 1800 || u.end_frame <= u.start_frame) p.push(`utterance ${u.dialogue_id} has invalid range`);
  }
  if (!/^[0-9a-f]{64}$/.test(ctx.context_hash ?? '') || !/^[0-9a-f]{64}$/.test(ctx.timeline_hash ?? '')) p.push('context_hash/timeline_hash must be sha256 hex');
  return p;
};

const checkBuild = (b: SceneBuild, ctx: SceneContext, projectId: string): string[] => {
  const p: string[] = [];
  if (b.project_id !== projectId) p.push(`build ${b.scene_id}: project_id mismatch`);
  if (b.context_hash !== ctx.context_hash) p.push(`build ${b.scene_id}: context_hash does not match the scene context`);
  if (b.timeline_hash !== ctx.timeline_hash) p.push(`build ${b.scene_id}: timeline_hash does not match the scene context`);
  if (!ctx.timeline.scenes.some((s) => s.scene_id === b.scene_id)) p.push(`build ${b.scene_id}: unknown scene id`);
  const slot = ctx.timeline.scenes.find((s) => s.scene_id === b.scene_id);
  if (slot) {
    const dur = slot.end_frame - slot.start_frame;
    for (const c of b.cues ?? []) {
      if (!(c.start_frame >= 0 && c.start_frame < c.end_frame && c.end_frame <= dur)) p.push(`build ${b.scene_id}: cue ${c.cue_id} outside [0,${dur})`);
    }
  }
  return p;
};

const sameSlot = (a: SceneSlot, b: SceneSlot | undefined) => !!b && canonicalJson(a) === canonicalJson(b);

/** Structural checks that need no filesystem access. */
export const checkRequest = (req: RenderJobRequest): string[] => {
  if (!req || typeof req !== 'object') return ['body must be a JSON object'];
  const p: string[] = [];
  if (req.schema_version !== '1.0') p.push('schema_version must be "1.0"');
  if (typeof req.project_id !== 'string' || !JOB_ID_RE.test(req.project_id)) p.push('invalid project_id');
  if (typeof req.job_id !== 'string' || !JOB_ID_RE.test(req.job_id)) p.push('invalid job_id');
  if (req.kind !== 'scene_preview' && req.kind !== 'final') return [...p, 'kind must be "scene_preview" or "final"'];
  p.push(...checkContext(req.context, req.project_id));
  if (p.length) return p;
  if (req.kind === 'scene_preview') {
    const ctxSlot = req.context.timeline.scenes.find((s) => s.scene_id === req.slot?.scene_id);
    if (!sameSlot(req.slot, ctxSlot)) p.push('slot does not match the context timeline slot');
    if (req.build?.scene_id !== req.slot?.scene_id) p.push('build.scene_id does not match slot');
    if (req.build) p.push(...checkBuild(req.build, req.context, req.project_id));
    const prefix = `projects/${req.project_id}/scenes/${req.slot?.scene_id}/`;
    if (!req.build?.source?.key?.startsWith(prefix)) p.push(`build.source.key must live under ${prefix}`);
  } else {
    const ids = (req.builds ?? []).map((b) => b.scene_id).sort();
    if (canonicalJson(ids) !== canonicalJson(['s01', 's02', 's03', 's04', 's05', 's06'])) p.push('final needs exactly one build for each of s01..s06');
    for (const b of req.builds ?? []) p.push(...checkBuild(b, req.context, req.project_id));
  }
  return p;
};

/** Output directory key for a job. */
export const outputDirKey = (req: RenderJobRequest): string =>
  req.kind === 'final' ? `projects/${req.project_id}/final/${req.job_id}` : path.posix.dirname(req.build.source.key);

const extFor = (ref: ArtifactRef): string => {
  const m = /\.([A-Za-z0-9]{1,5})$/.exec(ref.key);
  return m ? `.${m[1].toLowerCase()}` : '';
};

/** All media an input needs, verified, staged into the job public dir. */
const stageAssets = async (ctx: SceneContext, publicDir: string): Promise<Record<string, string>> => {
  const refs: [ArtifactRef, string][] = [];
  for (const u of ctx.audio.utterances) refs.push([u.wav, `audio ${u.dialogue_id}`]);
  for (const c of ctx.characters) if (c.image) refs.push([c.image, `character ${c.character_id}`]);
  for (const s of ctx.images.selections) if (s.status === 'selected' && s.asset) refs.push([s.asset, `image scene ${s.query.scene_index}`]);
  const assets: Record<string, string> = {};
  await fs.mkdir(path.join(publicDir, 'a'), {recursive: true});
  for (const [ref, label] of refs) {
    const real = await verifyRef(ref, label);
    const rel = `a/${ref.sha256}${extFor(ref)}`;
    const dest = path.join(publicDir, rel);
    try {
      await fs.link(real, dest);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') await fs.copyFile(real, dest);
    }
    assets[ref.key] = rel;
  }
  return assets;
};

export interface PreparedJob {
  dir: string;
  spec: JobSpec;
  outKey: string;
}

/** Build the isolated job dir: kit + shell + validated sources + verified assets. */
export const prepareJob = async (req: RenderJobRequest): Promise<PreparedJob> => {
  const dir = path.join(workDir(), `${req.job_id}-${Date.now()}`);
  await fs.mkdir(path.join(dir, 'src', 'types'), {recursive: true});
  await fs.symlink(path.join(RENDERER_DIR, 'node_modules'), path.join(dir, 'node_modules'), 'dir');
  for (const f of BUNDLE_FILES) await fs.copyFile(path.join(RENDERER_DIR, 'src', f), path.join(dir, 'src', f));

  const builds = req.kind === 'final' ? req.builds : [req.build];
  const lines: string[] = [];
  for (const b of builds) {
    const real = await verifyRef(b.source, `source ${b.scene_id}`);
    const source = await fs.readFile(real, 'utf8');
    const problems = staticCheck(source);
    if (problems.length) throw new InputError(`source ${b.scene_id} failed policy check:\n${problems.join('\n')}`);
    await fs.writeFile(path.join(dir, 'src', `scene_${b.scene_id}.tsx`), source);
    lines.push(`import ${b.scene_id} from './scene_${b.scene_id}';`);
  }
  lines.push(`import type {SceneComponent} from './shell';`);
  lines.push(`export const scenes: Record<string, SceneComponent> = {${builds.map((b) => b.scene_id).join(', ')}};`);
  await fs.writeFile(path.join(dir, 'src', 'generated-scenes.ts'), lines.join('\n') + '\n');

  const assets = await stageAssets(req.context, path.join(dir, 'public'));
  const props: RenderInputProps = {
    context: req.context,
    builds,
    assets,
    preview_scene_id: req.kind === 'scene_preview' ? req.slot.scene_id : null,
  };
  await fs.writeFile(path.join(dir, 'props.json'), JSON.stringify(props));
  const dur = req.kind === 'final' ? 1800 : req.slot.end_frame - req.slot.start_frame;
  const spec: JobSpec = {
    composition_id: req.kind === 'final' ? 'Reel' : 'ScenePreview',
    out_video: path.join(dir, 'out', req.kind === 'final' ? 'reel.mp4' : 'preview.mp4'),
    out_poster: path.join(dir, 'out', 'poster.jpg'),
    poster_frame: Math.floor(dur / 2),
    concurrency: process.env.RENDER_CHROME_CONCURRENCY ? Number(process.env.RENDER_CHROME_CONCURRENCY) : null,
    browser_executable: process.env.REMOTION_BROWSER_EXECUTABLE || null,
  };
  await fs.mkdir(path.join(dir, 'out'));
  await fs.writeFile(path.join(dir, 'spec.json'), JSON.stringify(spec, null, 2));
  return {dir, spec, outKey: outputDirKey(req)};
};

// ---------------------------------------------------------------- execution
const CHILD_ENV_ALLOW = ['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'XDG_CACHE_HOME', 'FONTCONFIG_PATH', 'FONTCONFIG_FILE', 'NODE_OPTIONS'];
export const childEnv = (): NodeJS.ProcessEnv =>
  Object.fromEntries(CHILD_ENV_ALLOW.filter((k) => process.env[k] !== undefined).map((k) => [k, process.env[k]]));

const tsxBin = () => path.join(RENDERER_DIR, 'node_modules', '.bin', 'tsx');

export interface ChildOutcome {
  ok: boolean;
  durationFrames?: number;
  message?: string;
  timedOut?: boolean;
  log: string;
}

export const runChild = (
  args: string[],
  timeoutMs: number,
  onLine: (msg: Record<string, unknown>) => void,
): Promise<ChildOutcome> =>
  new Promise((resolve) => {
    const child = spawn(tsxBin(), args, {cwd: RENDERER_DIR, env: childEnv(), stdio: ['ignore', 'pipe', 'pipe']});
    let log = '';
    let buf = '';
    let done: ChildOutcome | null = null;
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeoutMs);
    child.stdout.on('data', (d: Buffer) => {
      buf += d.toString();
      let i: number;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        try {
          const msg = JSON.parse(line) as Record<string, unknown>;
          if (msg.type === 'done') done = {ok: true, durationFrames: Number(msg.duration_frames), log: ''};
          else if (msg.type === 'error') done = {ok: false, message: String(msg.message), log: ''};
          else onLine(msg);
        } catch {
          log += line + '\n';
        }
      }
    });
    child.stderr.on('data', (d: Buffer) => {
      log = (log + d.toString()).slice(-20000);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (timedOut) return resolve({ok: false, timedOut: true, message: `render exceeded ${timeoutMs} ms`, log});
      if (done) return resolve({...done, log});
      resolve({ok: false, message: `render process exited with code ${code}`, log});
    });
  });

/** FFPROBE_PATH, else the ffprobe bundled with @remotion/compositor, else PATH. */
const ffprobeBin = (): string => {
  if (process.env.FFPROBE_PATH) return process.env.FFPROBE_PATH;
  const bundled = path.join(RENDERER_DIR, 'node_modules', '@remotion', `compositor-${process.platform}-${process.arch}-gnu`, 'ffprobe');
  return existsSync(bundled) ? bundled : 'ffprobe';
};

/** Count decoded video frames of an MP4 with ffprobe. */
export interface Probe {
  frames: number;
  width: number;
  height: number;
  fps: string;
  pix_fmt: string;
  video_codec: string;
  audio_codec: string | null;
}

export const probeFrames = (file: string): Promise<Probe> =>
  new Promise((resolve, reject) => {
    const ff = spawn(ffprobeBin(), ['-v', 'error', '-count_packets', '-show_entries', 'stream=codec_type,codec_name,nb_read_packets,width,height,r_frame_rate,pix_fmt', '-of', 'json', file]);
    let out = '';
    ff.stdout.on('data', (d: Buffer) => (out += d.toString()));
    ff.on('error', reject);
    ff.on('close', (code) => {
      if (code !== 0) return reject(new Error(`ffprobe exited ${code}`));
      type S = {codec_type: string; codec_name?: string; nb_read_packets?: string; width?: number; height?: number; r_frame_rate?: string; pix_fmt?: string};
      const streams = (JSON.parse(out).streams ?? []) as S[];
      const v = streams.find((s) => s.codec_type === 'video');
      const a = streams.find((s) => s.codec_type === 'audio');
      resolve({
        frames: Number(v?.nb_read_packets ?? 0),
        width: v?.width ?? 0,
        height: v?.height ?? 0,
        fps: v?.r_frame_rate ?? '',
        pix_fmt: v?.pix_fmt ?? '',
        video_codec: v?.codec_name ?? '',
        audio_codec: a?.codec_name ?? null,
      });
    });
  });

/** Required MP4 properties (plan.md section 8.8). Empty list = acceptable. */
export const outputProblems = (p: Probe, expectedFrames: number): string[] => {
  const out: string[] = [];
  if (p.frames !== expectedFrames) out.push(`${p.frames} frames, expected ${expectedFrames}`);
  if (p.width !== 1080 || p.height !== 1920) out.push(`${p.width}x${p.height}, expected 1080x1920`);
  if (p.fps !== '30/1') out.push(`fps ${p.fps}, expected 30/1`);
  if (p.pix_fmt !== 'yuv420p') out.push(`pix_fmt ${p.pix_fmt}, expected yuv420p`);
  if (p.video_codec !== 'h264') out.push(`video codec ${p.video_codec}, expected h264`);
  if (p.audio_codec !== 'aac') out.push(`audio codec ${p.audio_codec ?? 'none'}, expected aac`);
  return out;
};

export interface JobRecord {
  hash: string;
  request: RenderJobRequest;
  result: RenderResult;
}

const baseResult = (req: RenderJobRequest): RenderResult => ({
  schema_version: '1.0',
  project_id: req.project_id,
  job_id: req.job_id,
  status: 'queued',
  progress: 0,
  video: null,
  poster: null,
  duration_frames: null,
  error: null,
});

export const newRecord = (req: RenderJobRequest, hash: string): JobRecord => ({hash, request: req, result: baseResult(req)});

/** Previously completed job output on disk with the same input hash (survives worker restarts). */
export const loadCompleted = async (req: RenderJobRequest, hash: string): Promise<RenderResult | null> => {
  try {
    const rec = JSON.parse(await fs.readFile(resolveKey(`${outputDirKey(req)}/render-job.json`), 'utf8')) as {hash: string; result: RenderResult};
    return rec.hash === hash && rec.result.status === 'completed' ? rec.result : null;
  } catch {
    return null;
  }
};

/** Execute a queued job, updating rec.result in place. Never throws. */
export const executeJob = async (rec: JobRecord): Promise<void> => {
  const req = rec.request;
  const expected = req.kind === 'final' ? 1800 : req.slot.end_frame - req.slot.start_frame;
  const timeoutMs = Number(process.env.RENDER_JOB_TIMEOUT_SECONDS ?? 900) * 1000;
  const keepDirs = process.env.RENDER_KEEP_JOB_DIRS === 'true';
  rec.result = {...rec.result, status: 'running', progress: 0.01};
  let job: PreparedJob | null = null;
  let log = '';
  try {
    job = await prepareJob(req);
    const outcome = await runChild(['src/render-job.ts', job.dir], timeoutMs, (msg) => {
      if (msg.type === 'progress' && typeof msg.progress === 'number') {
        rec.result = {...rec.result, progress: Math.max(rec.result.progress, Math.min(0.97, msg.progress))};
      }
    });
    log = outcome.log;
    if (!outcome.ok) {
      const code = outcome.timedOut ? 'RENDER_TIMEOUT' : 'RENDER_FAILED';
      throw Object.assign(new Error(`${outcome.message ?? 'render failed'}${outcome.log ? `\n--- log tail ---\n${outcome.log.slice(-3000)}` : ''}`), {code, retryable: true});
    }
    const probe = await probeFrames(job.spec.out_video);
    const problems = outputProblems(probe, expected);
    if (problems.length) {
      throw Object.assign(new Error(`output check failed: ${problems.join('; ')}`), {code: 'FRAME_COUNT_MISMATCH', retryable: false});
    }
    const name = req.kind === 'final' ? 'reel.mp4' : 'preview.mp4';
    const video = await publishFile(job.spec.out_video, `${job.outKey}/${name}`, 'video/mp4');
    const poster = await publishFile(job.spec.out_poster, `${job.outKey}/poster.jpg`, 'image/jpeg');
    rec.result = {...rec.result, status: 'completed', progress: 1, video, poster, duration_frames: probe.frames, error: null};
  } catch (e) {
    const err = e as Error & {code?: string; retryable?: boolean};
    const code = e instanceof InputError ? 'RENDER_INPUT_INVALID' : err.code ?? 'RENDER_FAILED';
    rec.result = {...rec.result, status: 'failed', error: pipelineError(req, code, err.message, e instanceof InputError ? false : err.retryable ?? true)};
  } finally {
    try {
      await writeJsonAtomic(`${outputDirKey(req)}/render-job.json`, {hash: rec.hash, result: rec.result, worker_log_tail: log.slice(-5000)});
    } catch {
      /* output dir key invalid: nothing to record there */
    }
    if (job && !keepDirs) await fs.rm(job.dir, {recursive: true, force: true});
  }
};

