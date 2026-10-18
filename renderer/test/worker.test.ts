// Run: npm test  (node:test via tsx). Optional: OLD_REEL=<yuvj420p mp4> exercises the probe on a real bad file.
import assert from 'node:assert/strict';
import test from 'node:test';
import {canonicalJson, InputError, resolveKey} from '../src/artifacts';
import {checkRequest, outputProblems, probeFrames} from '../src/jobs';
import {staticCheck} from '../src/source-check';
import {captionChunks, characterOffset} from '../src/shell';
import type {TimedTurn} from '../src/scene-kit';
import type {RenderJobRequest} from '../src/types/contracts';

test('resolveKey rejects traversal, absolute and scheme keys', () => {
  process.env.ARTIFACT_ROOT = '/tmp/m4-root';
  for (const k of ['../x', 'a/../../x', '/etc/passwd', 'file:/x', 'a//b', 'a\\b', '']) {
    assert.throws(() => resolveKey(k), InputError, k);
  }
  assert.equal(resolveKey('projects/p/x.wav'), '/tmp/m4-root/projects/p/x.wav');
});

test('canonicalJson sorts keys recursively', () => {
  assert.equal(canonicalJson({b: 1, a: {d: [2, {z: 1, y: 2}], c: null}}), '{"a":{"c":null,"d":[2,{"y":2,"z":1}]},"b":1}');
});

test('outputProblems enforces the master format', () => {
  const ok = {frames: 1800, width: 1080, height: 1920, fps: '30/1', pix_fmt: 'yuv420p', video_codec: 'h264', audio_codec: 'aac'};
  assert.deepEqual(outputProblems(ok, 1800), []);
  assert.equal(outputProblems({...ok, pix_fmt: 'yuvj420p'}, 1800).length, 1);
  assert.equal(outputProblems({...ok, frames: 1799, audio_codec: null}, 1800).length, 2);
});

test('probe flags a real full-range file', {skip: !process.env.OLD_REEL}, async () => {
  const p = await probeFrames(process.env.OLD_REEL!);
  assert.match(outputProblems(p, 1800).join(), /yuvj420p/);
});

test('staticCheck accepts kit usage and rejects escapes', () => {
  const good = `import React from 'react';\nimport {interpolate} from 'remotion';\nimport {Box} from './scene-kit';\nimport type {SceneProps} from './scene-kit';\nexport default function Scene(p: SceneProps) { return <Box x={0} y={0} width={10} height={10} opacity={interpolate(p.frame,[0,1],[0,1])} />; }\n`;
  assert.deepEqual(staticCheck(good), []);
  const cases: [string, RegExp][] = [
    [`import x from 'lodash';`, /lodash/],
    [`const a = React.useEffect;`, /useEffect/],
    [`const t = window.location;`, /window/],
    [`const r = Math.random();`, /Math.random/],
    [`const u = '//evil/x.png';`, /URL/],
    [`const s = {background: 'url(x.png)'};`, /url/],
    [`const e = <iframe />;`, /iframe/],
    [`const m = import('./x');`, /dynamic import/],
    [`export * from './scene-kit';`, /re-export/],
    [`import {OffthreadVideo} from 'remotion';`, /OffthreadVideo/],
    [`const k = globalThis['process'];`, /globalThis/],
  ];
  for (const [line, re] of cases) {
    const src = `import React from 'react';\n${line}\nexport default function Scene() { return null; }\n`;
    assert.match(staticCheck(src).join('\n'), re, line);
  }
  assert.match(staticCheck(`export function Scene() { return null; }`).join(), /default/);
});

const turn = (speaker: 'sundar' | 'jensen', start: number, end: number, words: string[]): TimedTurn => ({
  turn: {dialogue_id: 'd001', order: 1, scene_index: 1, speaker_id: speaker, text: words.join(' '), intent: 'hook', claim_ids: []},
  audio: undefined,
  start,
  end,
  words: words.map((w, i) => ({word_id: `d001_w${i}`, text: w, start: start + i * 5, end: start + i * 5 + 4})),
});

test('characters slide in over the 8 frames before a turn and out over 8 after', () => {
  const turns = [turn('sundar', 100, 200, ['a', 'b'])];
  assert.equal(characterOffset(turns, 'sundar', 91), null);
  assert.ok((characterOffset(turns, 'sundar', 92) as number) < -400);
  assert.equal(characterOffset(turns, 'sundar', 100), 0);
  assert.equal(characterOffset(turns, 'sundar', 199), 0);
  assert.ok((characterOffset(turns, 'sundar', 207) as number) < -400);
  assert.equal(characterOffset(turns, 'sundar', 208), null);
  assert.equal(characterOffset(turns, 'jensen', 150), null);
  assert.ok((characterOffset([turn('jensen', 100, 200, ['a'])], 'jensen', 95) as number) > 0);
});

test('caption chunks cover the turn contiguously, break at punctuation and stay short', () => {
  const t = turn('jensen', 0, 300, 'Not always. Media can flow peer to peer, or through a relay when networks block that.'.split(' '));
  const chunks = captionChunks(t);
  assert.equal(chunks[0].start, 0);
  assert.equal(chunks.at(-1)!.end, 300);
  for (let i = 1; i < chunks.length; i++) assert.equal(chunks[i].start, chunks[i - 1].end);
  assert.deepEqual(chunks[0].words.map((w) => w.text), ['Not', 'always.']);
  for (const c of chunks) assert.ok(c.words.length <= 6 && c.words.map((w) => w.text).join(' ').length <= 34);
});

test('checkRequest rejects foreign hashes, bad ids and misplaced sources', () => {
  const slot = (i: number, s: number, e: number) => ({scene_id: `s0${i}`, index: i, start_frame: s, end_frame: e, dialogue_ids: [], entry_state: 'clear_content', exit_state: 'clear_content'});
  const b = [0, 273, 543, 813, 1083, 1353, 1800];
  const h = 'a'.repeat(64);
  const ctx = {
    project_id: 'p1', context_hash: h, timeline_hash: h, audio: {utterances: []},
    timeline: {video: {width: 1080, height: 1920, fps: 30, duration_frames: 1800, scene_count: 6}, utterances: [], scenes: [1, 2, 3, 4, 5, 6].map((i) => slot(i, b[i - 1], b[i]))},
  };
  const build = {project_id: 'p1', scene_id: 's01', context_hash: h, timeline_hash: h, cues: [], source: {key: 'projects/p1/scenes/s01/v1/op/a0/Scene.tsx'}};
  const req = {schema_version: '1.0', project_id: 'p1', kind: 'scene_preview', job_id: 'op-a0', context: ctx, slot: slot(1, 0, 273), build} as unknown as RenderJobRequest;
  assert.deepEqual(checkRequest(req), []);
  const bad = (patch: object) => checkRequest({...(req as object), ...patch} as RenderJobRequest).join();
  assert.match(bad({job_id: '../x'}), /job_id/);
  assert.match(bad({build: {...build, context_hash: 'b'.repeat(64)}}), /context_hash/);
  assert.match(bad({build: {...build, source: {key: 'projects/p1/scenes/s02/x/Scene.tsx'}}}), /must live under/);
  assert.match(bad({slot: slot(1, 0, 300)}), /slot does not match/);
  assert.match(bad({kind: 'final', builds: [build]}), /s01\.\.s06/);
});
