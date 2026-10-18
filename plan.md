# Five-hour implementation plan

## 1. Read first and freeze these decisions

Read `context.md`, then your member assignment below, then the shared contracts. Your member number determines your branch and allowed files. **All four feature branches are now merged locally into `feat/m1-platform`; integration changes are not yet published.** See `agents.md` for the current verified state and remaining work. Sections describing unimplemented modules and a created Compute VM are historical build assignments: the team project currently has a running Jupyter Devlab and zero standalone Compute VMs. All five services now run directly on that Devlab behind Jupyter Server Proxy; the cloud editor created a live project, but no final live reel is complete. Do not create another GPU resource.

**Deliverable:** a topic creates a grounded, two-character educational reel. Six scenes generate concurrently and become previewable progressively. A message edits one scene. Stitch renders a 1080×1920, 30 fps, exactly 60-second MP4 on Nebius Cloud, including voice, captions, and moving character PNGs.

**Stack:** Python 3.11 + FastAPI + Pydantic v2 + LangChain + `langchain-openai` + `httpx`; React + Vite + TypeScript + plain CSS; Node 22 + Remotion 4 for rendering. Lock one compatible installed version set. Member 4 pins all Remotion packages to the identical exact version. Use npm, not several JS package managers. Member 1 maintains Python root dependencies; each module supplies its additional dependency list.

**Execution:** a deterministic Python scheduler calls stages. Independent scene agents use LangChain `create_agent` and a shared immutable context. There is no manager LLM, inter-agent messaging, or mandatory extra LangGraph workflow. Use three concurrent scene agents by default and one rendering job at a time initially to protect VM memory. Increase rendering concurrency only after observing the available VM.

**Timeline:** exactly six scene slots, twelve alternating dialogue turns, and 1800 total frames. Audio lengths determine scene boundaries. Once locked, a scene correction cannot alter dialogue, audio, global timing, theme, or adjacent scenes.

**UI:** collapsible project sidebar; center topic/message/activity/dialogue pane; right ordered scene previews; Stitch progress and final artifact link. Final playback in the editor is optional.

**Not required:** auth, billing, Instagram publishing, lip sync, background music, arbitrary duration/theme, Redis/Celery, Kubernetes, a vector database, object storage, or an autonomous cloud provisioning agent.

## 2. Ownership and branches

| Member | Branch | Exclusive implementation ownership |
| --- | --- | --- |
| 1: project owner/integrator | `feat/m1-platform` | `contracts/`, `backend/core/`, `backend/api/`, `backend/app.py`, `backend/__init__.py`, `backend/modules/__init__.py`, root Python manifests/lockfiles, root docs/env/gitignore/dockerignore, `infra/`, root `scripts/` |
| 2: content | `feat/m2-research-dialogue` | `backend/modules/content/` |
| 3: voice | `feat/m3-voice-alignment` | `backend/modules/voice/` |
| 4: visual generation/rendering | `feat/m4-scenes-renderer` | `backend/modules/scenes/`, `renderer/` |
| 5: editor | `feat/m5-editor-ui` | `frontend/` |

`main` is the integration branch and member 1 owns merges. Member 1 also develops on their feature branch. No one pushes directly to `main` except the owner integrating reviewed work. These branch names are assignments; this planning step does not create or push them.

Every module directory contains `README.md`, `dependencies.txt` where needed, `fixtures/`, and a runnable `demo` entry point. Generated runtime media belongs under ignored `output/`, not in tracked module source.

### Start in parallel without waiting for someone else's implementation

1. Member 1 publishes these planning/configuration files as the common starting commit. All five branches start from that commit. The canonical Pydantic code below is already specified; creating its files is transcription, not an interface design dependency.
2. Each coding agent can immediately extract the **single canonical model block** into ignored `.bootstrap/contracts/models.py` and create `.bootstrap/contracts/__init__.py`. Set `PYTHONPATH="$PWD/.bootstrap:$PWD"` for standalone development. Member 1 puts the same code in tracked `contracts/models.py` first. Remove the bootstrap path once that commit is available. Never commit a second copy of the schemas.
3. Module code imports only `contracts.models` and uses the `Runtime` protocol. It does not import another member's module, API globals, or persistence implementation. Standalone demos provide their own small fixture runtime implementing that protocol.
4. Everyone makes local fixtures from section 12. Backend and provider implementations may be absent. Member 5 uses a frontend mock API with the exact response shapes and poll behavior below.
5. Each member's first checkpoint is a fixture-driven slice in their owned directory. Production stage ordering does not impose team coding order.

Suggested extraction, run from the repository root after installing Pydantic in your development environment:

```bash
python - <<'PY'
from pathlib import Path
text = Path('plan.md').read_text()
block = text.split('\n<!-- CONTRACTS_START -->\n', 1)[1].split('\n<!-- CONTRACTS_END -->', 1)[0]
code = block.split('```python', 1)[1].split('```', 1)[0].strip() + '\n'
target = Path('.bootstrap/contracts')
target.mkdir(parents=True, exist_ok=True)
(target / '__init__.py').touch()
(target / 'models.py').write_text(code)
PY
```

### Merge procedure

```bash
git fetch origin
git switch -c feat/m2-research-dialogue origin/main
# Replace the branch name above with your assigned branch; create it only once.
# Work and commit only your owned paths.
git push -u origin feat/m2-research-dialogue
```

Before submitting: update from `origin/main`, resolve conflicts only in your own paths, and include commands, fixture output, environment requirements, and known limitations in your module README. Ask member 1 to resolve a shared-file conflict. Do not rewrite other members' directories to make integration pass. Commit chunks early; member 1 can merge usable contracts/adapters before final polish. Do not force push a branch being integrated.

Only member 1 changes contracts or root manifests. A required schema change is proposed with the field name and migration impact, then published by member 1 to every branch. Keep contract version `1.0` fixed during this build if at all possible.

## 3. Repository structure to implement

```text
contracts/models.py              # exact shared Python schemas/protocol below
backend/app.py                   # FastAPI app assembly, one worker process
backend/api/                     # HTTP endpoints; no provider implementation
backend/core/
  config.py                      # validated .env settings
  runtime.py                     # artifacts + structured Nemotron invocation
  repository.py                  # project snapshots and event persistence
  pipeline.py                    # deterministic stage calls and scene fan-out
  timeline.py                    # measured audio -> global frame allocation
backend/modules/content/         # member 2
backend/modules/voice/           # member 3
backend/modules/scenes/          # member 4 Python scene agent + worker client
renderer/                        # member 4 Node worker + Remotion scene kit
frontend/                        # member 5 Vite editor
infra/compose.yml                # member 1 cloud service wiring
infra/Dockerfile.api             # member 1
scripts/                        # member 1 setup/deploy/demo helpers
assets/characters/{sundar,jensen}.png
assets/voices/{sundar,jensen}/{reference.wav,reference.txt}
output/projects/<project_id>/    # ignored runtime artifacts
  inputs/characters.json         # copied input asset references
  research/{raw.json,bundle.json}
  script/v1/script.json
  images/v1/                    # copied/downloaded images for script revision 1
  voice/v1/d001/{audio.wav,transcript.txt,words.json,subtitles.srt}
  voice/v1/bundle.json
  timeline.json
  context.json                  # immutable, validated scene context
  scenes/s01/v1/<operation_id>/a0/{Scene.tsx,build.json,preview.mp4,poster.jpg}
  final/<job_id>/{manifest.json,reel.mp4,poster.jpg}
  snapshot.json
  events.jsonl
```

All artifact references are relative keys under `ARTIFACT_ROOT`, e.g. `projects/<id>/voice/v1/d001/audio.wav`. Never serialize a laptop absolute path. The API and renderer mount the same Nebius host directory as `/workspace/output`; inside both containers `ARTIFACT_ROOT=/workspace/output`. Paths are resolved through the runtime/worker and checked to stay within that root. Artifact serving must support browser byte-range requests for WAV/MP4 playback. If a script is regenerated before timeline lock, use `v2` for its script/images/voice outputs, preserving `v1`. A second research attempt likewise gets an attempt-specific directory; never overwrite an artifact already referenced by a saved bundle.

Copy character/voice inputs into a project's artifact namespace when the project starts so later asset replacements cannot change an existing reel. Empty character assets are acceptable placeholders in mock mode; require actual character PNGs before a live final render.

## 4. Member 1 — platform, contracts, timeline, integration, Nebius

**Branch:** `feat/m1-platform`. You own `main` integration. Your role contains no dialogue/scene prompt implementation.

Implement:

1. Materialize section 9 as `contracts/models.py`. Add the cross-field validators and reference checks listed after the block. This is the first small commit, made available immediately.
2. Root `pyproject.toml`/lockfile, core FastAPI/Pydantic/LangChain/httpx dependencies, and documented Python setup. Merge each member's module dependency fragment centrally. Base package imports must not fail simply because an unmerged feature module is absent; temporarily report `MODULE_UNAVAILABLE` for an unavailable route/stage.
3. `Settings` loading root `.env`; implement `Runtime`. Services read only their own settings and ignore unrelated shared-env fields; keep API/contract payload validation strict. `Runtime.structured()` uses the configured Nemotron endpoint, validates with Pydantic, and permits at most two corrective attempts after an invalid structured response. Read only the model's final answer, not reasoning text, into the parser. Do not hardcode an unverified Nemotron model ID.
4. In the first fifteen minutes, check the chosen endpoint/model's tool calling and structured output support. Prefer `ToolStrategy` for agent structured output when supported; `json_prompt` uses a normal model call plus `model_validate_json` and bounded repair. Native provider JSON Schema is used only after its actual support is confirmed. `json_prompt` still works if native schema support does not.
5. When tool calling is unavailable, member 4 runs a bounded generate → compile/render feedback → repair loop through the same Nemotron endpoint. Record this capability choice once; do not let agents select incompatible strategies independently.
6. Artifact read/write helpers: root traversal protection, atomic writes via temp file + rename, SHA-256 and byte counts, strict JSON serialization, and immutable versioned scene/final artifacts. Write the artifact before publishing its reference.
7. File-backed persistence for the hackathon: snapshot + append-only events per project, atomic snapshot replacement, per-project locks. All state mutations happen through the API process; modules return results/artifacts and do not edit `snapshot.json`. Run a single Uvicorn worker. No database or distributed queue is needed for this deployment.
8. API routes and snapshot/event responses in section 10. Track background asyncio tasks so exceptions update state. A scene failure must not cancel successful siblings. Never hold a request open for the full research/render job.
9. Pipeline: research → dialogue → image selection → voice → timeline → scene generation/preview fan-out. Publish results after each stage. Use `asyncio.as_completed` or equivalent so every completed scene becomes visible immediately. The six slots exist from creation and are keyed by scene index.
10. Deterministic timing and boundary calculation in section 7. LLMs may propose visual cues but cannot choose or modify scene lengths. Freeze script/audio/timeline before scene generation.
11. Edit endpoint: obtain structured intent from member 4's router, validate the scene, retain its context and audio, generate revision `current_revision + 1`, then replace only that scene after a successful preview. `render_preview` returns `ScenePreviewOutcome`; commit its final `build` and `render` together, because preview repair may have updated the source. Stale completions cannot overwrite a newer request. Keep the previous ready preview on failure.
12. Stitch endpoint: capture all current scene versions/context in an immutable manifest; call member 4's final-render client. Reject Stitch while a required scene is unready or being edited. Reject new edits during a final render. An edit accepted after a completed final marks that final as stale until stitched again.
13. Resume behavior: on API startup mark interrupted running jobs as failed/retryable while preserving finished artifacts. Stage retry reuses completed immutable upstream bundles, avoiding another paid research call. A failed preview retries only its scene. Implement the retry route below.
14. `infra/compose.yml`, `infra/compose.gpu.yml`, API Dockerfile, deployment instructions/scripts, and deployment to the **already-created single Nebius VM**. Co-locate API, renderer, frontend/proxy, Chatterbox, and WhisperX there. Use SSH user `orange_whisky`. The renderer Dockerfile is supplied by member 4, speech Dockerfiles by member 3, and frontend build by member 5. Prefer same-origin `/api` reverse proxy. Never bake `.env` into an image. Only member 1 deploys the integrated checkout; other members push their branches without overwriting the shared VM checkout.

**Input/output:** owns `ProjectCreate → ProjectSnapshot`, artifact serving, timeline generation, API/event schemas, and pipeline state. Consumes member 2/3/4 callable interfaces. Exposes no provider keys to browsers or renderer-generated code.

**Standalone acceptance:** create a mock project, receive an immediate ID and six slots, produce a complete 1800-frame timeline from fixture audio, demonstrate one out-of-order scene update and one targeted edit state change, then download an artifact. Live/cloud acceptance is the full demo in section 14.

## 5. Member 2 — research, grounded dialogue, relevant images

**Branch:** `feat/m2-research-dialogue`. Own only `backend/modules/content/`.

Export these async callables from `backend/modules/content/service.py`:

```python
async def run_research(request: ResearchRequest, runtime: Runtime) -> ResearchBundle: ...
async def generate_dialogue(request: DialogueRequest, runtime: Runtime) -> DialogueScript: ...
async def find_images(request: ImageRequest, runtime: Runtime) -> ImageBundle: ...
```

Implement:

1. Tavily REST adapter using `httpx`: `POST https://api.tavily.com/research` with topic/input, configured `model`, and `stream: false`; retain the returned `request_id`; poll `GET /research/{request_id}` until completed/failed or the configured deadline. Accept documented `pending`/`in_progress` and tolerate `processing` as a running status. Unknown status is an adapter error, not completion.
2. Retry transient network/429/5xx errors with bounded backoff and `Retry-After` where supplied. Auth/invalid-input errors fail immediately. Store the initial response and completed raw response without pretending our normalized schema is Tavily's own response shape. The completed raw JSON is the `raw_response` artifact; initial JSON can be a sibling `initial.json`.
3. Normalize the completed research into `ResearchBundle`: readable report, short summary, indexed sources, and citable claims. Index source URLs first, then use `ResearchNotes` for Nemotron normalization against those known source IDs when necessary. The report is usually `content: string`; if structured content is returned, preserve its raw object and convert it explicitly. Read `sources` defensively; favicon is optional. Usage is optional.
4. Grounding rules: prioritize official engineering/security documents and relevant standards. Separate documented product behavior, general industry practice, and inference. For WhatsApp, do not assert an undocumented exact codec/topology/region/vendor as fact. Every claim has at least one valid `source_id`; preserve caveats. A source appearing in the bundle is not automatic proof of any newly invented statement.
5. Dialogue generation uses `DialogueRequest` and LangChain/Pydantic structured output. Produce exactly 12 turns, ordered `d001`…`d012`, grouped as two turns per scene 1…6. Alternate `sundar`, `jensen`. Aim for **120–135 spoken words overall**, with a short hook, skeptical questions, concise explanations, a challenge/correction, and a closing takeaway. No stage directions in spoken text. Factual turns carry valid claim IDs. Questions may have none.
6. Support `previous_script` and `revision_instruction` so member 1 can request one shorter script if measured speech will not fit. New content receives a new `script_revision`; voice must then be regenerated before the timeline is locked. Ordinary scene edits never call this operation.
7. Separate image-query planning pass receives the full research and script. Nemotron returns `ImageQueryPlan`, with one targeted `ImageQuery` per scene, linked to that scene's two dialogue IDs. Search using Tavily `/search` with `include_images: true` and `include_image_descriptions: true`. Attempt all six queries; retain the most relevant usable result per scene when available. The goal is at least one relevant image in the project, with reuse where appropriate.
8. Normalize returned image URLs/descriptions; handle either image URL strings or image objects. Download usable images before handing them to rendering, verify they decode, and store them under project artifacts. Retain the original image URL, query, and source-page URL when actually known. Never invent a source page or licensing attribution. Limit download time/size and do not fetch local/private network addresses from model/search output.
9. No usable result for a scene returns `asset: null`, `status: "unavailable"`, and a reason. This is nonfatal: member 4 draws a vector diagram. Failure of image search must not discard completed research/script.
10. Mock mode returns deterministic, visibly marked fixture content with no provider calls. README includes each CLI invocation, expected artifacts, and dependency fragment. Never modify core pipeline/API code yourself.

**Output artifacts:** raw Tavily JSON, normalized research bundle, script JSON, query/selection JSON, downloaded images. The UI receives research before dialogue because these are separate callables.

**Standalone acceptance:** fixture input yields valid grounded claims, 12 alternating turns assigned to six scenes, and six image selections including an unavailable-image case. A live research run is retrievable by saved request ID and does not silently restart after a polling interruption.

## 6. Member 3 — voice adapter, transcription, precise alignment

**Branch:** `feat/m3-voice-alignment`. Own only `backend/modules/voice/`.

Export from `backend/modules/voice/service.py`:

```python
async def synthesize_dialogue(request: VoiceRequest, runtime: Runtime) -> AudioBundle: ...
```

Implement:

1. **Selected provider: self-hosted Chatterbox Turbo on a Nebius GPU VM, followed by self-hosted WhisperX forced alignment.** Implement internal `synthesize(text, character, settings) → raw audio`. Own both speech-service source directories, dependency locks, and Dockerfiles under `backend/modules/voice/gpu_services/{chatterbox,whisperx}/`. Keep their Python/CUDA dependencies in separate containers; member 1 supplies their deployment Compose wiring under `infra/`. The main API requires only the speech HTTP client and audio-file processing dependencies; do not merge the services' conflicting Torch/CUDA/WhisperX environments into the API's root dependency lock.
2. Load each character's copied reference WAV and condition Chatterbox with `audio_prompt_path`. Use `ChatterboxTurboTTS.from_pretrained(device="cuda")`, load once per worker, and generate each requested line using the matching reference. No per-character training or hosted voice IDs are required. Reference transcript files can remain for provenance but Turbo does not need them for this flow. Read secrets on the server only. Do not confuse reference speech with the dialogue to synthesize.
3. Produce one WAV per dialogue turn, preserving `dialogue_id`, speaker, script revision, and exact intended text. Normalize to **48,000 Hz, mono, PCM signed 16-bit WAV**. Use `.wav`, not `.wave`. Measure duration from decoded sample counts; do not estimate it from the script.
4. **Word-level alignment is required, not optional.** After final audio processing, send the exact normalized WAV and its intended transcript to WhisperX. Use `load_align_model(language_code="en", device="cuda")` and `whisperx.align` with a segment covering that clip and the known transcript. WhisperX internally resamples its analysis audio to its expected sample rate; the returned offsets still refer to the same clip in seconds, then convert them to integer milliseconds. Full Whisper ASR is optional for detecting synthesis/text mismatches; do not require ASR or speaker diarization just to align a known speaker's script. Never replace measured timing with evenly distributed estimates.
5. The normalized public result has integer **clip-local milliseconds** and stable word IDs such as `d001_w001`. `words.json` is canonical; `.txt` and `.srt` are convenience outputs. Retain provider timing separately if conversion was needed. Word offsets do not include any global scene/reel offset.
6. Finalize all normalization, silence trimming, or bounded audio speed changes **before** producing canonical timing. If modifying audio after alignment, realign or apply a measured exact transform and revalidate. Never return timestamps for a different WAV.
7. Read section 7's duration budget. Sum frame-rounded utterance lengths. If over budget, a single uniform speed-up of at most 1.08× is allowed if intelligible; then update audio and timing. If still too long, raise `AUDIO_DURATION_OUT_OF_RANGE` with measured total and desired budget. Member 1 asks member 2 to shorten the script once and reruns voice. Do not chop spoken endings.
8. Add only trailing silence up to the next frame boundary so each WAV has `frame_count * 1600` samples at 48 kHz/30 fps. Do not add inter-turn gaps into each WAV; member 1 owns those in the global timeline. `duration_ms` describes the padded audio; words end before it.
9. If ASR/aligner omits meaningful words or produces a different transcript, return a recoverable alignment error; do not silently animate against different text. Allow punctuation/tokenization differences, but preserve readable words and the mapping to the dialogue.
10. Mock mode generates deterministic WAV tones/silence and synthetic alignment, with `timing_quality: "mock"`. This supports the full editor/render path before voice selection. Live mode requires `"provider"` or `"forced_alignment"` quality and intelligible speech. Missing providers return clear errors; no automatic fake-voice fallback in live mode.

**Output:** `AudioBundle` with twelve `UtteranceAudio` entries, twelve WAVs, transcripts, `words.json` files and SRTs. Concurrency for voice requests can be small/bounded; no cross-member orchestration is needed.

### Speech service contracts — member 3 implements both

These are **our own service endpoints**, callable on a Nebius private network or forwarded ports for development. No OpenAI/Resemble hosted speech key is required. `VOICE_API_KEY` and `ALIGNMENT_API_KEY` are team-generated bearer secrets protecting the respective routes. Configure the same values on callers and service containers. Use public checkpoint downloads without a separate model-hub account/token; English forced alignment does not require gated speaker diarization models. Pin a release that supports unauthenticated loading and persist its model caches on the Nebius GPU VM.

| Endpoint | Request | Response |
| --- | --- | --- |
| `POST :8002/v1/tts` | Bearer `VOICE_API_KEY`; multipart `text`, `dialogue_id`, `model=chatterbox-turbo`, and uploaded `reference_audio` WAV | `audio/wav` bytes at the model's native sample rate; caller decodes/measures and normalizes |
| `POST :8003/v1/align` | Bearer `ALIGNMENT_API_KEY`; multipart `audio` containing final normalized WAV, `dialogue_id`, `transcript`, `language=en` | JSON `AlignmentResult` below, with word offsets against that exact upload |
| `GET :8002/health`, `GET :8003/health` | — | Readiness including model-loaded status, never credentials |

Upload file bytes, not an API container's filesystem path: speech services do not depend on a shared artifact mount even though they run on the same host. Pin compatible package/CUDA versions per container, install FFmpeg as needed, and persist model caches. The actual GPU is an **RTX PRO 6000 with 96 GB VRAM (Blackwell)**. Select PyTorch/CUDA binaries with support for that GPU, and compatible torchaudio/CTranslate2/cuDNN versions for the pinned WhisperX release. Do not blindly install upstream's older Torch pin if it lacks this GPU's kernels. Member 1 serializes whole speech pipelines with `SPEECH_GPU_PIPELINE_CONCURRENCY=1`; each speech service bounds active requests to one. Measure actual model memory, then retain/unload models accordingly. Do not provision another GPU as part of a module's work.

WhisperX receives the final waveform after any speed adjustment and frame padding. Include `audio_sha256` in its response so the caller can verify it matches the uploaded canonical WAV. Word IDs use `<dialogue_id>_w001`, etc. Omitted or unaligned meaningful words produce `ALIGNMENT_INCOMPLETE` and a bounded retry/error rather than guessed timings. Numbers/acronyms should be written in their intended spoken form in the original dialogue when needed for clear speech and alignment.

Example `words.json` contents for an illustrative utterance; times below show the format and are not measured live values:

```json
{
  "dialogue_id": "d001",
  "audio_sha256": "<SHA-256 of the exact final WAV>",
  "transcript": "How does calling work?",
  "words": [
    {"word_id": "d001_w001", "text": "How", "start_ms": 80, "end_ms": 240},
    {"word_id": "d001_w002", "text": "does", "start_ms": 250, "end_ms": 390},
    {"word_id": "d001_w003", "text": "calling", "start_ms": 410, "end_ms": 790},
    {"word_id": "d001_w004", "text": "work?", "start_ms": 810, "end_ms": 1100}
  ]
}
```

Member 4 uses those word IDs for cues such as drawing a packet when “calling” begins, then highlighting the receiving phone at “work”. Section 7 converts milliseconds into global and scene-local frames. This format supports per-word captions and timed diagram movement without giving the scene agent authority to invent speech timing.

**Standalone acceptance:** both character mappings work with fixtures, all WAVs decode with the required format, word times are monotonic and within the matching clip, audio and timing revisions match, and the measured total fits the budget or produces the specified error.

## 7. Shared timing, visual layout, and scene continuity

### Global timing rules — member 1 implements; members 3/4 consume

- Fixed video: 1080×1920, 30 fps, 1800 frames. Every frame range is **half open** `[start_frame, end_frame)`; duration is `end_frame - start_frame`. Remotion's inclusive render `frameRange` becomes `[start_frame, end_frame - 1]` at the worker boundary.
- WAVs are frame-padded by member 3. A frame is 1600 samples at 48 kHz. Do not repeatedly round floating-point seconds.
- Reserve 15 frames before the first utterance. Add 6 silent frames between the two turns inside a scene, and 24 silent frames between successive scene groups. Reserve at least 30 frames after the final utterance.
- There are six internal 6-frame gaps and five 24-frame scene gaps. Speech budget is therefore `1800 - 15 - 6*6 - 5*24 - 30 = 1599 frames`, or **53.3 seconds**, using the sum of padded utterance frame counts. Aim for about 49–53 seconds of speech. Extra unused frames hold the final summary visual and silence; final duration is still exactly one minute.
- Allocate utterance start/end frames sequentially from the measured clips, inserting those gaps. Preserve the script order. No simultaneous speech in this version.
- Between scene groups, put the scene cut at the midpoint of the 24-frame silence: 12 frames after the previous group's audio ends. Thus the previous scene has 12 silent exit frames and the next scene has 12 silent entry frames. Scene 1 starts at frame 0; scene 6 ends at 1800. No scene gaps or overlaps.
- Example: if a group's final utterance ends at frame 275, the next scene begins at 287 and its first speech begins at 299. The previous scene owns exit frames `[275,287)` and the next scene owns entrance frames `[287,299)`.
- A word event converts clip-local milliseconds using its utterance's global frame start: `global_start = utterance_start_frame + floor(start_ms*30/1000)` and `global_end = utterance_start_frame + ceil(end_ms*30/1000)`, clamped to that utterance. Validate at least one visible frame when a cue needs it. For a scene-local cue subtract the scene's `start_frame`.
- Member 1 creates a canonical `Timeline`, hashes its canonical JSON, and freezes it before dispatch. Every scene task/build records that hash. Reject a build for another timeline or script revision.

### Fixed video theme — member 4 implements once

| Item | Exact rule |
| --- | --- |
| Canvas | 1080×1920; origin at top left; coordinates are unscaled video pixels |
| Background | `#FFFFFF`, dots `#D8DEE8`, 24 px spacing, 1 px radius, full canvas |
| Workboard | `x=0, y=0, width=1080, height=1344` |
| Character region | `x=0, y=1344, width=1080, height=576`, clipped |
| Persistent topic title | `x=72, y=120, width=936, height=120`; shorten display title if needed |
| Scene content bounds | `x=72, y=288, width=936, height=816` |
| Caption bounds | `x=72, y=1152, width=936, height=144`, at most two lines |
| Character boxes | Sundar `x=48`, Jensen `x=612`; both `y=1344, width=420, height=576`; contain, bottom aligned |
| Main ink / secondary | `#111827` / `#64748B` |
| Accent colors | blue `#2563EB`, green `#16A34A`, orange `#EA580C`; consistent meanings |
| Typography | bundled/system-installed DejaVu Sans; no network font fetch during rendering; board labels at least 36 px |
| Layers | background → board → captions → characters; reserve regions so they do not cover each other |

Coordinates are our design choices, not an assertion of Instagram's exact overlay-safe area. Keep important information away from outer edges and platform controls. Use 9:16 as supported by Meta's Reels guidance; 1080×1920 is this project's chosen high-resolution canvas.

### Smooth boundaries and persistent characters

The **global shell** owns dot background, topic title, captions, character positioning, and audio. Generated scene code owns only workboard content inside the scene content bounds. It cannot redraw/reset the character or audio layer.

Every scene has identical start/end boundary state: **clear scene-content area**, with the same global shell. Animate board opacity from 0 to 1 over the first 12 scene frames and back to 0 over the last 12. The worker applies this outer envelope centrally; agents must not override it. The two adjacent half-fades occur during the allocated speech gap, without overlapping video timelines or shortening the reel. Agent code keeps its own animation in the interior interval `[12, duration_frames-12)`.

Characters use global utterance timing, independent of scene component mounts: Sundar enters from the left and Jensen from the right during `[turn_start-8, turn_start)`, remains while speaking, and exits during `[turn_end, turn_end+8)`. Clamp to video bounds; overlap of entrances/exits is allowed. Same-speaker adjacent turns, if ever supported later, should stay in place. Do not restart character animations at scene cuts. Object-fit and clipping keep all PNG pixels in the bottom 30%.

Captions come from actual aligned words and global offsets; show small phrase chunks, with the active word highlighted. Scene agents can add diagram/numeric highlights keyed to those same word IDs. A shared caption component prevents each scene from implementing slightly different timing.

Use `useCurrentFrame`, `interpolate`, and deterministic Remotion springs. No CSS keyframe timers, `setTimeout`, wall-clock time, unseeded randomness, browser network fetches, or a GSAP ticker inside generated scenes. The same frame must always produce the same image. Remotion documents this requirement for reliable rendering.

## 8. Member 4 — independent scene agents, edit routing, Remotion worker

**Branch:** `feat/m4-scenes-renderer`. Own `backend/modules/scenes/` and `renderer/`.

Export from `backend/modules/scenes/service.py`:

```python
async def route_edit(request: EditRoutingRequest, runtime: Runtime) -> EditIntent: ...
async def generate_scene(request: SceneTask, runtime: Runtime) -> SceneBuild: ...
async def render_preview(request: PreviewRequest, runtime: Runtime) -> ScenePreviewOutcome: ...
async def render_final(request: FinalRenderRequest, runtime: Runtime) -> RenderResult: ...
```

Implement the Python side:

1. `SceneTask` contains the full immutable context plus its one scene slot, revision, optional previous build, and correction instruction. Create one isolated agent invocation per scene. It can inspect research, the whole dialogue, image choices, audio alignment, timeline, theme, and the assigned scene's exact start/end frames.
2. Use LangChain `create_agent` with Nemotron and narrowly scoped tools such as `read_scene_context`, `read_previous_source`, `validate_scene_source`, and `submit_scene`. Tool access is to that task's artifacts only. No API/global-project mutations or access to neighboring scene outputs.
3. Supply a checked-in `scene_authoring.md` with the full theme/coordinate system, Remotion component API, timestamp rules, boundary rules, import allowlist, and a small working example. This is the shared Remotion skill/context all six runtime agents receive. Do not depend on an unspecified external skill being installed.
4. Agent output is `SceneDraft`: a full TypeScript/React module for one visual scene, summary, and timing cues. Save its source as a versioned `Scene.tsx` artifact, validate it, and return `SceneBuild`. The same shared Pydantic output model is used for every scene; instances differ, not schemas.
5. Compile/type-check the module in the renderer before accepting it. Provide compiler/render errors to that scene's repair loop, with at most two corrective attempts total across compilation and preview; carry the count in `SceneBuild.repair_attempts`. Preview repair uses the same scene context and previous candidate source without changing audio or slots, then returns the final build and completed preview together in `ScenePreviewOutcome`. Member 1 commits both. Return a stage error or use the declared deterministic fallback template if exhausted; mark `generation_mode: "fallback"` and explain it. Do not report failed generated code as successful generated output.
6. Prefer a diagram such as phones → signaling → audio packets → receiving phone, with motion/highlights at meaningful words. Figures specific to the topic must reference claim IDs. Do not fabricate latency/user/traffic numbers for visual interest.
7. Edit router accepts “scene six”, “scene 6”, or an explicitly selected scene ID, returns `edit_scene` plus exactly one valid ID and instruction, or `unsupported` with an explanation. It never executes the change itself. For ambiguous multi-scene/global/audio edits, ask the user to select one scene or create a new reel; do not silently choose a target.
8. For an edit, pass the previous source and precise instruction to that scene's agent. Keep context/timeline hashes and boundary contract fixed. Update only that revision's files. A fresh invocation with previous source is sufficient; no persistent hidden agent process or cross-scene memory is needed.

Implement the Node worker and Remotion side:

1. `renderer/package.json`, lockfile, `src/scene-kit.tsx`, `src/Reel.tsx`, `src/ScenePreview.tsx`, `src/index.ts`, `src/worker.ts`, and `renderer/Dockerfile`. Pin matching `remotion`, `@remotion/renderer`, and `@remotion/bundler` versions. Install Chromium and needed system fonts/libraries following Remotion's Docker documentation.
2. Small authenticated internal HTTP server. `POST /jobs` accepts `PreviewRequest | FinalRenderRequest`, discriminated by `kind`, and returns `202 {"job_id":"...","status":"queued"}`. `GET /jobs/{job_id}` returns `RenderResult`. `POST /validate` accepts a candidate `PreviewRequest`, compiles/type-checks its source, and returns `SourceValidationResult` without video encoding. `GET /health` returns readiness. The Python client polls jobs asynchronously and enforces the render deadline. Use `Authorization: Bearer <RENDER_WORKER_TOKEN>` for job and validation endpoints in live deployment.
3. Run rendering jobs from a bounded queue. `RENDER_CONCURRENCY=1` initially. `POST /jobs` must be fast; no encoding inside the request handler. Idempotency: identical job ID + identical input returns the same job; conflicting reuse is rejected.
4. Scene source contract:

```tsx
import React from 'react';
import {interpolate} from 'remotion';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  // props.frame is SCENE-LOCAL. The wrapper supplies the 936×816 content area.
  // Return deterministic visual content; global shell/audio/captions are external.
  return <div>{props.slot.index}</div>;
}
```

`SceneProps` contains `frame: number`, `durationInFrames: number`, `slot: SceneSlot`, `context: SceneContext`, and `cues: AnimationCue[]`. The content wrapper's origin is the top-left of the 936×816 scene content area; geometry generated by the agent is relative to that area. `frame = global_frame - slot.start_frame`. Global context positions stay in video pixels.

5. Allow only `react`, `remotion`, and the adjacent `./scene-kit` module in generated imports. Provide image/diagram helpers in that kit. Copy the kit and validated module into an isolated job bundle. Generated code cannot add packages, run shell commands, read secrets, or make network requests. Build/render in a child process with timeout, no model credentials, and only project assets available. Keep worker control/process privileges separate from generated source.
6. All external images, character PNGs, fonts, and audio must be local before render. Resolve `ArtifactRef.key` via the checked shared artifact root and pass worker-local/static asset URLs to Remotion. Bundler `publicDir` and `staticFile`/local HTTP asset serving must refer to the same job asset manifest. Generated modules receive resolved asset helpers; they never use laptop paths.
7. Preview renders one assigned scene with the **same shell, character timing, captions, and audio** used by the final composition. Offset preview frames to global frames, clip audio to the scene range, and include only the scene's duration. Preview frame 0 represents `slot.start_frame`. Return MP4 + poster and measured frame count.
8. Final rendering loads all six latest validated source artifacts, orders by `slot.index`, places them at their fixed frame ranges, and adds each dialogue WAV exactly once on the global timeline. Render **one master composition**, H.264 MP4 with AAC audio, yuv420p, 1080×1920, 30 fps, 1800 frames. Avoid concatenating independently encoded preview MP4s; they are review artifacts, not the final source of truth.
9. Keep all scene components on the same global shell/coordinate system. Do not use overlapping transitions that reduce total duration or duplicate audio. Section 7's centralized boundary fades provide continuity without changing the timeline.
10. Write output before returning completed status. `RenderResult.progress` is 0–1; relay real encoder progress. Preserve diagnostic artifacts on failure. The final output path is `projects/<id>/final/<job_id>/reel.mp4`. Final stitching entails rendering/encoding and must run on the Nebius worker in the cloud demo.
11. Distinguish the coordinator's scene operation ID from worker attempt IDs. `SceneTask.job_id` and the original `PreviewRequest.job_id` are the operation ID stored in `SceneState.active_job_id`. For worker submission, derive `<operation_id>-a<repair_attempts>` as the job ID; preserve that ID in the returned `RenderResult`. Call `runtime.report_progress` with the original operation ID so core can check whether it is still active. Save source/output under the corresponding `a0`, `a1`, or `a2` directory. Never overwrite an earlier attempt or resubmit changed input under the same worker job ID. An explicit user retry gets a fresh operation/job ID.

**Standalone acceptance:** from fixtures, render one preview and a 60-second master composition; generate/repair a scene with the configured Nemotron mode; edit scene six without changing its timing or scene five; and demonstrate persistent PNG/caption/audio behavior at a scene boundary. A deterministic fallback is available for a single exhausted scene, with visible metadata.

## 9. Canonical Pydantic v2 contracts

Member 1 materializes this block as `contracts/models.py`. Other members may extract the exact block into ignored bootstrap files as described above. Field names and literal values are frozen. Python defaults are filled when writing serialized JSON. Use `model_dump(mode="json")`; all API/artifact JSON uses snake_case and UTF-8.

These are application contracts. They are **not** schemas for arbitrary raw Tavily, voice-provider, or NVIDIA responses. Adapters perform that translation.

<!-- CONTRACTS_START -->
```python
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, TypeVar
from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(Model):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str


class ArtifactRef(Model):
    key: str                       # Relative to ARTIFACT_ROOT; no ../ or absolute path.
    media_type: str
    sha256: str                     # 64 lowercase hex characters.
    size_bytes: int = Field(ge=0)


class VideoSpec(Model):
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps: Literal[30] = 30
    duration_frames: Literal[1800] = 1800
    scene_count: Literal[6] = 6


class ThemeSpec(Model):
    theme_id: Literal["notebook_v1"] = "notebook_v1"
    background: Literal["#FFFFFF"] = "#FFFFFF"
    dot_color: Literal["#D8DEE8"] = "#D8DEE8"
    dot_spacing: Literal[24] = 24
    dot_radius: Literal[1] = 1
    workboard_height: Literal[1344] = 1344
    character_region_y: Literal[1344] = 1344
    font_family: Literal["DejaVu Sans"] = "DejaVu Sans"
    boundary_frames: Literal[12] = 12


SpeakerId = Literal["sundar", "jensen"]


class CharacterSpec(Model):
    character_id: SpeakerId
    display_name: str
    image: ArtifactRef | None = None
    voice_reference: ArtifactRef | None = None
    reference_transcript: str | None = None
    voice_id: str | None = None


class ProjectCreate(Model):
    topic: str = Field(min_length=5, max_length=1000)
    language: Literal["en"] = "en"


class ResearchRequest(Envelope):
    topic: str


class Source(Model):
    source_id: str                 # src001, src002, ...
    title: str
    url: str
    favicon: str | None = None


class Claim(Model):
    claim_id: str                  # c001, c002, ...
    text: str
    source_ids: list[str] = Field(min_length=1)
    evidence_type: Literal["documented", "general_industry_practice", "inference"]
    caveat: str | None = None


class ResearchNotes(Model):
    summary: str
    claims: list[Claim]
    uncertainties: list[str] = Field(default_factory=list)


class ResearchBundle(Envelope):
    topic: str
    tavily_request_id: str
    summary: str
    report_markdown: str
    sources: list[Source]
    claims: list[Claim]
    uncertainties: list[str] = Field(default_factory=list)
    raw_response: ArtifactRef
    is_mock: bool = False


class DialogueTurn(Model):
    dialogue_id: str               # d001 ... d012
    order: int = Field(ge=1, le=12)
    scene_index: int = Field(ge=1, le=6)
    speaker_id: SpeakerId
    text: str = Field(min_length=1)
    intent: Literal["hook", "question", "answer", "challenge", "takeaway"]
    claim_ids: list[str] = Field(default_factory=list)


class DialogueScript(Envelope):
    script_revision: int = Field(ge=1)
    title: str
    language: Literal["en"] = "en"
    turns: list[DialogueTurn] = Field(min_length=12, max_length=12)


class DialogueRequest(Envelope):
    research: ResearchBundle
    characters: list[CharacterSpec] = Field(min_length=2, max_length=2)
    script_revision: int = 1
    previous_script: DialogueScript | None = None
    revision_instruction: str | None = None


class ImageQuery(Model):
    scene_index: int = Field(ge=1, le=6)
    dialogue_ids: list[str]
    query: str
    reason: str


class ImageQueryPlan(Model):
    queries: list[ImageQuery] = Field(min_length=6, max_length=6)


class ImageSelection(Model):
    query: ImageQuery
    status: Literal["selected", "unavailable"]
    asset: ArtifactRef | None = None
    image_url: str | None = None
    source_page_url: str | None = None
    description: str | None = None
    reason: str | None = None


class ImageRequest(Envelope):
    research: ResearchBundle
    script: DialogueScript


class ImageBundle(Envelope):
    script_revision: int
    selections: list[ImageSelection] = Field(min_length=6, max_length=6)


class VoiceRequest(Envelope):
    script: DialogueScript
    characters: list[CharacterSpec] = Field(min_length=2, max_length=2)
    max_speech_frames: Literal[1599] = 1599


class WordTiming(Model):
    word_id: str                   # e.g. d001_w001
    text: str
    start_ms: int = Field(ge=0)    # Clip-local, after final audio processing.
    end_ms: int = Field(ge=0)


class AlignmentResult(Model):
    dialogue_id: str
    audio_sha256: str
    transcript: str
    words: list[WordTiming] = Field(min_length=1)


class UtteranceAudio(Model):
    dialogue_id: str
    speaker_id: SpeakerId
    wav: ArtifactRef
    transcript: str
    transcript_file: ArtifactRef
    words_file: ArtifactRef
    srt_file: ArtifactRef
    duration_ms: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    sample_rate_hz: Literal[48000] = 48000
    channels: Literal[1] = 1
    sample_count: int = Field(gt=0)
    words: list[WordTiming] = Field(min_length=1)
    timing_quality: Literal["provider", "forced_alignment", "mock"]


class AudioBundle(Envelope):
    script_revision: int
    utterances: list[UtteranceAudio] = Field(min_length=12, max_length=12)
    total_speech_frames: int = Field(gt=0)


class TimedUtterance(Model):
    dialogue_id: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)


class SceneSlot(Model):
    scene_id: str                  # s01 ... s06
    index: int = Field(ge=1, le=6)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    dialogue_ids: list[str] = Field(min_length=2, max_length=2)
    entry_state: Literal["clear_content"] = "clear_content"
    exit_state: Literal["clear_content"] = "clear_content"


class Timeline(Envelope):
    script_revision: int
    video: VideoSpec = Field(default_factory=VideoSpec)
    utterances: list[TimedUtterance] = Field(min_length=12, max_length=12)
    scenes: list[SceneSlot] = Field(min_length=6, max_length=6)


class SceneContext(Envelope):
    research: ResearchBundle
    script: DialogueScript
    images: ImageBundle
    audio: AudioBundle
    timeline: Timeline
    characters: list[CharacterSpec]
    theme: ThemeSpec = Field(default_factory=ThemeSpec)
    timeline_hash: str
    context_hash: str


class AnimationCue(Model):
    cue_id: str
    word_ids: list[str] = Field(default_factory=list)
    start_frame: int = Field(ge=0)  # Scene-local, not global.
    end_frame: int = Field(gt=0)
    description: str
    claim_ids: list[str] = Field(default_factory=list)


class SceneDraft(Model):
    source_code: str
    summary: str
    cues: list[AnimationCue] = Field(default_factory=list)


class SourceValidationResult(Model):
    valid: bool
    diagnostics: list[str] = Field(default_factory=list)


class SceneBuild(Envelope):
    scene_id: str
    revision: int = Field(ge=1)
    context_hash: str
    timeline_hash: str
    source: ArtifactRef             # Complete validated Scene.tsx.
    summary: str
    cues: list[AnimationCue] = Field(default_factory=list)
    generation_mode: Literal["agent", "fallback", "mock"]
    repair_attempts: int = Field(default=0, ge=0, le=2)
    warnings: list[str] = Field(default_factory=list)


class SceneTask(Envelope):
    job_id: str
    context: SceneContext
    slot: SceneSlot
    revision: int = Field(ge=1)
    previous_build: SceneBuild | None = None
    edit_instruction: str | None = None


class PreviewRequest(Envelope):
    kind: Literal["scene_preview"] = "scene_preview"
    job_id: str
    context: SceneContext
    slot: SceneSlot
    build: SceneBuild


class FinalRenderRequest(Envelope):
    kind: Literal["final"] = "final"
    job_id: str
    project_revision: int
    context: SceneContext
    builds: list[SceneBuild] = Field(min_length=6, max_length=6)


class PipelineError(Model):
    code: str
    stage: str
    message: str
    retryable: bool = False
    scene_id: str | None = None


class RenderResult(Envelope):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: float = Field(ge=0, le=1)
    video: ArtifactRef | None = None
    poster: ArtifactRef | None = None
    duration_frames: int | None = None
    error: PipelineError | None = None


class ScenePreviewOutcome(Envelope):
    build: SceneBuild
    render: RenderResult


class StageFailure(Exception):
    def __init__(self, error: PipelineError):
        self.error = error
        super().__init__(error.message)


class EditRequest(Model):
    message: str = Field(min_length=1, max_length=4000)
    scene_id: str | None = None
    expected_scene_revision: int | None = None


class EditRoutingRequest(Envelope):
    message: str
    scene_ids: list[str]
    selected_scene_id: str | None = None


class EditIntent(Model):
    action: Literal["edit_scene", "unsupported"]
    scene_id: str | None = None
    instruction: str
    reason: str | None = None


class SceneState(Model):
    scene_id: str
    index: int
    slot: SceneSlot | None = None  # None until audio timeline is locked.
    status: Literal["pending", "generating", "rendering", "ready", "failed"] = "pending"
    current_revision: int = 0     # Last successfully previewed revision.
    requested_revision: int = 1
    active_job_id: str | None = None
    progress: float = Field(default=0, ge=0, le=1)
    build: SceneBuild | None = None
    preview: RenderResult | None = None
    error: PipelineError | None = None


class ProjectSnapshot(Envelope):
    topic: str
    project_revision: int = 1
    mode: Literal["mock", "live"]
    status: Literal[
        "created", "researching", "scripting", "finding_images", "voicing",
        "planning", "generating_scenes", "ready", "rendering", "completed", "failed"
    ]
    created_at: str                # UTC ISO 8601.
    updated_at: str
    active_job_id: str | None = None
    research: ResearchBundle | None = None
    script: DialogueScript | None = None
    images: ImageBundle | None = None
    audio: AudioBundle | None = None
    timeline: Timeline | None = None
    scenes: list[SceneState] = Field(min_length=6, max_length=6)
    final: RenderResult | None = None
    final_project_revision: int | None = None
    final_is_stale: bool = False
    error: PipelineError | None = None


class ProjectSummary(Envelope):
    topic: str
    status: str
    updated_at: str
    mode: Literal["mock", "live"]


class ProjectEvent(Envelope):
    event_id: int                  # Monotonically increasing per project.
    at: str
    type: str                     # Names enumerated in section 10.
    scene_id: str | None = None
    revision: int | None = None
    message: str
    progress: float | None = None


class EventPage(Model):
    events: list[ProjectEvent]
    next_after: int


T = TypeVar("T", bound=BaseModel)


class Runtime(Protocol):
    mock_mode: bool
    artifact_root: Path
    settings: Mapping[str, Any]    # Server-only configuration.
    llm: Any                      # Configured LangChain chat model for create_agent.

    def path(self, key: str) -> Path: ...

    async def write_bytes(
        self, key: str, data: bytes, media_type: str
    ) -> ArtifactRef: ...

    async def write_json(self, key: str, value: Any) -> ArtifactRef: ...

    async def structured(
        self, *, messages: list[dict[str, str]], schema: type[T]
    ) -> T: ...

    async def report_progress(
        self, *, project_id: str, job_id: str, stage: str,
        progress: float, scene_id: str | None = None
    ) -> None: ...
```
<!-- CONTRACTS_END -->

### Required validators/checks to add around these models

Member 1 owns shared validation helpers in `contracts/validation.py`. Each stage validates its output before publishing it; member 1 validates again at integration boundaries. Member 4 implements the corresponding worker checks for renderer input. No consumer should rely on a prompt alone to enforce these rules.

Module callables return completed validated stage outputs or raise `StageFailure(PipelineError(...))`. Do not return an untyped error dictionary in place of the declared model. `render_preview` and `render_final` await worker completion asynchronously; `queued`/`running` results are intermediate worker states, not their successful return values. Member 1 maps exceptions to snapshot/events. Member 4's worker client calls `runtime.report_progress` after each poll: stage `scene_preview` with the scene ID, or `final` with no scene ID. Member 1 implements this method to update progress/events only if the operation/job is still active; standalone fake runtimes use a no-op implementation. Scene progress goes in `SceneState.progress`; do not replace the last ready `preview` with an in-flight result. Final progress goes in the project's current `final` render result. This keeps persistence owned by core and avoids another callback or wire schema.

- IDs are unique and reference the same project. Sources/claims/dialogue/image references must resolve. Twelve turn IDs/orders are contiguous; `(order-1)//2 + 1` equals `scene_index`; speakers alternate, beginning with Sundar. There are exactly two distinct character specs, one per ID.
- Every factual turn references the corresponding research claims. Unknown IDs are rejected and repaired. A genuine question can have no claim IDs. `inference` has a nonempty caveat.
- Six image selections cover indices 1…6 once each and reference the two turns in their scene. Selected images require an actual `asset` and original `image_url`; unavailable selections require a reason and no asset.
- Voice has one clip for each script turn with matching speaker/revision. Words are ordered, have positive lengths, unique IDs, and fit the actual WAV. `sample_count == frame_count * 1600`. `duration_ms` is rounded from the measured samples. `total_speech_frames` equals the clip sum and is at most 1599 before timeline creation. Mock timing cannot enter a live scene context.
- Timeline has positive ranges, ordered utterances, no overlapping speech, the exact specified gaps, and six contiguous scene ranges covering `[0,1800)`. Each clip fits its scene; the two dialogue IDs in every slot match the script. The first and last boundary are fixed.
- Hash canonical JSON with sorted object keys, compact separators, UTF-8. `timeline_hash` hashes `Timeline.model_dump(mode="json")`; `context_hash` hashes the whole scene context payload with its `context_hash` field omitted, including `timeline_hash`. No expiring URLs/secrets go into it. Builds/preview/final manifests must match that context and timeline.
- Scene-local cues have `0 <= start_frame < end_frame <= slot_duration`; word IDs belong to that scene's dialogue. Their timings must derive from the matching words or explicitly describe an untimed entrance/exit. Do not let an LLM change authoritative audio offsets.
- Artifact keys cannot be absolute or escape the artifact root. Verify referenced source/media assets exist and match hashes before rendering. No arbitrary filesystem URL may be supplied through a generated source/image reference.
- `RenderResult.status == "completed"` requires `video`, no error, and the expected frame count: slot duration for preview, 1800 for final. Failed results require an error. A ready scene requires a successful preview for its current build/revision.
- `EditIntent.action == "edit_scene"` requires a valid single `scene_id`. A provided selected scene wins unless the message explicitly conflicts; return unsupported in that conflict. Enforce revision preconditions before accepting edits.

### TypeScript contracts

Member 1 exports JSON Schema from the Pydantic models into `contracts/schema/`. Member 5 maintains only the editor-used TypeScript interfaces in `frontend/src/types/contracts.ts`; member 4 maintains the renderer-used equivalents in `renderer/src/types/contracts.ts`. Both mirror the same snake_case JSON fields. Do not introduce a second backend schema or rename fields to camelCase on the wire. JSON Schema is a reference/export artifact, not an added code-generation framework dependency.

## 10. API and event contract — member 1 implements, member 5 consumes

Base URL is `/api` on deployment; local frontend uses `VITE_API_BASE_URL` plus `/api`. No provider is called from the browser. JSON errors use `{"error": <PipelineError>}`; invalid request bodies use the same envelope with code `VALIDATION_ERROR` and HTTP 422.

| Method/path | Request | Response / behavior |
| --- | --- | --- |
| `GET /api/health` | — | `{"status":"ok","mode":"mock"}`; diagnostics can additionally list configured capabilities without keys |
| `POST /api/projects` | `ProjectCreate` | 202 `ProjectSnapshot`; initial six pending slots and background pipeline job |
| `GET /api/projects` | — | `{"projects": [ProjectSummary, ...]}` sorted by most recently updated |
| `GET /api/projects/{id}` | — | 200 `ProjectSnapshot`, including all current partial results |
| `GET /api/projects/{id}/events?after=0` | event cursor | 200 `EventPage`; `next_after` is last returned ID or unchanged cursor |
| `POST /api/projects/{id}/edits` | `EditRequest` | 202 updated `ProjectSnapshot`, or 422 unsupported/ambiguous; 409 stale revision/busy scene/render |
| `POST /api/projects/{id}/retry` | `{"stage":"research"}` etc., optional `"scene_id":"s03"` | 202 `ProjectSnapshot`; reuse finished upstream data, retry the first failed relevant operation |
| `POST /api/projects/{id}/stitch` | `{}` | 202 `ProjectSnapshot` in rendering state; 409 if scenes/timing are unready or another render is active |
| `GET /api/artifacts/{key:path}` | validated relative key | bytes with correct media type, range support, and useful download filename |

Retry stage literal values: `research`, `dialogue`, `images`, `voice`, `scenes`, `final`. Reject unsupported values. Research polling retry resumes a stored Tavily request ID before starting another task. Retrying an upstream stage invalidates all dependent artifacts/state; only allow this explicit retry when failed, before scenes are locked. Scene retry requires a scene ID and does not invalidate siblings. Final retry uses the latest unchanged manifest if its input revision is still current.

Initial creation example, abbreviated only for explanatory readability: `scenes` in the actual response contains all six entries.

```json
{
  "schema_version": "1.0",
  "project_id": "<uuid>",
  "topic": "How does WhatsApp voice calling infrastructure work?",
  "project_revision": 1,
  "mode": "mock",
  "status": "created",
  "created_at": "<UTC ISO timestamp>",
  "updated_at": "<UTC ISO timestamp>",
  "active_job_id": "<uuid>",
  "research": null,
  "script": null,
  "images": null,
  "audio": null,
  "timeline": null,
  "scenes": [
    {
      "scene_id": "s01",
      "index": 1,
      "slot": null,
      "status": "pending",
      "current_revision": 0,
      "requested_revision": 1,
      "active_job_id": null,
      "progress": 0,
      "build": null,
      "preview": null,
      "error": null
    }
  ],
  "final": null,
  "final_project_revision": null,
  "final_is_stale": false,
  "error": null
}
```

**Polling, not SSE, is the required transport:** while a job is active, poll snapshot and event endpoints every second using the cursor. Stop/back off when idle; resume after edits/Stitch. Events are lightweight activity records; the latest snapshot is authoritative and contains typed bundles. This avoids inventing untyped nested event payloads. Event IDs and stage outputs survive a refresh. Return 404 for an unknown project.

Event names: `project.created`, `research.started`, `research.ready`, `dialogue.ready`, `images.ready`, `voice.started`, `voice.ready`, `timeline.ready`, `scene.started`, `scene.code_ready`, `scene.rendering`, `scene.ready`, `scene.failed`, `edit.accepted`, `render.started`, `render.progress`, `render.completed`, `stage.failed`. Scene events contain scene ID/revision. A `scene.ready` event appears immediately after that preview is committed. UI placement is by scene index, never completion order.

**Revision lifecycle:** initial scene generation requests revision 1 while current revision is 0. A successful preview commits current revision 1. An edit with `expected_scene_revision: 1` requests revision 2; the old preview remains available while rendering. Commit revision 2 only if its operation ID is still active and its context hash matches. A failed edit preserves revision 1, restores status `ready`, clears the active job, resets `requested_revision` to the current revision, and retains the error for the activity/UI; an initial failure without a previous preview remains `failed`. A second edit to the same busy scene returns 409; edits to different scenes may run concurrently. Versioned artifacts also contain operation/attempt IDs so failed/retried revision numbers never overwrite a file.

The frontend should send selected scene and expected revision when available. For free text without a selection, the backend routes the message and validates the target before scheduling. `project_revision` increments when a new edit is accepted; snapshot progress changes alone do not increment it. `final_project_revision` records the revision captured by Stitch.

## 11. Member 5 — editor frontend

**Branch:** `feat/m5-editor-ui`. Own only `frontend/` including its package/lock/config files.

Implement:

1. Vite + React + TypeScript with plain CSS. Root frontend config uses `envDir: ".."` to read only `VITE_API_BASE_URL` from the shared env. No Next.js server, component framework, or frontend LLM integration is needed.
2. `src/api/client.ts` typed wrapper around section 10. `src/api/mock.ts` implements the same interface and deterministic delayed transitions when `?mock=1` is selected for frontend-only development. Display a mock indicator; this mode is separate from server mock mode and never submits paid requests.
3. Three-pane desktop workspace. Left: collapsible reel/project list, selected project, New. Center: topic input when creating, then chronological activity with collapsible research/sources, 12 dialogue turns, and later each turn's audio/transcript/timing details. Keep these updates associated by `dialogue_id`, rather than appending duplicate turn cards.
4. Right: six numbered placeholders from project creation, progress state per slot, playable MP4 preview and poster when ready, scene title/summary and current revision, selectable scene target. Reserve fixed slots so out-of-order completion never rearranges scene numbers.
5. Message composer works for scene corrections. If scene six is selected, send its ID and current revision alongside the message. Show queued/running state for the target, retain the previous preview, then replace its source URL on success. Versioned artifact paths prevent stale browser caching. Handle 409 and unsupported edits with a short useful message.
6. Poll active project/events once per second. Merge snapshot state by IDs, deduplicate activity by event ID, and discard responses for previously selected projects. Refresh restores the selected project from its ID and persisted API state. Do not assume all stages finish in one response.
7. Stitch is enabled only when all six scene previews are ready and no required jobs are active. Show actual final-render progress and a Download MP4 link when complete; show stale-final status after a later edit. Embedding the final reel is optional.
8. Use the backend artifact URL resolver: `${API_BASE}/api/artifacts/${key}` with each path segment URL-encoded. Do not use filesystem paths or assume assets live in frontend public. A preview's audio is already included; avoid playing extra audio simultaneously.
9. Clear empty/loading/error states, readable source links, compact dialogue timing display, stable column widths, and scrollable panes. Favor useful controls over visual effects. A laptop demo is the primary target; collapse panes to tabs on narrower screens if time permits.
10. `npm run dev`, `npm run build`, and a README with screenshots or reproduction steps for progressive mock updates and a scene edit. No backend code edits; request API/schema changes through member 1.

**Standalone acceptance:** mocked research → dialogue → audio updates appear; scenes complete in order `3,1,6,2,5,4` but remain placed `1…6`; editing scene 6 updates only it; Stitch shows progress and a download link; a refresh can restore backend-backed project state once integrated.

## 12. Deterministic fixtures and independent demos

Each member owns fixtures in their directory and implements a tiny fake `Runtime` for their standalone demo. Reuse this recipe so fixtures line up across modules; do not wait for paid provider access. Member 1 assembles the integrated fixture snapshot from the same recipe.

- Project ID: `demo-whatsapp-001`; mode/mock flags set explicitly.
- Two character IDs: `sundar`, `jensen`; mock PNGs may be absent and rendered as labeled silhouette placeholders. Live project IDs are UUIDs.
- Sources: `src001` and `src002` with `https://example.com/mock-source-1` and `https://example.com/mock-source-2`; titles explicitly start with “Mock”. Claims `c001`…`c006` are fixture statements marked as demonstration data, not a completed real WhatsApp research result.
- Turn `d001`…`d012`: `order = 1…12`, `scene_index = (order-1)//2 + 1`; odd Sundar, even Jensen. Use coherent short fixture questions/answers; do not imply invented fixture facts are verified findings. Answer turns reference `c001`…`c006` respectively.
- Each dialogue WAV has exactly **120 frames = 192000 samples = 4000 ms**. Twelve clips give **1440 speech frames**, satisfying the 1599-frame ceiling. Split each fixture line into words and assign explicitly mock, ordered clip-local timings inside 4000 ms.
- With the prescribed gaps, the last utterance ends at frame **1611**. Scene boundaries are **`[0,273,543,813,1083,1353,1800]`**. The final scene holds its takeaway during the remaining silence. These are fixture values only; live durations are computed from live WAVs.
- Six image queries. At least one available local fixture image in a demo can be a generated simple diagram; mark it mock. Include one unavailable selection to exercise vector fallback. Never download required fixture assets at render time.
- Scene source fixtures are deterministic Remotion modules using the same kit. Their artifact hashes/byte sizes must be calculated from real local files, not dummy hashes. Member 4 provides the simplest diagram template immediately.
- Fake preview completion order is `s03, s01, s06, s02, s05, s04`. Frontend-only mocks may use local placeholder videos, explicitly mock. A backend-integrated mock run should render real previews/MP4 through Remotion so the rendering path is exercised.

Required module entry points after implementation:

```bash
python -m backend.modules.content.demo --mock --output output/demos/content
python -m backend.modules.voice.demo --mock --output output/demos/voice
python -m backend.modules.scenes.demo --mock --output output/demos/scenes
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1
```

`--mock` controls external inference/content, not whether Remotion can produce an actual local MP4. Each demo creates all artifacts it references and describes how to connect to the renderer. Commands in this plan are targets to implement, not claims that they work in the current planning-only repository.

## 13. Nebius deployment and configuration

**Deploy to the existing single VM, not a new CPU/GPU pair.** The owner reports VM creation complete and is waiting for it to become active. No SSH connection or deployment has been performed in this planning step. Member 1 verifies Running status, the actual VM ID/name, assigned public/private addresses, and SSH before deploying.

| Deployment setting | Value |
| --- | --- |
| Final console review name | `cyan-ape-instance-8` |
| Project / region | `group08-project`, `project-e05mfttbln00ypf4h123rz`, `uk-south2` |
| Platform / preset | `gpu-rtx6000-a`, `1gpu-24vcpu-218gb` |
| Hardware | 1 NVIDIA RTX PRO 6000, 96 GB VRAM, 24 vCPUs, 218 GiB RAM |
| Boot image / disk | `ubuntu24.04-cuda13.0`, encrypted 1.25 TiB network SSD |
| SSH user | `orange_whisky` |
| Subnet / security group | `vpcsubnet-e05xggeet8sf02btby` / `vpcsecuritygroup-e05s1hk66ypwqtswpn` |
| Attached service account | `group08-sa` (name; not a supplied service-account ID or API credential) |
| SSH private key | Owner's ignored `.ssh/nebius_reel_ed25519`; absolute path already recorded in local `.env` |
| Host addresses | Pending; leave `.env` address fields empty until supplied |

The pasted Terraform preview names `maroon-carp-instance-6`, while the final review names `cyan-ape-instance-8`. Treat the latter as the intended name and confirm the existing instance in the console. Do not apply the older snippet or create a duplicate. This is an existing infrastructure handoff, not a request to modify the VM size, disk, or service account.

All five containers run on this VM. Chromium rendering uses CPU resources; only Chatterbox/WhisperX receive GPU device access. Keep rendering concurrency at one and speech pipeline concurrency at one initially. The GPU is Blackwell; the speech images need compatible GPU kernels, independently pinned Python environments, and a real inference readiness check. The host CUDA image and container CUDA/PyTorch versions are separate compatibility concerns. Member 3 chooses/releases its compatible container dependencies; member 1 supplies Docker/NVIDIA Container Toolkit access and verifies each container can see the GPU.

```text
Browser
  → web/proxy on the existing Nebius VM
  → api/FastAPI on the same VM
      → Tavily API
      → NVIDIA hosted Nemotron API
      → chatterbox :8002 (GPU) → normalized WAV → whisperx :8003 (GPU)
      → renderer :8001 (CPU)
          → shared /workspace/output volume with api
```

**Compose contract:** service names `api`, `renderer`, `web`, `chatterbox`, and `whisperx`; API internally on 8000, renderer on 8001, Chatterbox on 8002, and WhisperX on 8003. All services join the same Compose project/network. API/renderer share the output volume. `web` proxies `/api` to `api:8000` and serves built frontend files. Public ingress is needed for the web/proxy and owner SSH. Keep service-to-service traffic internal and retain bearer-token authentication. Do not expose model credentials in the renderer container.

Compose overrides the local endpoint defaults for `api`:

```dotenv
RENDER_WORKER_URL=http://renderer:8001
VOICE_API_URL=http://chatterbox:8002/v1/tts
ALIGNMENT_API_URL=http://whisperx:8003/v1/align
ARTIFACT_ROOT=/workspace/output
```

Member 1 makes these runtime overrides in Compose rather than telling every teammate to rewrite local `.env`. Service DNS names resolve inside the Compose network; local development uses the localhost defaults with matching SSH forwards when calling remote services.

Build the deployed frontend with an empty `VITE_API_BASE_URL` so it uses the same origin; the local `.env.example` value targets localhost for development. Vite embeds this value at build time, so changing only a running container's environment does not change an already built frontend.

Member 4's renderer Dockerfile follows Remotion's official Debian/Node/Chromium guidance. Member 5 supplies the frontend build. Member 1 owns the final Compose/proxy configuration and health-check/startup order. Use the local equivalent for development; cloud rendering has the same request/response contract.

Member 1 also owns `infra/compose.gpu.yml`: it adds `chatterbox` and `whisperx` to the same Compose project using member 3's Dockerfiles, GPU access, persistent caches, and their bearer secrets. The target deployment command, to implement once those files exist, is `docker compose -f infra/compose.yml -f infra/compose.gpu.yml up -d --build` from the integrated repository root. Configure root `.env` loading explicitly; Compose files live under `infra/`, so do not rely on accidentally finding an `infra/.env`. `NEBIUS_VM_HOST` and `NEBIUS_GPU_VM_HOST` will both point to this VM's SSH address. Publish any developer-only service port on host loopback and use SSH forwarding when needed.

### Immediate tasks while the VM starts

- **Member 1:** publish the docs/contracts seed, start API fixtures, prepare Compose and scripts. Once an IP arrives, set both host fields, SSH as `orange_whisky`, check the existing driver/GPU, set up Docker GPU access, and deploy only the merged checkout. Keep secrets/key files out of the image build context via a root `.dockerignore`.
- **Member 2:** implement research, script, and image modules using the configured NVIDIA Nemotron endpoint and fixtures. No VM/SSH dependency.
- **Member 3:** start both speech containers and lock dependencies for the actual Blackwell GPU. Coordinate with member 1 for the first real synthesize → align run; save evidence of real word timestamps. No new VM provisioning.
- **Member 4:** implement source generation, scene kit, worker, and fixture MP4 locally. The renderer remains CPU-based on deployment. No GPU dependency for authoring/layout work.
- **Member 5:** build the editor with mocked stage/scene updates. Target same-origin `/api` when deployed; no VM/SSH dependency.

Once the public address is available, the owner's connection command is:

```bash
ssh -i .ssh/nebius_reel_ed25519 orange_whisky@<VM_PUBLIC_IP>
```

The private key exists only on the owner's machine; teammates use fixture development and their assigned branches. The actual IP, instance ID, service readiness, and driver compatibility are still pending verification. The final review does not establish what ingress rules exist inside the selected security group; member 1 checks SSH/web reachability when the VM is Running.

No object storage is required because both services share a durable Nebius disk. Keep final MP4s and source/timing artifacts across container restarts. If moving to multiple render VMs later, add artifact transfer/object storage behind `ArtifactRef`; do not attempt that expansion during this build.

### Environment ownership

Root `.env.example` lists all agreed names without credentials. The owner's ignored `.env` contains the supplied NVIDIA/Tavily keys and generated internal service secrets. Member 1 merges additional names only when a selected provider demonstrably needs them.

| Variables | Owner/use |
| --- | --- |
| `TAVILY_API_KEY`, research model/poll/deadline | Member 2: Tavily research/search |
| `NEMOTRON_BASE_URL`, `NEMOTRON_API_KEY`, `NEMOTRON_MODEL`, structured mode/timeout | Member 1 config/runtime; members 2/4 consume runtime |
| `VOICE_API_URL`, `VOICE_API_KEY`, `VOICE_MODEL`, device/timeout | Member 3 Chatterbox service/client; key is our bearer secret |
| `ALIGNMENT_API_URL`, key/model/device/timeout | Member 3 WhisperX service/client; mandatory word alignment |
| `WHISPERX_TRANSCRIBE`, ASR model/compute type | Member 3 optional transcription quality check; known-script alignment is the default |
| `TORCH_HOME` | Persistent Torch cache; also persist the libraries' default model-download caches |
| `SPEECH_GPU_PIPELINE_CONCURRENCY` | Member 1 serializes voice/alignment pipelines across projects |
| `RENDER_WORKER_URL`, token, timeout, render concurrency | Members 1/4 service boundary |
| `ARTIFACT_ROOT`, `ASSETS_ROOT`, API host/public URL, frontend origin | Member 1 platform |
| `VITE_API_BASE_URL` | Member 5; public URL only |
| `NEBIUS_VM_HOST`, `NEBIUS_GPU_VM_HOST`, SSH user/key path | Member 1 deployment inputs; both hosts identify the existing single VM; user is `orange_whisky` |
| `NEBIUS_VM_NAME`, region/project/subnet/security group/service-account name | Recorded infrastructure metadata; do not create duplicate resources from it |

**Selected inference configuration:** `NEMOTRON_BASE_URL=https://integrate.api.nvidia.com/v1`, `NEMOTRON_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b`. The owner has populated its NVIDIA key, the Tavily key, and generated internal bearer secrets in local `.env`; keys are intentionally absent from these shared docs and `.env.example`. Member 1 still checks model/tool availability against this account. Inference credentials, VM SSH credentials, and cloud IAM credentials are distinct. Modules consume `Runtime.llm`/`Runtime.structured` and do not instantiate a hardcoded alternative endpoint.

`VOICE_API_URL` and `ALIGNMENT_API_URL` will point to **our Chatterbox and WhisperX FastAPI services**, with the exact contracts in section 6; these services have not yet been implemented/deployed by this planning step. They do not require NVIDIA NIM, a Resemble hosted API key, or an OpenAI Whisper API key. The Nebius VM already exists in the owner's project; deployment uses SSH. Do not pass a broad Nebius IAM credential into application containers merely to call these services. `NEMOTRON_API_KEY` is currently the NVIDIA hosted inference key. Keep mock mode available for teammates; the cloud API uses live mode once its configured services are ready.

## 14. Five-hour checkpoints and definition of done

| Time from start | All members work concurrently toward this checkpoint |
| --- | --- |
| 0–15 min | Member 1 publishes canonical schemas/settings and checks model capabilities; everyone starts owned directories from fixture contracts; owner adds PNGs/reference WAVs; VM is already created, awaiting IP/startup |
| 15–60 min | Each member delivers a runnable fixture slice; API returns progressive mock state; UI handles it; renderer produces one real fixture scene preview; voice emits valid mock WAV/timing |
| 60–120 min | Live research/dialogue/image search; selected live voice adapter/alignment; scene agent generates one valid scene; Nebius worker container is rendering |
| 120–180 min | Merge module slices; full mocked pipeline plus at least one live content/audio run; all six scene jobs publish progressively; targeted edit round trip works |
| 180–240 min | Full live topic → six previews → corrected scene → cloud-rendered 60-second final MP4; fix boundary/caption/audio/layout problems |
| 240–270 min | Stabilize retries, stale revisions, missing-image fallback, and download; freeze contracts/features |
| 270–300 min | Rehearse with cached successful artifacts; preserve live run evidence and final MP4; fix only demo blockers |

If VM startup/checkpoint download is delayed, keep member 3's Chatterbox/WhisperX adapters and mock flow working while member 1 resolves deployment to the existing VM. Report that live voice is pending; do not present a tone fixture as a finished voice demo. If arbitrary scene generation is unreliable, keep the shared deterministic diagram template and bounded per-scene agent repairs; preserve individual editability and record fallback use. These choices preserve integration without hiding which live capabilities are working.

### Required acceptance evidence before final integration

- A source-backed WhatsApp topic run with raw Tavily result, indexed sources, claim IDs, and generated dialogue.
- Twelve speaker-mapped WAVs and transcripts, real word timing, correct sample/frame counts, and a timeline covering exactly 1800 frames.
- A screenshot or event trace showing previews finishing out of order while slots remain ordered.
- A “correct scene six” request with revision before/after and unchanged scene 1–5 source hashes, audio hashes, and timeline hash.
- A final MP4 from the Nebius renderer, 1080×1920, 30 fps, 1800 frames, audible dialogue, captions, character slide animations, and no duplicate/missing speech at joins. Check stream metadata and visually/audibly inspect a scene boundary.
- Refresh restores state; a failed image uses a diagram; a failed scene preserves other ready scenes; final render progress and download work.

These are focused implementation acceptance checks to perform while building. The planning deliverable itself does not run provider jobs, deploy cloud resources, or execute application tests.

### Handoff prompt for each coding agent

```text
Read context.md and plan.md. I am member <1|2|3|4|5>.
Implement exactly that member's assigned scope on its assigned branch.
Use the frozen contracts, fixtures, ownership boundaries, and callable/API names.
Start from fixtures immediately; do not wait for other modules or paid APIs.
Do not edit another member's directories or change shared field names.
Deliver runnable code, a module README with commands and evidence, and push your branch.
Report any shared-contract change to member 1 before applying it.
```

## 15. References checked for this plan

- [Tavily Create Research Task](https://docs.tavily.com/documentation/api-reference/endpoint/research): asynchronous initial response; model and structured output configuration.
- [Tavily Get Research Task Status](https://docs.tavily.com/documentation/api-reference/endpoint/research-get): polling, completed content/sources, optional usage. Initial/completed examples are also saved in `reqc.md`.
- [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search): image inclusion and image descriptions.
- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output): `create_agent`, tool/provider strategies, Pydantic validation, and `structured_response`.
- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents): agent/tool execution; the selected Nemotron endpoint still needs a capability check.
- [Nebius Token Factory quickstart](https://docs.tokenfactory.nebius.com/quickstart) and [API reference](https://api.tokenfactory.nebius.com/docs): OpenAI-compatible inference base URL and model listing.
- [Chatterbox](https://github.com/resemble-ai/chatterbox) and [Turbo loader](https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/tts_turbo.py): reference-conditioned GPU synthesis with public checkpoint loading.
- [WhisperX](https://github.com/m-bain/whisperX), [known-transcript alignment](https://github.com/m-bain/whisperX/issues/939), and [English alignment model mapping](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py): GPU alignment for word timestamps; full transcription/diarization is not required for the known-script flow.
- [Nebius GPU VM types](https://docs.nebius.com/compute/virtual-machines/types): choose deployed GPU capacity from the team's region/quota.
- [NVIDIA framework support matrix](https://docs.nvidia.com/deeplearning/frameworks/support-matrix/index.html) and [GPU compute capabilities](https://developer.nvidia.com/cuda/gpus): confirm Blackwell-compatible speech container dependencies for the selected RTX PRO 6000.
- [Nebius SSH connection guide](https://docs.nebius.com/compute/virtual-machines/connect): use the configured VM username and the matching private SSH key.
- [Remotion Docker](https://www.remotion.dev/docs/docker), [rendering](https://www.remotion.dev/docs/render), and [flickering/determinism](https://www.remotion.dev/docs/flickering): separate Node renderer, browser requirements, and frame-driven animation.
- [Meta Reels guidance](https://www.facebook.com/business/ads/facebook-instagram-reels-ads): vertical 9:16 video with audio and important content kept in safe areas. 1080×1920 is the selected project resolution; layout margins in this plan are project design choices.
- [infra_peter](https://github.com/aditya-ladawa/infra_peter): reference README's Python/LangGraph research-to-reel approach. This plan does not depend on its runtime or claim its internal source was audited.
