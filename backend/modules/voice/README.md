# Voice module (member 3)

`synthesize_dialogue(VoiceRequest, Runtime) -> AudioBundle` in `service.py`: 12 dialogue turns -> 12 normalized WAVs
+ transcripts + **measured word timestamps** (`words.json`, `subtitles.srt`) + `bundle.json`.
Live mode = our Chatterbox Turbo service (:8002) then our WhisperX forced-alignment service (:8003).
Mock mode = deterministic tones + synthetic timing, `timing_quality: "mock"`, no services needed.

## Run

```bash
export PYTHONPATH="$PWD"            # or "$PWD/.bootstrap:$PWD" until contracts/ lands on main
python -m backend.modules.voice.demo --mock --output output/demos/voice --clean
python -m backend.modules.voice.demo --live --env .env --assets assets --output output/demos/voice   # needs both services
python -m pytest backend/modules/voice/tests -q                                                       # 45 tests
```

The demo prints per-clip frames/words and runs `validate.py` (WAV format, sha256/size of every file, ordered
in-clip word times, `sample_count == frame_count*1600`, total <= 1599). Mock output: 12 x 120 frames = 1440, matching the
plan's fixture recipe. `--live` strips the `MOCK FIXTURE:` prefix and needs `assets/voices/{sundar,jensen}/reference.wav`.

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
5. Write artifacts under `projects/<id>/voice/v<rev>/<dialogue_id>/{audio.wav,transcript.txt,words.json,subtitles.srt,alignment_raw.json}`
   and `voice/v<rev>/bundle.json`. `alignment_raw.json` keeps the provider's raw timing. Re-running the same revision overwrites it.

Error codes (all `StageFailure`, stage `voice`): `VOICE_REQUEST_INVALID`, `VOICE_REFERENCE_MISSING|MISMATCH`, `VOICE_AUTH_FAILED`,
`VOICE_UNAVAILABLE` (retryable), `VOICE_NOT_CONFIGURED`, `VOICE_AUDIO_INVALID`, `VOICE_SILENT_AUDIO`, `VOICE_IMPLAUSIBLE_AUDIO`,
`AUDIO_DURATION_OUT_OF_RANGE`, `ALIGNMENT_*`. Live mode never falls back to fake audio.

Settings read from `runtime.settings` (any key case): `VOICE_API_URL/KEY/MODEL/TIMEOUT_SECONDS`, `ALIGNMENT_API_URL/KEY/TIMEOUT_SECONDS`.
`voice_reference` on each `CharacterSpec` must point at the copied reference WAV (sha256 is verified). `voice_id` is unused with Chatterbox.
Write numbers/acronyms in spoken form in the script and avoid `[tags]`: the text is both spoken and aligned verbatim.

## GPU services (`gpu_services/{chatterbox,whisperx}/`)

| Service | Endpoint | Notes |
| --- | --- | --- |
| Chatterbox Turbo `:8002` | `POST /v1/tts` (Bearer `VOICE_API_KEY`; multipart `text, dialogue_id, model, reference_audio`, optional `seed`) -> `audio/wav` PCM16 at native 24 kHz; `GET /health` | one active synthesis; conditioning cached per reference sha256; fails closed if key unset |
| WhisperX `:8003` | `POST /v1/align` (Bearer `ALIGNMENT_API_KEY`; multipart `audio, dialogue_id, transcript, language=en`) -> `AlignmentResult` + extra `quality{mean_score,min_score,...}`; `GET /health` | known-script forced alignment only; `WHISPERX_TRANSCRIBE=true` adds ASR similarity check |

Both load their model in the background at startup and report `status: loading|ok|error` plus the GPU name on `/health`;
loading includes a real inference smoke test. Dependencies are locked **independently** with `uv pip compile` for Python 3.11 / linux x86_64
(`requirements.in` -> `requirements.txt`, `--exclude-newer 2026-10-11`): torch/torchaudio **2.8.0+cu128** (CUDA 12.8 wheels, includes Blackwell sm_120 kernels).
`chatterbox-tts` 0.1.7 pins `torch==2.6.0` (no Blackwell kernels), so the Dockerfile installs it with `--no-deps` on top of the lock.
WhisperX is pinned to 3.8.6 with `pandas<3`; NLTK `punkt_tab` is baked into the image.

Compose wiring for member 1 (`infra/compose.gpu.yml`), per service:

```yaml
chatterbox:
  build: ../backend/modules/voice/gpu_services/chatterbox
  environment: [VOICE_API_KEY, VOICE_DEVICE=cuda]
  volumes: [chatterbox-models:/models]
  ports: ["127.0.0.1:8002:8002"]
  deploy: {resources: {reservations: {devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]}}}
# whisperx: same shape, build .../whisperx, ALIGNMENT_API_KEY, ALIGNMENT_MODEL/DEVICE, volume whisperx-models:/models, port 8003
```

Make `api` `depends_on` both with `condition: service_healthy`: the first boot downloads checkpoints (health `start-period` is 600-900 s).

## Results so far

- 45 tests pass locally: audio (decode/resample/trim/stretch/pad), alignment mapping, mock bundle, full live flow through the **real FastAPI
  service apps** using fake engines (speed-up, over-budget, resynthesis, auth, missing reference, unreachable), and service contracts.
- Mock demo passes all acceptance checks. Dependency locks resolve for the target platform.

## Remaining blockers / not verified

- **No real GPU run yet.** The Docker images were not built and Chatterbox/WhisperX were not run (no Linux/GPU here); `diffusers==0.29.0`
  with `huggingface_hub 1.x`/`transformers 5.2.0` import compatibility is unverified. First real synthesize -> align on the VM is for members 1 + 3.
- `ALIGNMENT_LOW_CONFIDENCE` threshold (mean word score 0.2) and the 0.6 ASR similarity threshold are uncalibrated.
- Needs real `assets/voices/*/reference.wav` (>5 s each) and `contracts/` on main (tests use `.bootstrap/` meanwhile).
- `Runtime.report_progress` is not called: `VoiceRequest` carries no job ID.
