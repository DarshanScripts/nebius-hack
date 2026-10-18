# Member 1 platform

Branch: `feat/m1-platform`. Read root `context.md` and `plan.md` for the product and
frozen member interfaces. The canonical block in plan.md is materialized unchanged
in `contracts/models.py`; cross-field checks live in `contracts/validation.py`.
JSON Schemas are exported under `contracts/schema/`.

## Run locally

```bash
uv sync --python 3.12
# Copy .env.example to .env only if .env does not already exist.
uv run uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1
```

Python 3.11 is used in the API image; local checks ran on Python 3.12. The lockfile
covers the root declared Python range. Keep exactly one API process/worker for
file-backed state and in-process operation locks. Swagger is available at `/docs`.

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"topic":"How does WhatsApp voice calling infrastructure work?"}'
```

Project creation immediately returns HTTP 202 with six slots. The next GET/poll
returns partial state or a clear failed stage if a teammate module is unavailable.
Default API execution loads actual member modules in both mock and live mode.
There is no automatic replacement for a missing member implementation.

## Explicit fixture demo

```bash
uv run python -m scripts.demo_platform
uv run python -m scripts.export_schemas
uv run python -m pytest -q
```

The platform demo injects explicit research/dialogue/image/audio fixtures from
`backend/core/fixtures.py`. It writes twelve real silent PCM WAVs and mock word
timings; it does not generate human speech. It locks a complete 1800-frame timeline
then invokes Member 4's scene interfaces. Until that module is merged it reports
six `MODULE_UNAVAILABLE` errors while retaining completed content and the timeline.
The demo is a coordinator fixture, not a completed reel or live research run.

Measured fixture timeline: boundaries `[0,273,543,813,1083,1353,1800]`, final speech
end 1611, total speech 1440 frames. The focused tests inject scene/worker doubles
and verify progressive updates, revision guards, build/preview pairing, final
manifest capture, stale finals, failed edit preservation, artifact isolation,
restart recovery, and HTTP range serving. Test result artifacts are JSON fixtures;
these checks do not claim real Remotion encoding or GPU inference.

## Integration for Members 2, 3, and 4

Import shared models from `contracts.models`. Consume the exact async signatures
in plan.md. Stage functions return their declared completed Pydantic models or
raise `StageFailure(PipelineError(...))`. Module import errors fail only that stage.
Do not create/mutate snapshots or events; core owns persistence.

`Runtime.settings` uses **uppercase environment names**, e.g.
`runtime.settings["TAVILY_API_KEY"]`, `runtime.settings["VOICE_API_URL"]`.
It is server-only and includes unwrapped credentials; do not serialize it into
prompts, generated code, logs, render requests, or client responses. `Runtime.llm`
is a lazily configured LangChain ChatOpenAI instance; `Runtime.structured()` handles
the configured strategy and at most two JSON validation repairs. It ignores
reasoning fields and parses only final text/tool output.

Artifact keys are project-relative to `ARTIFACT_ROOT`, for example
`projects/<id>/research/attempt-<id>/raw.json`. Use runtime `write_json`/`write_bytes`
so writes are atomic and references include measured hashes/sizes. Repeating an
identical write is allowed; changing bytes at an existing key fails. Reuse completed
files on retry or select a new attempt path. In particular, research adapters must
persist/resume their own Tavily request ID before starting a replacement paid task.
Stage retry retains completed upstream snapshot bundles and resumes from the first
incomplete stage. Locked scene retries affect only one scene.

Call validation helpers in `contracts.validation` at your own boundaries; core
rechecks before publishing. Word-backed cue intervals use the span from the
earliest referenced aligned word start to the latest word end in scene-local
frames. Non-word-backed entrance/exit cues stay inside the slot.

Member 4's `render_preview` returns `ScenePreviewOutcome` containing the final
possibly repaired build and completed preview together. Worker job IDs are
`<operation_id>-a0`, `-a1`, or `-a2`; progress reports use the original operation ID.
Final render IDs are the manifest's exact job ID. Stale job callbacks are ignored.
All refs must point into the current project's namespace and match existing bytes.

## Model capability and cloud status

```bash
uv run python -m scripts.check_nemotron
```

This makes two small billable requests to the configured NVIDIA model (plain JSON,
then forced tool calling) and saves credential-free capability metadata. Both
requests returned HTTP 200 on 2026-10-18, and the local ignored `.env` selects
`tool_calling`. Native JSON Schema capability remains untested.

`infra/` provides API/web Dockerfiles, Nginx proxy, base Compose and a GPU overlay.
See `infra/README.md` for exact Docker build paths and current Nebius status.
The team GPU resource is a Jupyter Devlab, not a standalone Compute VM. Both
speech services passed live reference-WAV inference and word alignment on that
GPU; cloud API/render deployment and a live final video remain pending.
