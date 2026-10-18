# Member 4 — scene agents, edit router, Remotion render worker

Owner paths: `backend/modules/scenes/` (Python) and `renderer/` (Node 22 + Remotion 4.0.534).
Branch: `feat/m4-scenes-renderer`. Contracts: `contracts.models` exactly as in `plan.md` §9 (no changes proposed).

## Callable interfaces (`backend/modules/scenes/service.py`)

```python
async def route_edit(request: EditRoutingRequest, runtime: Runtime) -> EditIntent
async def generate_scene(request: SceneTask, runtime: Runtime) -> SceneBuild
async def render_preview(request: PreviewRequest, runtime: Runtime) -> ScenePreviewOutcome
async def render_final(request: FinalRenderRequest, runtime: Runtime) -> RenderResult
```

All return validated models or raise `StageFailure(PipelineError)`. No snapshot/event writes;
progress goes through `runtime.report_progress` after every worker poll (stage `scene_preview` +
scene id with the **operation** id, or `final` with no scene id).

| Behaviour | Where |
| --- | --- |
| Target scene decided deterministically ("scene six", "scene 6", "s06", "sixth scene", selected id). Requests that change a locked layer (several scenes, the soundtrack, spoken words/captions, scene length, the character layer, theme/title) → `unsupported` with a reason. Words are matched in context, so diagram edits such as "voice packets", "a longer arrow" or "animation timing" stay editable. Pattern-based: tested on 21 editable and 19 locked-layer phrasings (plus 4 targeting errors), not exhaustive. Live mode: Nemotron structured output may refine the instruction or flag unsupported, never retarget. | `router.py` |
| Mock mode: deterministic fixture source per scene (`fixtures/scenes/sNN.tsx`, edits use `sNN_edit.tsx` or the fallback template), `generation_mode="mock"`, still validated by the worker. | `service.py` |
| Live mode: one isolated agent invocation per scene. `NEMOTRON_STRUCTURED_MODE=tool_calling` → LangChain `create_agent(runtime.llm, tools=[read_scene_context, read_previous_source, validate_scene_source], response_format=ToolStrategy(SceneDraft))`; `json_prompt` → `runtime.structured(schema=SceneDraft)`. | `agent.py` |
| Generate → worker `/validate` → repair with diagnostics, **max 2 corrective attempts total across validation and preview** (`SceneBuild.repair_attempts`), then the deterministic fallback template (`generation_mode="fallback"`, `warnings[0]` starts `FALLBACK:`). Model transport/auth errors are a retryable `SCENE_AGENT_UNAVAILABLE` stage error, never a silent fallback. A `StageFailure` from `runtime.structured` counts as a repair attempt when its code names an output problem (`INVALID`/`SCHEMA`/`PARSE`/`VALIDATION`/`STRUCTURED`/`JSON`, and none of `UNAVAILABLE`/`TIMEOUT`/`AUTH`/`RATE`/…); otherwise it is re-raised. **Member 1:** please keep core's invalid-output code within that vocabulary. A preview repair of an edit keeps the user's instruction (read from the operation's `task.json`). | `service.py` |
| Cue frames that name word ids are recomputed from the measured words (LLM cannot move timing); unknown word/claim ids, duplicates and out-of-range untimed cues are repair diagnostics. | `timing.py` |
| Worker job id `<operation_id>-a<repair_attempts>` (fallback: `<operation_id>-afb`), preserved in the returned `RenderResult`. | `service.worker_job_id` |
| Agent brief: topic, all 12 turns (own turns with scene-local word frames), research summary + report excerpt + sources + claims + uncertainties, own and other scenes' image choices, the six-slot timeline, theme. | `agent.scene_brief` |
| Shared authoring context for every agent (theme, coordinates, kit API, timing/boundary rules, import allowlist, working example — the example is compiled by the test suite). | `scene_authoring.md` |

Artifacts (all immutable, relative keys):

```text
projects/<id>/scenes/<sid>/v<rev>/<operation_id>/task.json                     # edit instruction for this operation
projects/<id>/scenes/<sid>/v<rev>/<operation_id>/a<n>/{Scene.tsx,validation.json,build.json,preview.mp4,poster.jpg,render-job.json}
projects/<id>/scenes/<sid>/v<rev>/<operation_id>/a<n>/candidates/NN/Scene.tsx   # tool_calling validate calls
projects/<id>/scenes/<sid>/v<rev>/<operation_id>/afb/...                         # fallback build
projects/<id>/final/<job_id>/{reel.mp4,poster.jpg,render-job.json}               # manifest.json is member 1's
```

`render-job.json` holds the input hash, final `RenderResult` and the render log tail, written for
failed jobs too (diagnostics).

## Render worker (`renderer/`)

| Route | Behaviour |
| --- | --- |
| `GET /health` | `{status, queued, running, concurrency, auth_required, artifact_root_ready}` — no secrets |
| `POST /jobs` | `PreviewRequest \| FinalRenderRequest` by `kind` → `202 {"job_id","status"}`. Fast: structural checks only, encoding runs from a FIFO queue (`RENDER_CONCURRENCY`, default 1). Same id + same input → same job; same id + different input → 409. Completed output on disk with the same input hash is reused after a worker restart. |
| `GET /jobs/{id}` | `RenderResult` (progress 0–1 from real bundle/render/encode progress) |
| `POST /validate` | candidate `PreviewRequest` → `SourceValidationResult` (policy check + strict TypeScript type-check against the real kit, in a child process; no encoding) |

`Authorization: Bearer $RENDER_WORKER_TOKEN` on `/jobs` and `/validate` (unauthenticated only
when the token is empty — the worker prints a warning; local dev only).

Render path: request checks (contiguous six slots over `[0,1800)`, build hashes == context hashes,
slot == context slot, source key under its scene dir) → isolated job dir with the kit/shell, the
generated sources (re-policy-checked) and **only** hash-verified local assets (WAVs, character PNGs,
selected images) in its `publicDir` → child `tsx src/render-job.ts` with an allowlisted environment
(no API keys/tokens) and `RENDER_JOB_TIMEOUT_SECONDS` kill → H.264/AAC, `yuv420p` (bt709 limited
range), 1080×1920@30 → ffprobe check (frame count = slot duration or 1800, codecs, pix_fmt) →
atomic publish into `ARTIFACT_ROOT`.

Compositions: `Reel` (1800 frames: six scenes at fixed ranges, each WAV once on the global timeline)
and `ScenePreview` (one scene; frame 0 = `slot.start_frame`; the same shell with characters,
captions and audio clipped to the scene). The shell (`src/shell.tsx`) owns dot grid, title,
captions from aligned words (≤6 words/34 chars per chunk, active word blue), character slides
`[start-8,start)` / `[end,end+8)` driven by global utterance timing, audio, and the 12-frame
boundary envelope. Generated scenes only draw inside the 936×816 content box.

Generated-source policy (`src/source-check.ts`): imports only `react`, `remotion` (allowlisted
helpers) and `./scene-kit`; no state/effect hooks, timers, `Date`, `Math.random`, network,
globals, `process`, raw `<img>/<video>/<audio>/<iframe>/<image>/<use>`, URL strings or CSS `url()`,
literal `fontSize` below 36; default-exported component; strict TypeScript. (Computed font sizes
cannot be checked statically.)

## Setup and commands

From the repository root (Python 3.11, Node 22):

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/modules/scenes/dependencies.txt
npm ci --prefix renderer
# until contracts/models.py lands on main: plan.md section 2 bootstrap into ignored .bootstrap/
export PYTHONPATH="$PWD/.bootstrap:$PWD"

# tests (offline, no worker, no model calls; one test runs the real TS validator)
.venv/bin/python -m pytest backend/modules/scenes/tests -q
npm test --prefix renderer && npm run typecheck --prefix renderer

# full fixture acceptance: starts its own worker on :8011 with ARTIFACT_ROOT=--output
.venv/bin/python -m backend.modules.scenes.demo --mock --output output/demos/scenes
# same, with MOCK transparent character PNGs instead of silhouettes. Use a separate --output:
# artifacts are immutable, so a different fixture variant in the same project namespace is refused.
.venv/bin/python -m backend.modules.scenes.demo --mock --character-pngs --output output/demos/scenes-png

# worker alone (what compose runs); relative ARTIFACT_ROOT resolves against the repo root
ARTIFACT_ROOT=./output RENDER_WORKER_TOKEN=<secret> npm run worker --prefix renderer

# one live scene through the configured Nemotron endpoint (needs NEMOTRON_* env)
.venv/bin/python -m backend.modules.scenes.demo --output output/demos/scenes-live --only s02
```

Optional env: `REMOTION_BROWSER_EXECUTABLE` (use an existing chrome-headless-shell instead of
Remotion's download), `RENDER_CHROME_CONCURRENCY`, `RENDER_WORK_DIR` (default `renderer/.jobs`),
`RENDER_KEEP_JOB_DIRS=true`, `FFPROBE_PATH` (default: Remotion's bundled ffprobe),
`RENDER_POLL_INTERVAL_SECONDS`, `SCENE_REPAIR_ATTEMPTS` (≤2). Settings are read from
`runtime.settings` (either case) then the environment.

Docker: `docker build -t reel-renderer renderer` (Remotion's Debian/Chrome guidance + DejaVu,
non-root user, healthcheck). Compose (member 1): service `renderer`, port 8001, mount the shared
volume at `/workspace/output`, pass `RENDER_WORKER_TOKEN`, `RENDER_CONCURRENCY`,
`RENDER_JOB_TIMEOUT_SECONDS`; no model credentials.

## Acceptance results (2026-10-18, laptop, mock mode, real Remotion renders)

Snapshot: code as committed after the review fixes. Run `output/demos/scenes-png/demo-report-20261018-1453.json`
(`--mock --character-pngs`, 2 min 35 s). Every row below was measured on this run's artefacts.

| Check | Result |
| --- | --- |
| Six scenes generated + worker-validated | 6 × `mock`; all six validated in ~3 s (concurrent) |
| Previews submitted `s03,s01,s06,s02,s05,s04` | completed in that order; frames 273/270/270/270/270/447 = slot durations; ~12 s each |
| Route "Please correct scene six: make the packet diagram clearer" | `edit_scene`, `s06` |
| Edit s06 rev 1 → 2 | s06 source hash changed; s01–s05 source hashes unchanged; timeline hash unchanged; preview 447 frames |
| Repair loop → fallback (canned broken model, `json_prompt` path) | 3 drafts (a0,a1,a2) rejected by the real validator, fallback `afb`, `repair_attempts=2`, `FALLBACK:` warning, preview rendered |
| Final master `final-20261018-1453/reel.mp4` | 1800 frames, 1080×1920, 30/1, h264 `yuv420p`, aac 48 kHz, 60.01 s, 39.5 s render |
| Audio at joins | silent at 0.0 s (before first utterance), speech at 1.0 s, silent at 8.9 s (scene gap), speech at 17 s / 50 s, silent at 55 s (after 53.7 s) |
| Character PNGs + boundary (frames 130/138/1340/1353/1366/1500) | inspected: transparent cut-outs over the dot grid, clipped to the bottom region; Sundar slides out / Jensen in at a turn change; s05 board until its fade, empty board at the 1353 cut, s06 fading in; captions follow global turns |
| Python tests | 70 passed |
| Renderer tests / typecheck | 8 passed with `OLD_REEL` set (7 + 1 skipped without it; that test proves a full-range file is rejected) / clean |

The silhouette-placeholder variant (no PNGs) was rendered and inspected in run
`output/demos/scenes/demo-report-20261018-1437.json` (before the review fixes; same render code
path except the character image branch).

Bad-source probe (`/tmp` files, see engineering log): every policy class and TS errors reported
with line numbers; syntax errors reported.

## Blockers / not verified

- **Live Nemotron scene generation: BLOCKED.** With the key available in this shell
  (`NVIDIA_API_KEY` mapped to `NEMOTRON_API_KEY`), `/v1/models` lists
  `nvidia/nemotron-3.5-super-vl-120b-a12b` but chat completion returns `403 Authorization failed`.
  Needs the project's NVIDIA key (owner's `.env`). The failure path was verified: it raises a
  retryable `SCENE_AGENT_UNAVAILABLE` and the run report is still written
  (`output/demos/scenes-live/demo-report-20261018-1440.json`).
- `tool_calling` mode (create_agent + ToolStrategy) is implemented but unexercised against
  Nemotron; it depends on member 1's capability check.
- Docker image not built yet (downloads several hundred MB: base image, npm deps, Chrome
  Headless Shell). Cloud rendering on the Nebius VM is member 1's deployment step.
- Real character PNGs not in the repo yet; the image path is exercised with MOCK transparent PNGs
  (`--character-pngs`), the silhouette placeholder when absent.
- `context_hash` is not recomputed by the worker (it checks build hashes == context fields);
  member 1's `contracts/validation.py` owns canonical hashing.

More: `doc/engineering-log.md`, `doc/backlog.md` in this directory.
