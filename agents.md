# Agent handoff

Updated: 2026-10-18. Read [context.md](context.md), [plan.md](plan.md), and the module READMEs for contracts. This page records verified implementation and deployment state; older planning language elsewhere may describe an unrealized Compute VM.

## Product and branch

The pipeline is topic → Tavily research → grounded Nemotron dialogue → Chatterbox Turbo conditioned on two reference WAVs → WhisperX word timing → six independently editable Remotion scenes → 1080×1920, 30 fps MP4. Visual design: white dotted notebook page, motion workboard in the upper 70%, speaker PNGs in the lower 30%.

Working branch is `feat/m1-platform`. All four teammate branches were fetched and merged with `--no-ff`; the original integration commit was `0b53b03`. A second integration on 2026-10-18 brought in the teammates' later content, voice, scenes/renderer, and editor changes after `6bcea29`. `main` has not been updated. Do not reset, clean, or overwrite the worktree. Review `git status` and diff before committing. Never stage `.env`, voice references, `.remotion`, output artifacts, caches, or generated video.

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

The second teammate integration adds URL-mapped Tavily citations and image
ranking, retry-safe immutable voice outputs, scene repair/worker job IDs that
match core validation, renderer container build fixes, and an editor HTTP
client smoke fixture. These changes are merged locally; they have not yet
been installed on the Devlab at the time of this handoff update. Preserve the
remote `SCENE_AGENT_MODE=single_call` setting when deploying the scene module.

### Scene retry investigation (2026-10-18)

The remote scene-generation attempt has not completed successfully. Scene 1's
Nemotron source generation produced valid `Scene.tsx`, `build.json`, and
`validation.json`, but the preview worker stalled because the Jupyter Devlab
image lacks Chromium NSS libraries. Scenes 2–6 were interrupted after the
worker issue. API health was `ok`; renderer health showed one running job.

Chromium is present at
`/home/jovyan/work/nebius-app/renderer/node_modules/.remotion/chrome-headless-shell/linux64/chrome-headless-shell-linux64/chrome-headless-shell`.
The missing libraries were installed persistently in user space with mamba at
`/home/jovyan/work/remotion-libs`; Chromium `--version` succeeds with
`LD_LIBRARY_PATH=/home/jovyan/work/remotion-libs/lib`. No sudo/root changes
were made.

An integration archive from commit `11cc617` was uploaded and extracted to
`/home/jovyan/work/nebius-app-release-11cc617` on the Devlab. It contains
source only and does not replace the live app yet. A local uncommitted patch
in `backend/core/pipeline.py` reuses validated `build.json` from an interrupted
first preview so scene 1 can retry without another Nemotron call. The patch
also matches M4's `operation_id-a{repair_attempts}` render job ID. Its upload
is at `/home/jovyan/pipeline-resume-11cc617.py`. `git status` showed this file
modified and not yet committed; inspect the diff before changing it.

To resume safely, first reinitialize CUA with `await cua.rewriteDocumentation()`
and attach Brave browser ID `1` to the existing Jupyter tab `24799453`. Check
the current service process IDs and project snapshot before stopping anything.
If the remote still runs the old integration, stop only the exact API and
Remotion worker processes from `/home/jovyan/work/nebius-app`, overlay
`/home/jovyan/work/nebius-app-release-11cc617` onto that workspace, and copy
the uploaded pipeline patch to `backend/core/pipeline.py`. Do not overwrite
`.env`, output, `node_modules`, or speech assets. Run `py_compile` on the
changed backend modules. Restart the worker with both:

```bash
export LD_LIBRARY_PATH=/home/jovyan/work/remotion-libs/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export REMOTION_BROWSER_EXECUTABLE=/home/jovyan/work/nebius-app/renderer/node_modules/.remotion/chrome-headless-shell/linux64/chrome-headless-shell-linux64/chrome-headless-shell
```

Preserve the private `.env` and its `SCENE_AGENT_MODE=single_call`,
`SCENE_AGENT_CONCURRENCY=1`, and `NEMOTRON_TIMEOUT_SECONDS=360` settings. Then
restart worker on `127.0.0.1:8001` and API on `127.0.0.1:8000`. The API recovery
will make interrupted scenes retryable. Retry scene 1 and verify worker/API
state before starting the other scenes. Only after this works, retry scenes
2–6. Do not Stitch the existing example project: its locked context predates
the supplied character PNGs. A fresh project is required for a final reel.

Local follow-up (later session, no remote access): the uncommitted
`pipeline.py` patch is now covered by tests. `test_preview_job_matches_final_build`
was updated to M4's current scheme (fallback uses `-a{repair_attempts}`, `-afb`
is rejected), and a new
`test_scene_retry_reuses_validated_build_from_interrupted_preview` proves a
scene retry after a failed first preview reuses `build.json` with no second
`generate_scene` call. Full backend suite: **159 passed**. The local file is
the version to deploy; diff it against `/home/jovyan/pipeline-resume-11cc617.py`
before copying. Still uncommitted. That session had no CUA tool, so none of
the remote steps below were run.

Latest observed state: Chromium starts after adding NSS libraries; the app
source archive and patch are staged remotely; the live app has not yet been
overlaid/restarted with that integration, no scene preview has been verified,
and no cloud final reel exists. The current Jupyter tab and tunnel hostname
may have changed after a Devlab restart; check them in Brave before operating.

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
