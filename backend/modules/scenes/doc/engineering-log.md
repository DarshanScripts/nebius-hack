# Member 4 engineering log

Newest last. What was done, why, what worked, and what failed (with the reason).

## 2026-10-18 — initial build on `feat/m4-scenes-renderer`

**Setup.** Branch from `origin/main` (0c1ff3e). Contracts extracted with the plan's bootstrap
snippet into ignored `.bootstrap/` (member 1 has not published `contracts/models.py` yet).
`backend/` and `backend/modules/` have no `__init__.py` on main (member 1 owns them); they work
as implicit namespace packages, so `python -m backend.modules.scenes.demo` runs without creating
them. Tests live in `tests/` *without* `__init__.py`; with one, pytest's prepend import mode
imports them as `scenes.tests.*`, colliding with `backend.modules.scenes`.

**Version picks.** Remotion 4.0.534 (published 2026-10-07; 4.0.535/536 were < 7 days old).
React 19.3.0 (19.3.1 was 4 days old). TypeScript 5.9.3, not 7.x: the validator uses the
TypeScript compiler API and TS 7 is the native port. tsx 4.23.15 runs the worker without a build
step.

**Design decisions.**
- One isolated job dir per render: copies of the kit/shell/compositions, generated
  `scene_sNN.tsx`, a generated `generated-scenes.ts` map, `node_modules` symlinked, and a
  `public/` holding only hash-verified assets named by sha256. The scene kit is the only local
  import generated code can reach.
- The shell renders in *global* frames with an `offset`, so preview and reel share one code path
  (preview = offset `slot.start_frame`, duration = slot). Audio per utterance is a `Sequence`;
  the preview simply cuts at its duration.
- `RenderInputProps` must be a `type`, not an `interface`: Remotion's `Composition` requires props
  assignable to `Record<string, unknown>`, which TS interfaces are not (tsc error TS2322).
- Validation = static policy (TS AST) + strict type-check against the real kit with `types: []`,
  so `process`/`require` are also type errors. Runs in a child process (`/validate` does not block
  the HTTP loop or the render queue).
- Repair accounting: each regenerate after a failed validation or a scene-attributable render
  failure is one corrective attempt; total ≤ 2 (`SceneBuild.repair_attempts`), then the
  deterministic fallback template. Transport/auth errors from the model raise
  `SCENE_AGENT_UNAVAILABLE` instead — a fallback there would hide a provider outage behind a
  "successful" scene.
- Edit routing is deterministic for the target; the model may only rewrite the instruction or
  declare the request unsupported. A model-proposed different scene is logged and ignored.
- Cue frames for cues with word ids are recomputed from measured words (warning recorded), so a
  model can never move authoritative timing.
- Worker restarts: completed outputs carry `render-job.json` with the input hash; an identical
  resubmission returns the stored result. The Python client resubmits once on a 404 (lost queue).

**What failed and why.**
- Placeholder silhouette name clipped ("Sundar Picha") — the text ran past the SVG body width.
  Found by looking at preview frames, not by any test. Fixed with a wider body and `textLength`.
- First final render was `yuvj420p` (full range) although `pixelFormat: 'yuv420p'` was set.
  Reason (read in `@remotion/renderer/dist/ffmpeg-args.js`): only `colorSpace: 'bt709'` adds
  `-color_range tv` and the limited-range zscale; the default leaves full range, which ffprobe
  reports as `yuvj420p`. Fixed with `colorSpace: 'bt709'`, and the worker's output check now
  rejects anything but h264/`yuv420p`/aac/30fps/1080×1920/exact frames — proven by running the
  check against the old full-range reel (`OLD_REEL=… npm test`).
- My first audio check printed nothing: `ffmpeg -v error` suppresses `volumedetect` output.
  Re-run with `-hide_banner`.
- Live Nemotron call: `403 Authorization failed` on chat completions with the key available in
  this shell, although `/v1/models` (same key) lists the model. Not retried — auth is the owner's
  call. Error surfaced as `SCENE_AGENT_UNAVAILABLE`; report written from the `finally` path.

**Evidence.** `output/demos/scenes/demo-report-20261018-1437.json` (mock acceptance, completed),
`output/demos/scenes-live/demo-report-20261018-1440.json` (live, failed 403). Bad-source probe:
three hand-written sources (forbidden imports/hooks/timers/network/URLs/img; syntax error;
type error) — all rejected with line-numbered diagnostics.
