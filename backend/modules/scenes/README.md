# Member 4 — scene agents, edit router, Remotion render worker

Owner paths: `backend/modules/scenes/` (Python) and `renderer/` (Node 22 + Remotion 4.0.534).
Branch: `feat/m4-scenes-renderer` (includes Member 1's platform seed `d3dfba6`). Uses `contracts.models` and
`contracts.validation` unchanged; no shared-contract change is required.

## Callable interfaces (`backend/modules/scenes/service.py`)

```python
async def route_edit(request: EditRoutingRequest, runtime: Runtime) -> EditIntent
async def generate_scene(request: SceneTask, runtime: Runtime) -> SceneBuild
async def render_preview(request: PreviewRequest, runtime: Runtime) -> ScenePreviewOutcome
async def render_final(request: FinalRenderRequest, runtime: Runtime) -> RenderResult
```

All return validated models or raise `StageFailure(PipelineError)`. Builds/renders are checked with core's
`validate_context` (structure + hashes), `validate_build` and `validate_render` before returning. No snapshot/event writes;
progress goes through `runtime.report_progress` after every worker poll (stage `scene_preview` +
scene id with the **operation** id, or `final` with no scene id).

| Behaviour | Where |
| --- | --- |
| Target scene decided deterministically ("scene six", "scene 6", "s06", "sixth scene", selected id). Requests that change a locked layer (several scenes, the soundtrack, spoken words/captions, scene length, the character layer, theme/title) → `unsupported` with a reason. Words are matched in context, so diagram edits such as "voice packets", "a longer arrow" or "animation timing" stay editable. Pattern-based: tested on 21 editable and 19 locked-layer phrasings (plus 4 targeting errors), not exhaustive. Live mode: Nemotron structured output may refine the instruction or flag unsupported, never retarget. | `router.py` |
| Mock mode: deterministic fixture source per scene (`fixtures/scenes/sNN.tsx`, edits use `sNN_edit.tsx` or the fallback template), `generation_mode="mock"`, still validated by the worker. | `service.py` |
| Live mode: one isolated agent invocation per scene. `NEMOTRON_STRUCTURED_MODE=tool_calling` → LangChain `create_agent(runtime.llm, tools=[read_scene_context, read_previous_source, validate_scene_source], response_format=ToolStrategy(SceneDraft))`; `json_prompt` → `runtime.structured(schema=SceneDraft)`. | `agent.py` |
| Generate → worker `/validate` → repair with diagnostics. Attempt slots `a0..a2` (core accepts only worker ids `-a0/-a1/-a2`): `a0` = first draft, corrective attempts up to `SCENE_REPAIR_ATTEMPTS` (default 2) across validation **and** preview; the **last** corrective slot is the deterministic fallback template (`generation_mode="fallback"`, `warnings[0]` starts `FALLBACK:`). Default: a0 agent → a1 agent repair → a2 fallback. If no slot is left (e.g. a failing fallback, or `SCENE_REPAIR_ATTEMPTS=0`) → `SCENE_REPAIRS_EXHAUSTED` stage error. Model transport/auth errors are a retryable `SCENE_AGENT_UNAVAILABLE` stage error, never a silent fallback. A `StageFailure` from `runtime.structured` counts as a repair attempt when its code names an output problem (`INVALID`/`SCHEMA`/`PARSE`/`VALIDATION`/`STRUCTURED`/`JSON`, and none of `UNAVAILABLE`/`TIMEOUT`/`AUTH`/`RATE`/…); otherwise it is re-raised. Core's codes classify as intended: `STRUCTURED_OUTPUT_INVALID` → repair; `MODEL_REQUEST_FAILED`, `MISSING_CONFIGURATION`, `MOCK_LLM_DISABLED` → raised. A preview repair of an edit keeps the user's instruction (read from the operation's `task.json`). | `service.py` |
| Cue frames that name word ids are recomputed from the measured words (LLM cannot move timing); unknown word/claim ids, duplicates and out-of-range untimed cues are repair diagnostics. | `timing.py` |
| Worker job id `<operation_id>-a<repair_attempts>` (fallback included), preserved in the returned `RenderResult`. | `service.worker_job_id` |
| Agent brief: topic, all 12 turns (own turns with scene-local word frames), research summary + report excerpt + sources + claims + uncertainties, own and other scenes' image choices, the six-slot timeline, theme. | `agent.scene_brief` |
| Shared authoring context for every agent (theme, coordinates, kit API, timing/boundary rules, import allowlist, working example — the example is compiled by the test suite). | `scene_authoring.md` |

Artifacts (all immutable, relative keys):

```text
projects/<id>/scenes/<sid>/v<rev>/<operation_id>/task.json                     # edit instruction for this operation
projects/<id>/scenes/<sid>/v<rev>/<operation_id>/a<n>/{Scene.tsx,validation.json,build.json,preview.mp4,poster.jpg,render-job.json}
projects/<id>/scenes/<sid>/v<rev>/<operation_id>/a<n>/candidates/NN/Scene.tsx   # tool_calling validate calls
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

From the repository root, using the platform's root environment (Python ≥ 3.11, Node 22):

```bash
uv sync                      # root pyproject/uv.lock (Member 1); this module needs nothing extra
npm ci --prefix renderer

# tests: offline, no worker, no model calls (one test runs the real TS validator)
uv run python -m pytest backend/modules/scenes/tests -q
npm test --prefix renderer && npm run typecheck --prefix renderer

# full fixture acceptance; starts its own worker on :8011 with ARTIFACT_ROOT=--output.
# Artifacts are immutable: use a fresh --output per fixture variant.
uv run python -m backend.modules.scenes.demo --mock --output output/demos/scenes
uv run python -m backend.modules.scenes.demo --mock --character-pngs --output output/demos/scenes-png

# Member 1's real Coordinator driving this module (core content/voice fixtures + real scenes,
# edit and Stitch) against a running worker whose ARTIFACT_ROOT is --output
RENDER_WORKER_TOKEN=<token> uv run python -m backend.modules.scenes.integration_check \
    --worker-url http://127.0.0.1:8001 --output output/demos/scenes-core

# worker alone; a relative ARTIFACT_ROOT resolves against the repo root
ARTIFACT_ROOT=./output RENDER_WORKER_TOKEN=<token> npm run worker --prefix renderer

# live: one scene with core's AppRuntime and the root .env (NEMOTRON_*), see limitations below
uv run python -m backend.modules.scenes.demo --output output/demos/scenes-live --only s02
```

Environment variables (root `.env.example` names; read from `runtime.settings`, uppercase, then the
process environment):

| Variable | Used by | Purpose |
| --- | --- | --- |
| `RENDER_WORKER_URL`, `RENDER_WORKER_TOKEN` | Python client, worker | worker address; bearer secret for `/jobs` and `/validate` |
| `RENDER_JOB_TIMEOUT_SECONDS`, `RENDER_CONCURRENCY` | both | per-job deadline; parallel encodes (default 1) |
| `ARTIFACT_ROOT` | worker | shared output root (`/workspace/output` in compose) |
| `NEMOTRON_STRUCTURED_MODE`, `SCENE_REPAIR_ATTEMPTS` | Python | `json_prompt` / `tool_calling`; corrective attempts (≤ 2) |
| `MOCK_MODE`, `NEMOTRON_*` | core runtime | fixture vs agent generation; model endpoint (core's `Runtime.llm/structured`) |
| optional: `REMOTION_BROWSER_EXECUTABLE`, `RENDER_CHROME_CONCURRENCY`, `RENDER_WORK_DIR`, `RENDER_KEEP_JOB_DIRS`, `FFPROBE_PATH`, `RENDER_POLL_INTERVAL_SECONDS`, `RENDER_WORKER_HOST` | worker/client | local Chrome, Chrome tabs, job dir, keep job dirs, ffprobe path (default Remotion's bundled one), poll interval, bind address |

Docker: the build context is the **repository root**, matching `infra/compose.yml`
(`context: ..`, `dockerfile: renderer/Dockerfile`):

```bash
docker build -f renderer/Dockerfile -t reel-renderer .
docker compose --env-file .env -f infra/compose.yml build renderer   # verified: builds unchanged compose
```

The image (1.42 GB: Remotion's Debian/Chrome guidance, Chrome Headless Shell, DejaVu) runs as uid
10001, the same uid as `infra/Dockerfile.api`, so api and renderer can write each other's
directories on the shared volume; the host `output/` must be writable by uid/gid 10001. It also runs
under any other uid via compose `user:`. No model credentials are needed in the container.

## Integration steps for Member 1

1. Merge `feat/m4-scenes-renderer` (it already contains `d3dfba6`; only `backend/modules/scenes/`
   and `renderer/` differ). No contract, root manifest or lockfile change is needed: imports are
   `pydantic`, `httpx`, `langchain`, `langchain-openai`, all in the root `pyproject.toml`.
2. The API picks the module up via `backend.modules.scenes.service` (the coordinator's `STAGES`
   map); no core code change.
3. Compose: the existing `renderer` service works as is. Set `RENDER_WORKER_TOKEN` in `.env` (same
   value for api and renderer) and make sure the host `output/` is writable by uid 10001.
4. Mock deployment smoke test: `MOCK_MODE=true`, create a project, wait for six ready previews,
   send "Please correct scene six: make the packet diagram clearer", then Stitch. The same flow ran
   locally through `integration_check` against the compose-built image (results below).
5. Live: see the Nemotron limitations below. Recommended `Runtime.llm` change for Member 1 (not applied):
   `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` and `NEMOTRON_TIMEOUT_SECONDS≥300`.

## Acceptance results (2026-10-18, laptop)

Code as committed after merging `d3dfba6`. Every row was measured on the run it names.

| Check | Run | Result |
| --- | --- | --- |
| Standalone mock acceptance (`--mock --character-pngs`, 2 min 40 s) | `output/demos/scenes-final/demo-report-20261018-1609.json` | previews submitted `s03,s01,s06,s02,s05,s04` completed in that order, frames 273/270/270/270/270/447 = slot durations; routed edit s06 rev 1 → 2 with s01–s05 source hashes and timeline hash unchanged; canned broken model → a0, a1 rejected by the real validator → fallback in **a2** (`repair_attempts=2`, `FALLBACK:` warning), preview rendered; final 1800 frames, 1080×1920, 30/1, h264 `yuv420p`, aac, 60.01 s (39.5 s render); audio silent at 0.0 s / 8.9 s / 55 s, speech at 1.0 s / 50 s |
| **Core Coordinator → this module → compose-built worker image** | `output/demos/scenes-core/integration-report-20261018-1551.json` | core's own checks accepted all six builds/previews (`validate_build`, `validate_render`, artifacts, `-a0` job ids); `scene.ready` events arrived out of order (s02 first) with slots kept; `coordinator.edit` routed to s06 → rev 2, others unchanged, project revision 2; `coordinator.stitch` → manifest written by core, final completed, 1800 frames h264 `yuv420p` 1080 + aac; 155 progress events; frames inspected |
| **Live Nemotron scene (json_prompt)** | `output/demos/scenes-live3/live-report-20261018-1605.json` | s02 generated by the agent (`generation_mode=agent`, 0 repairs, 148 s), passed the real validator, 270-frame preview rendered; 3 word-backed cues citing `c002`; inspected: correct phone/relay diagram timed to the words, one text overlap in a caption box (guide rule added afterwards, not re-run). Ran with a standalone runtime with thinking disabled (see limitations) |
| Python tests | — | 72 passed; core suite 10 passed |
| Renderer tests / typecheck | — | 8 passed with `OLD_REEL` set (7 + 1 skipped without) / clean |
| Earlier evidence, still valid | `scenes-docker-full/demo-report-20261018-1537.json` | full mock path inside the Docker image (pre-merge build context) |

## Remaining limitations / blockers

- **Live generation through core's runtime times out (Member 1 change needed).** With the `.env` key,
  tiny requests answer in < 1 s, but the model spends its output on hidden reasoning; a full scene
  through core's `AppRuntime` hit the 180 s `NEMOTRON_TIMEOUT_SECONDS` (`MODEL_REQUEST_FAILED`).
  With `chat_template_kwargs.enable_thinking=false` the same request succeeds (see live row).
  Core owns `Runtime.llm`; suggested: that `extra_body` (or a setting for it) and a 300 s timeout.
- **Intermittent HTTP 500** (`Failed to generate completions`) from the NVIDIA endpoint on one
  full-size request; the identical request succeeded minutes later. It surfaces as a retryable
  `SCENE_AGENT_UNAVAILABLE`; a scene retry recovers.
- **Model JSON is sometimes malformed** (one reply string-escaped the `cues` array); the runtime's
  structured-output repair handles it, at the cost of an extra call.
- `tool_calling` mode (create_agent + ToolStrategy) is implemented but not yet run live.
- Only one live scene was generated; six-scene live quality, edits and live final are unverified.
- Real character PNGs are not in the repo; MOCK transparent PNGs exercise the image path.
- The edit router is pattern-based (accepted limitation, see backlog).

More: `doc/engineering-log.md`, `doc/backlog.md` in this directory.
