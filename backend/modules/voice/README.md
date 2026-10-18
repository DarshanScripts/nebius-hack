# Voice module (member 3)

`synthesize_dialogue(VoiceRequest, Runtime) -> AudioBundle` in `service.py`: 12 dialogue turns -> 12 normalized WAVs
+ transcripts + **measured word timestamps** (`words.json`, `subtitles.srt`) + `bundle.json`.
Live mode = our Chatterbox Turbo service (:8002) then our WhisperX forced-alignment service (:8003).
Mock mode = deterministic tones + synthetic timing, `timing_quality: "mock"`, no services needed.
Branch `feat/m3-voice-alignment` includes the member 1 platform seed `d3dfba6` (real `contracts/`).

## Run

```bash
uv sync && uv pip install numpy python-multipart pytest   # numpy: see "Integration" (not yet in the root lock)
export PYTHONPATH="$PWD"
python -m backend.modules.voice.demo --mock --output output/demos/voice --clean
python -m backend.modules.voice.demo --live --env .env --assets assets --output output/demos/voice   # needs both services
python -m pytest backend/modules/voice/tests -q                                                       # 49 tests
```

The demo prints per-clip frames/words and runs `validate.py` (WAV format, sha256/size of every file, ordered
in-clip word times, `sample_count == frame_count*1600`, total <= 1599). Mock output: 12 x 120 frames = 1440, matching the
plan's fixture recipe. `--live` strips the `MOCK FIXTURE:` prefix and needs `assets/voices/{sundar,jensen}/reference.wav`
(each longer than 5 s; Chatterbox rejects shorter prompts with a 422).

## Environment

Read from `runtime.settings` (upper-case names, as provided by member 1's runtime):

| Variable | Used by | Notes |
| --- | --- | --- |
| `VOICE_API_URL`, `VOICE_API_KEY`, `VOICE_MODEL`, `VOICE_TIMEOUT_SECONDS` | API-side client | key = our bearer secret, also given to the Chatterbox container |
| `ALIGNMENT_API_URL`, `ALIGNMENT_API_KEY`, `ALIGNMENT_TIMEOUT_SECONDS` | API-side client | key also given to the WhisperX container |
| `VOICE_DEVICE`, `VOICE_REF_CACHE` | Chatterbox container | `cuda` in production; reference conditioning cached per sha256 |
| `ALIGNMENT_MODEL`, `ALIGNMENT_DEVICE`, `WHISPERX_TRANSCRIBE`, `WHISPERX_ASR_MODEL`, `WHISPERX_COMPUTE_TYPE` | WhisperX container | ASR is an optional mismatch check; known-script alignment is the default |
| `TORCH_HOME`, `HF_HOME` | both containers | persistent model caches under `/models` |

## Live pipeline (per `service.py`)

1. Synthesize each turn (Chatterbox, reference WAV per speaker, seed `order*100+attempt`) -> resample to 48 kHz mono ->
   trim silence (keeps 50 ms lead / 120 ms tail) -> level-normalize (-20 dBFS RMS, peak <= -1 dBFS, short fades).
   Audio of implausible length (<0.12 s or >1.5 s per word + 3 s) is regenerated.
2. Pick **one** uniform speed (pitch-preserving WSOLA, 0.005 steps, max 1.08x) only if the total exceeds 1599 frames; otherwise
   `AUDIO_DURATION_OUT_OF_RANGE` (message contains `measured_frames=` and `budget_frames=`) **before** any alignment call.
3. Pad each clip with trailing silence to `frame_count*1600` samples, encode PCM16, send that exact WAV to WhisperX.
4. Verify `audio_sha256`, map aligner words onto the script's tokens (every meaningful word must be covered, punctuation /
   split-token differences tolerated), clamp to ordered positive in-clip ms. Failure -> one resynthesis of that clip, then a
   retryable `ALIGNMENT_INCOMPLETE`/`ALIGNMENT_LOW_CONFIDENCE`/`ALIGNMENT_TEXT_MISMATCH`.
5. Write `projects/<id>/voice/v<rev>/<dialogue_id>/{audio.wav,transcript.txt,words.json,subtitles.srt,alignment_raw.json}`
   and `voice/v<rev>/bundle.json`. Artifacts are immutable (the platform runtime refuses changed bytes at an existing key):
   a retry first **reuses** a complete, still-valid bundle for that revision, otherwise writes to `voice/v<rev>/attempt-<n>/`.

Error codes (all `StageFailure`, stage `voice`): `VOICE_REQUEST_INVALID`, `VOICE_REFERENCE_MISSING|MISMATCH`, `VOICE_AUTH_FAILED`,
`VOICE_UNAVAILABLE` (retryable), `VOICE_NOT_CONFIGURED`, `VOICE_REJECTED`, `VOICE_AUDIO_INVALID`, `VOICE_SILENT_AUDIO`,
`VOICE_IMPLAUSIBLE_AUDIO`, `AUDIO_DURATION_OUT_OF_RANGE`, `ALIGNMENT_*`. Live mode never falls back to fake audio.
Write numbers/acronyms in spoken form in the script and avoid `[tags]`: the text is both spoken and aligned verbatim.

## GPU services (`gpu_services/{chatterbox,whisperx}/`)

| Service | Endpoint | Notes |
| --- | --- | --- |
| Chatterbox Turbo `:8002` | `POST /v1/tts` (Bearer `VOICE_API_KEY`; multipart `text, dialogue_id, model, reference_audio`, optional `seed`) -> `audio/wav` PCM16 at native 24 kHz; `GET /health` | one active synthesis; conditioning cached per reference sha256; fails closed if key unset |
| WhisperX `:8003` | `POST /v1/align` (Bearer `ALIGNMENT_API_KEY`; multipart `audio, dialogue_id, transcript, language=en`) -> `AlignmentResult` + extra `quality{mean_score,min_score,...}`; `GET /health` | known-script forced alignment only; `WHISPERX_TRANSCRIBE=true` adds an ASR similarity check |

Both load their model in a background thread at startup and report `status: loading|ok|error` plus the GPU name on
`/health`; loading includes a real inference smoke test. **Build context is the repository root**, matching
`infra/compose.gpu.yml`:

```bash
docker build -f backend/modules/voice/gpu_services/chatterbox/Dockerfile -t reel-chatterbox .
docker build -f backend/modules/voice/gpu_services/whisperx/Dockerfile   -t reel-whisperx .
```

Dependencies are locked **independently** with `uv pip compile` for Python 3.11 / linux x86_64 (`requirements.in` ->
`requirements.txt`, `--exclude-newer 2026-10-11`): torch/torchaudio **2.8.0+cu128** (CUDA 12.8 wheels with Blackwell sm_120
kernels). `chatterbox-tts` 0.1.7 pins `torch==2.6.0` (no Blackwell kernels), so the Dockerfile installs it `--no-deps` on top of the
lock. `setuptools<81` is pinned because Chatterbox's watermarker (`resemble-perth`) imports `pkg_resources`; with setuptools 84
it silently disables itself and the model fails to construct (reproduced, then fixed). WhisperX is pinned to 3.8.6 with
`pandas<3`; NLTK `punkt_tab` is baked into the image. First boot downloads ~4 GB of public Chatterbox weights (no HF token
needed) and the 360 MB wav2vec2 aligner into the `/models` volumes.

## Evidence

- 49 tests: audio (decode/resample/trim/stretch/pad), alignment mapping, mock bundle, full live flow through the **real FastAPI
  service apps** with fake engines (speed-up, over-budget, resynthesis, auth, missing reference, unreachable, retry reuse /
  fresh attempt directory, immutable artifacts), and service contracts. Pass on Python 3.11, 3.12 and 3.14.
- Member 1 integration: member 1's `Coordinator` called this module end to end in mock mode (audio published, timeline
  `[0,273,543,813,1083,1353,1800]`, then `MODULE_UNAVAILABLE` at scenes because member 4 is not merged); member 1's
  `validate_audio(live=True)` and `validate_artifacts` pass on mock, sped-up and real bundles.
- **Real models on CPU** (no GPU available locally), production code and locked versions except CPU torch wheels:
  real Chatterbox Turbo (torch 2.8) -> this module -> real WhisperX/wav2vec2 alignment over HTTP. 12 clips, 1195 speech frames
  (39.8 s), **121/121 words aligned**, mean alignment confidence 0.77-0.89 per clip, word times track the voiced region and real
  pauses (e.g. d001 `instant,` ends 1505 ms, `but` starts 1786 ms). Reference voices were Windows SAPI stand-ins.

## Integration steps for member 1

1. Merge this branch (contains `d3dfba6`; touches only `backend/modules/voice/`).
2. Add `numpy>=1.26` to root `pyproject.toml` dependencies and `uv lock`; without it the voice module import fails and the
   stage reports `MODULE_UNAVAILABLE`. (`httpx`/`pydantic` are already there; `python-multipart` only for these tests.)
3. Put real `assets/voices/{sundar,jensen}/reference.wav` (> 5 s) and `reference.txt` on the VM.
4. `docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml up -d --build chatterbox whisperx`,
   wait for both `/health` to report `"status":"ok"` with the GPU name, then run the live demo once from the API container or
   with SSH forwards (`python -m backend.modules.voice.demo --live`) before setting `MOCK_MODE=false`.

## Remaining limitations

- Not run on the Blackwell GPU and the Docker images were not built (no Docker daemon on the development machine).
- Real Sundar/Jensen reference recordings were not available; voice similarity is untested.
- Confidence (0.2) and ASR-similarity (0.6) thresholds are conservative; real speech scored 0.77-0.89.
- `Runtime.report_progress` is not called: `VoiceRequest` carries no job ID.
- Chatterbox's `from_pretrained` also downloads an unused 1 GB `s3gen.safetensors` (upstream download pattern).
