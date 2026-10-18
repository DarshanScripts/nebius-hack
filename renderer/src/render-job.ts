// Child process: bundle one prepared job dir and render it. Runs with a
// sanitized environment (no model/API credentials) and a parent-enforced
// timeout. Communicates via JSON lines on stdout.
import fs from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {ensureBrowser, renderMedia, renderStill, selectComposition} from '@remotion/renderer';

export interface JobSpec {
  composition_id: 'Reel' | 'ScenePreview';
  out_video: string;
  out_poster: string;
  poster_frame: number;
  concurrency: number | null;
  browser_executable: string | null;
}

const emit = (msg: Record<string, unknown>) => process.stdout.write(JSON.stringify(msg) + '\n');

const main = async () => {
  const jobDir = process.argv[2];
  const spec = JSON.parse(await fs.readFile(path.join(jobDir, 'spec.json'), 'utf8')) as JobSpec;
  const inputProps = JSON.parse(await fs.readFile(path.join(jobDir, 'props.json'), 'utf8')) as Record<string, unknown>;
  const browserExecutable = spec.browser_executable ?? undefined;
  const chromiumOptions = {enableMultiProcessOnLinux: true};
  if (!browserExecutable) await ensureBrowser();
  emit({type: 'progress', progress: 0.02, phase: 'bundling'});
  const serveUrl = await bundle({
    entryPoint: path.join(jobDir, 'src', 'index.ts'),
    publicDir: path.join(jobDir, 'public'),
    outDir: path.join(jobDir, 'bundle'),
    onProgress: (p) => emit({type: 'progress', progress: 0.02 + (p / 100) * 0.08, phase: 'bundling'}),
  });
  const composition = await selectComposition({serveUrl, id: spec.composition_id, inputProps, browserExecutable, chromiumOptions, logLevel: 'error'});
  emit({type: 'progress', progress: 0.1, phase: 'rendering'});
  await renderMedia({
    serveUrl,
    composition,
    inputProps,
    codec: 'h264',
    audioCodec: 'aac',
    pixelFormat: 'yuv420p',
    colorSpace: 'bt709',
    enforceAudioTrack: true,
    outputLocation: spec.out_video,
    browserExecutable,
    chromiumOptions,
    concurrency: spec.concurrency,
    logLevel: 'error',
    timeoutInMilliseconds: 120_000,
    onProgress: ({progress}) => emit({type: 'progress', progress: 0.1 + progress * 0.85, phase: 'rendering'}),
  });
  await renderStill({
    serveUrl,
    composition,
    inputProps,
    output: spec.out_poster,
    frame: Math.min(spec.poster_frame, composition.durationInFrames - 1),
    imageFormat: 'jpeg',
    jpegQuality: 85,
    browserExecutable,
    chromiumOptions,
    logLevel: 'error',
  });
  emit({type: 'done', duration_frames: composition.durationInFrames});
};

main().catch((e: unknown) => {
  const err = e instanceof Error ? `${e.name}: ${e.message}\n${e.stack ?? ''}` : String(e);
  emit({type: 'error', message: err.slice(0, 6000)});
  process.exitCode = 1;
});
