# Agent handoff

Updated: 2026-10-18. Read [context.md](context.md), [plan.md](plan.md), and the module READMEs for contracts. This page records verified implementation and deployment state; older planning language elsewhere may describe an unrealized Compute VM.

## Product and branch

The pipeline is topic → Tavily research → grounded Nemotron dialogue → Chatterbox Turbo conditioned on two reference WAVs → WhisperX word timing → six independently editable Remotion scenes → 1080×1920, 30 fps MP4. Visual design: white dotted notebook page, motion workboard in the upper 70%, speaker PNGs in the lower 30%.

Working branch is `feat/m1-platform`. All four teammate branches were fetched and merged locally with `--no-ff`. Integration commit `0b53b03` was pushed to `origin/feat/m1-platform` on 2026-10-18; `main` has not been updated. Do not reset, clean, or overwrite the worktree. Review `git status` and diff before committing. Never stage `.env`, voice references, `.remotion`, output artifacts, caches, or generated video.

The user authorized integration, pushing, and setup of the existing Nebius Devlab. New GPU resources are unnecessary.

## Verified local integration

- Python backend: 150 tests passed. Frontend production build and Remotion typecheck passed. Remotion tests: 7 passed, 1 skipped for an unavailable prior-reel fixture.
- Full mock coordinator flow generated six previews, edited scene six to revision 2 without changing other scene hashes or audio, stitched a 1080×1920, 30 fps H.264/AAC MP4 with 1800 frames, and recovered persisted project state. Report: `output/demos/platform-integration/projects/d3bd48a9-d6e9-46aa-8837-a8886d507a10/acceptance.json`. This was mock research, silent audio, and mock timing, so it does not establish the live cloud reel.
- `scripts/check_nemotron.py` reached HTTP 200 for both JSON-prompt and tool-calling requests using the configured NVIDIA model on 2026-10-18. The ignored local `.env` now selects `NEMOTRON_STRUCTURED_MODE=tool_calling`; native JSON Schema support remains untested. Capability report: `output/capabilities/nemotron.json`.
- Integration fixes in `0b53b03` include preview/final attempt identity, Compose build paths, core dependency lock, Remotion acceptance driver, and Chatterbox `setuptools==80.9.0` pin.
- The frontend Vite config now supports relative assets (`VITE_BASE_PATH=./`) and an exact proxy hostname (`VITE_PREVIEW_HOST`). This was required to serve the built editor under Jupyter's `/proxy/5173/` path.

## Existing Nebius GPU Devlab

The team project `group08-project` (`project-e05mfttbln00ypf4h123rz`) has one Devlab, `azure-pinniped-devlab-2` (`devlab-e05bkzg40ksp13hx8z`), with one RTX PRO 6000 Blackwell GPU, 24 vCPUs, 218 GiB RAM, and 100 GiB persistent `/home` storage. There are zero standalone Compute VMs in this project. `cyan-ape-instance-8` appeared only in a VM creation preview. Do not create or SSH to a supposed duplicate VM.

Jupyter runs in the Nebius port-8888 authenticated tunnel. Its tunnel hostname can change when the Devlab restarts. Use the console's Open/endpoint button to obtain the current URL. Browser CUA is available: initialize with `await cua.rewriteDocumentation()` at the start of a resumed browser task; selected browser is Brave ID `1`. Do not print or commit Jupyter, Nebius, NVIDIA, Tavily, voice, alignment, or render tokens.

Persistent remote speech workspace: `/home/jovyan/work/nebius-speech`. Chatterbox and WhisperX use separate Python 3.11 virtual environments `.venv-chatterbox` and `.venv-whisperx`, each with Torch 2.8.0+cu128. The private workspace `.env` (mode 600) contains the **same** voice/alignment bearer tokens as the ignored local repo `.env`; `.env.gpu` is older and has different keys. Launch from `.env`, never `.env.gpu`.

The user-supplied real reference WAVs are installed remotely at `assets/voices/{sundar,jensen}/reference.wav` (mode 600) and in the local ignored `assets/voices/` paths. Remote/local SHA-256 matched. The user also supplied transparent `jensen.png` and `sundar.png`; both were installed under the remote `assets/characters/` directory (mode 600) and local ignored `assets/characters/`, with matching SHA-256 hashes. Do not call voice identity/perceptual quality verified merely from inference.

Before Devlab restart, both loopback services returned `status: ok`, `model_loaded: true`, `device: cuda`:

- Chatterbox on `127.0.0.1:8002`, `.venv-chatterbox/bin/python`, source `backend/modules/voice/gpu_services/chatterbox/app.py`.
- WhisperX on `127.0.0.1:8003`, `.venv-whisperx/bin/python`, source `backend/modules/voice/gpu_services/whisperx/app.py`.

The Perth watermark import needed `setuptools==80.9.0`; the source requirements and lock now pin it. A real GPU smoke program synthesized and aligned a short sentence for **both** reference WAVs. For each it checked response validity, 11 ordered spoken-word timestamps, transcript identity, and SHA-256 equality between the WAV sent to WhisperX and the final normalized WAV. Remote artifacts: `output/speech-check/{sundar,jensen}/{raw.wav,audio.wav,words.json}`; log `logs/speech-smoke.log`.

### Authenticated proxy and restart

User explicitly approved enabling authenticated Jupyter Server Proxy. It was installed (`jupyter_server_proxy 4.6.0`) and `jupyter server extension list` reported it enabled and validation OK after a Devlab restart. The Devlab resumed, Jupyter loaded at `https://port8888-f560v6ypmfn50ww.tunnel.applications.uk-south2.nebius.cloud/lab`, and both Uvicorn processes were relaunched from the private workspace `.env`. Authenticated browser requests to `/proxy/8002/health` and `/proxy/8003/health` both returned `status: ok`, `model_loaded: true`, `device: cuda`. The console page briefly returned HTTP 500 during startup, but Jupyter and both model routes recovered. Do not assume this tunnel hostname persists through another restart.

The restarted container retained or rediscovered the extension. Future restarts may still lose packages installed into `/opt/conda`, while `/home` persists. `jupyter-server-proxy` was also installed into the user site under `/home`; check the extension list and proxy health after any restart.

The Uvicorn services are loopback-only and still require separate bearer keys. Their previous PIDs are historical. Inspect current process command and cwd before touching any process. If absent, from the remote workspace:

```bash
nohup bash -lc 'set -a; source /home/jovyan/work/nebius-speech/.env; set +a; cd /home/jovyan/work/nebius-speech/backend/modules/voice/gpu_services/chatterbox; exec /home/jovyan/work/nebius-speech/.venv-chatterbox/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8002 --workers 1' > logs/chatterbox-service.log 2>&1 &
nohup bash -lc 'set -a; source /home/jovyan/work/nebius-speech/.env; set +a; cd /home/jovyan/work/nebius-speech/backend/modules/voice/gpu_services/whisperx; exec /home/jovyan/work/nebius-speech/.venv-whisperx/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8003 --workers 1' > logs/whisperx-service.log 2>&1 &
```

Check both loopback `/health` bodies and then authenticated Jupyter `/proxy/{8002,8003}/health`. Health endpoints are public within the authenticated proxy; synthesis/alignment retain service bearer checks. The **local backend still points to localhost** and no protected server-to-server route has been verified. Jupyter token auth and service bearer auth both normally use `Authorization`, so account for this conflict before configuring backend URLs. Do not put a Jupyter token in a logged URL, disable either authentication, expose speech ports publicly, or extract browser cookies.

The integrated API, frontend, and Remotion renderer are now installed beside
speech on the same Devlab under `/home/jovyan/work/nebius-app`. The app's
private `.env` is mode 600 and contains the needed provider/internal keys;
`ASSETS_ROOT` points to the speech workspace reference WAVs. A separate
Python 3.12 `.venv` runs the API on `127.0.0.1:8000`. Persistent conda
Node 22 under `/home/jovyan/work/nebius-speech/.node` runs the authenticated
Remotion worker on `127.0.0.1:8001` and built Vite preview on
`127.0.0.1:5173`. The worker receives only render settings, not Tavily or
NVIDIA provider keys. API `/api/health` reported `mode: live` and
`structured_mode: tool_calling`; worker `/health` reported
`auth_required: true`. The browser loaded the editor and created a live
project through authenticated Jupyter `/proxy/5173/`. Its frontend uses
same-origin `/proxy/8000/api`; the backend calls speech over loopback. This
avoids the Jupyter-token/service-bearer header conflict. At the latest
verified editor check, the example WhatsApp voice calling project had completed
research and dialogue and started image search. Project ID:
`615d8640-d6c6-4338-87f4-4be723e224d1`.

The character PNGs arrived after the example project was created. Its original
`inputs/characters.json` and locked `context.json` have null images, so that
project cannot be stitched into a live reel with the supplied photos.
`Coordinator.characters()` now attaches both later from `ASSETS_ROOT` to a
new immutable `inputs/characters-with-images.json` **before** `context.json`
is locked. This patch is installed remotely and the API was restarted to load
it. A fresh project will pick up both PNGs directly; do not edit the locked
context of the original project. `Coordinator.stitch()` refuses a live final
render with error `CHARACTERS_MISSING` when either image is absent.

The first parallel ReAct scene agents timed out (`SCENE_AGENT_UNAVAILABLE`)
without producing previews. A scene-specific `SCENE_AGENT_MODE=single_call`
path was added and installed remotely. The Devlab `.env` now sets that mode,
`SCENE_AGENT_CONCURRENCY=1`, and `NEMOTRON_TIMEOUT_SECONDS=360`. The API was
restarted and returned `/api/health` status `ok`; the original project's
scene 1 was retried at 16:23 local time. Confirm that it succeeds before
running six more scenes. The remote browser control recovered by opening a
fresh tab in Brave browser ID `1` after older claimed tabs stopped attaching.

No cloud final reel was produced yet. The Devlab container has no verified
Docker/Compose; all five processes were started directly and need relaunch
after Devlab restart. `infra/README.md` has exact commands and URL. The
current Jupyter tunnel hostname may change on restart; update the app
`.env` values `VITE_PREVIEW_HOST` and `FRONTEND_ORIGIN`, rebuild the
frontend if needed, and get the new URL from Nebius.

## Next operator actions on Nebius

1. Watch the original project's scene 1 retry. It already completed Tavily research (16 sources, 12 claims), Nemotron dialogue (12 turns), Tavily images, Chatterbox speech, and WhisperX word timing. Its locked context lacks both PNGs, so do not Stitch it. If scene 1 succeeds, create a fresh project with the now-installed PNGs and verify `characters[*].image` in its context. The normal UI create path makes a new Tavily request; avoid it if a reviewed project-reuse implementation becomes available.
2. Follow all six scene previews and Stitch on the fresh project. Check listening and visual quality separately.
3. Review and merge the published `feat/m1-platform` branch to `main` through the team's review path when ready; preserve all four teammate merges.

Read-only remote inspection, once browser access returns:

```bash
cd /home/jovyan/work/nebius-app
python - <<'PY'
import json
from pathlib import Path
p = Path('output/projects/615d8640-d6c6-4338-87f4-4be723e224d1')
s = json.loads((p / 'snapshot.json').read_text())
print('status:', s['status'], 'error:', (s.get('error') or {}).get('code'))
print('research:', bool(s.get('research')), 'dialogue:', bool(s.get('script')),
      'images:', bool(s.get('images')), 'audio:', bool(s.get('audio')))
c = p / 'context.json'
print('context_locked:', c.exists())
if c.exists():
    d = json.loads(c.read_text())
    print('character_images:', {x['character_id']: bool(x.get('image')) for x in d['characters']})
PY
```

The original project is already `context_locked: true` with both images false;
this was confirmed from the Devlab filesystem after API recovery. A fresh
project is needed for a final reel with the supplied PNGs.

## Secret handling

Root `.env`, remote workspace `.env`, and voice WAVs are ignored/private. Do not display their values or stage them. User has already provided the reference WAV paths and existing API keys; do not ask again. User approved this specific authenticated Jupyter proxy change; any new public route or access expansion would be a separate decision.
