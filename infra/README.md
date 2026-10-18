# Nebius deployment status and paths

## What exists now (2026-10-18)

The team project `group08-project` has one running Jupyter Devlab,
`azure-pinniped-devlab-2` (`devlab-e05bkzg40ksp13hx8z`), with an RTX PRO 6000
Blackwell GPU. The Nebius console lists **zero standalone Compute VMs** in this
project. `cyan-ape-instance-8` was the name in a VM creation review, not a verified
running machine. Do not attempt SSH to it or create a duplicate GPU resource.

The Devlab's Jupyter service is exposed through authenticated port 8888. Its
Chatterbox Turbo and WhisperX FastAPI services run on `127.0.0.1:8002` and
`127.0.0.1:8003`, respectively, in separate Python 3.11 environments under
`/home/jovyan/work/nebius-speech`. Both use Torch 2.8.0+cu128 and report
`status: ok`, `model_loaded: true`, and `device: cuda`. The two real reference
WAVs are in `assets/voices/{sundar,jensen}/reference.wav` on the Devlab, mode
600. The supplied transparent character PNGs are now in
`assets/characters/{sundar,jensen}.png`, mode 600. A live loopback TTS → WhisperX alignment check passed for both speakers:
11 ordered word timestamps each, with a SHA-256 match to the normalized audio.
Generated WAV/JSON files are under `output/speech-check/` on that workspace.

The Chatterbox lock pins `setuptools==80.9.0`. Perth imports `pkg_resources`,
which is absent from the previous `setuptools==84.0.0` resolution. The pin was
confirmed by importing the actual Perth watermark class on the GPU host.

The two speech services bind **loopback only**. Jupyter Server Proxy 4.6.0 is
installed and enabled in the Devlab's Jupyter server. After a Devlab restart
on 2026-10-18, the authenticated Jupyter tunnel returned `status: ok`,
`model_loaded: true`, and `device: cuda` from both
`/proxy/8002/health` and `/proxy/8003/health`. The Jupyter tunnel hostname
may change on later restarts. The synthesis and alignment POST routes still
require their separate bearer keys. The merged application is now installed
under `/home/jovyan/work/nebius-app`, using a separate Python 3.12 environment
and a persistent conda Node 22 environment under the speech workspace. The
API, Remotion worker, and built Vite preview run on loopback ports 8000, 8001,
and 5173. The API reports `mode: live`, the worker reports `auth_required:
true`, and the editor loads through authenticated `/proxy/5173/`. The
frontend calls `/proxy/8000/api` on the same Jupyter origin. The API reaches
speech through loopback, so no server-to-server Jupyter token is needed. The
browser can reach the API only after authenticating to Jupyter. The current
tunnel URL is
`https://port8888-f560v6ypmfn50ww.tunnel.applications.uk-south2.nebius.cloud/proxy/5173/`;
get the current hostname from Nebius if the Devlab restarts.

A live example project for “How does WhatsApp voice calling infrastructure
work?” was created through the cloud editor. Tavily returned 16 sources and
12 grounded claims; Nemotron generated 12 dialogue turns; image search then
started. This is **not yet a completed cloud reel**. A previous local mock
pipeline completed a real Remotion render, but live speech, scenes, and final
video still require acceptance. The PNGs arrived after project creation, and
that project's locked scene context has null images. The API has since been
restarted with an upgrade path for PNGs added before timeline lock. Its scene
agents were switched to one structured Nemotron call at a time after parallel
ReAct calls timed out; scene 1 was retried on the original project as a check.
A fresh project is needed for a final reel with both PNGs. Do not expose the
loopback ports publicly or remove bearer checks.

## Recheck the existing GPU services

From an authenticated Jupyter terminal, without printing `.env` or token values:

```bash
cd /home/jovyan/work/nebius-speech
curl --fail http://127.0.0.1:8002/health
curl --fail http://127.0.0.1:8003/health
tail -n 30 logs/chatterbox-service.log
tail -n 30 logs/whisperx-service.log
```

Treat a health response as ready only if both `status` is `ok` and
`model_loaded` is `true`. Health endpoints contain no credentials. Before
restarting either service, inspect its current PID, command, and working
directory; only stop a verified process belonging to this workspace. Its
private `.env` must stay mode 600. Avoid installing speech dependencies into
Jupyter's Python 3.13 base environment.

Jupyter Server Proxy itself is installed into the Jupyter environment. If a
future Devlab restart loses it, check `jupyter server extension list`;
the extension was also installed into the persistent user site under
`/home`. Restart only absent workspace Uvicorn processes, loading
`/home/jovyan/work/nebius-speech/.env` (not the older `.env.gpu`).

## Current Devlab app

The merged worktree was uploaded as a source archive, then installed in
`/home/jovyan/work/nebius-app`. Its private `.env` is mode 600 and contains
only the provider and internal keys needed by this app, plus paths to the
speech assets. The worker process receives only its render token and artifact
settings. Both speech services use their separate private env. Logs live in
`logs/{api,renderer,frontend,chatterbox,whisperx}-service.log` under their
respective workspaces.

After a Devlab restart, check `jupyter server extension list` and restart
only absent services from the correct workspace. The speech launch commands
and exact paths are in [agents.md](../agents.md). Start the app from its root,
keeping every service on loopback:

```bash
cd /home/jovyan/work/nebius-app
nohup .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1 > logs/api-service.log 2>&1 &

nohup bash -lc 'cd /home/jovyan/work/nebius-app; set -a; source .env; set +a; export PATH=/home/jovyan/work/nebius-speech/.node/bin:$PATH; exec env -i HOME=/home/jovyan PATH="$PATH" LANG=C.UTF-8 ARTIFACT_ROOT="$ARTIFACT_ROOT" RENDER_WORKER_TOKEN="$RENDER_WORKER_TOKEN" RENDER_CONCURRENCY=1 RENDER_WORKER_HOST=127.0.0.1 RENDER_WORKER_PORT=8001 npm run worker --prefix renderer' > logs/renderer-service.log 2>&1 &

nohup bash -lc 'export PATH=/home/jovyan/work/nebius-speech/.node/bin:$PATH; cd /home/jovyan/work/nebius-app; exec npm run preview --prefix frontend -- --host 127.0.0.1 --port 5173' > logs/frontend-service.log 2>&1 &
```

Before starting a process, inspect whether its port and existing workspace
process are already present. The `.env` uses `VITE_BASE_PATH=./` so built
assets resolve under Jupyter's proxy path. Set `VITE_API_BASE_URL=/proxy/8000`
and `VITE_PREVIEW_HOST` to the current tunnel hostname, then rebuild the
frontend if these values or the tunnel change. Set `FRONTEND_ORIGIN` to the
same Jupyter origin for API CORS. The backend and worker both use the absolute
`ARTIFACT_ROOT=/home/jovyan/work/nebius-app/output`.

## Compose deployment option

`infra/compose.yml` and `infra/compose.gpu.yml` define the intended
five-service deployment for a Docker-capable GPU host. No such standalone VM
is currently available in the team project. The Devlab container did not have
Docker installed when inspected. The Compose files are integration source,
not evidence of a running cloud application.

When the team has an authorized Docker host with GPU access, inspect its
driver, Docker/Compose, NVIDIA Container Toolkit, disk, ingress, and user
permissions before deployment. Put the ignored `.env`, actual voice WAVs, and
character PNGs on that host separately. Prepare the shared artifact directory
for API UID/GID 10001, then from the repository root:

```bash
docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml config --quiet
docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml up -d --build
docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml ps
```

`config --quiet` avoids printing interpolated secrets. The web service proxies
same-origin `/api`; only its ingress should be reachable from a demo browser.
API, renderer, and speech ports remain internal to Compose. Verify readiness,
actual reference synthesis, alignment, frontend editing, and final Remotion
render on the target host before calling cloud deployment complete.
