# Existing Nebius VM deployment

Only Member 1 deploys the integrated checkout. The existing VM is `cyan-ape-instance-8`,
SSH user `orange_whisky`, RTX PRO 6000 Blackwell, Ubuntu 24.04/CUDA 13.
Its public IP is still required. Do not create a second VM.

## Before deployment

Merge the content, speech, scene/renderer, and frontend branches. The Docker build
contexts are the repository root. Member 3 supplies these exact paths:

```text
backend/modules/voice/gpu_services/chatterbox/Dockerfile
backend/modules/voice/gpu_services/whisperx/Dockerfile
```

Member 4 supplies `renderer/Dockerfile`; the worker must bind `0.0.0.0:8001`.
Member 5 supplies the frontend npm build. Service interfaces/ports match plan.md.
Each speech container binds its service to `0.0.0.0`, ports 8002/8003.

Connect using the owner's ignored SSH key:

```bash
ssh -i .ssh/nebius_reel_ed25519 orange_whisky@<VM_PUBLIC_IP>
```

On the VM, inspect `nvidia-smi`, `docker version`, `docker compose version`, and
`docker info` before changing host packages. Install Docker Engine/Compose and
NVIDIA Container Toolkit if missing, following the official install instructions.
Member 3 must verify actual GPU inference in both containers with compatible
Blackwell CUDA/PyTorch dependencies. A successful `nvidia-smi` alone is insufficient.

- https://docs.docker.com/engine/install/ubuntu/
- https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

## Start the integrated application

Clone the repo onto the VM. Copy the owner's `.env` via SSH separately; it must
remain mode 600. Add the character PNGs and voice references under `assets/`.
Change `MOCK_MODE=false` only after live speech/inference readiness has been checked.
Prepare the artifact directory for the API user (UID 10001) and shared renderer
group (GID 10001, added by Compose):

```bash
sudo install -d -m 2775 -o 10001 -g 10001 output
```

Member 4 should keep renderer output subdirectories group-writable when creating
them (`umask 0002`). Renderer and API paths must both resolve to `/workspace/output`.

From the repository root:

```bash
docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml config --quiet
docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml up -d --build
docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml ps
curl --fail http://localhost:8080/api/health
```

Do not paste `docker compose config` output without `--quiet`: interpolation can
include secrets. Public web ingress is port 8080 by default (`WEB_PORT`), in addition
to SSH. Internal API, renderer, and speech ports are not published. Set web ingress
in the existing security group and host firewall as needed after checking current rules.
For a private demo, use `ssh -L 8080:localhost:8080 ...` instead.

The web image builds with empty `VITE_API_BASE_URL` and proxies same-origin `/api`.
An external browser therefore does not need access to backend/service ports.
Only the API reads the complete application `.env`; the renderer and speech workers
receive their own explicit variables. Provider keys are absent from their environments.

The base Compose file can run without speech containers when using mock modules.
It still requires Member 4's renderer and Member 5's frontend before a complete build.
The GPU overlay adds only the two speech containers and persistent model caches.
Completed artifacts stay on the host disk under `output/` across restarts.

## Current deployment status

Compose configuration is supplied; no cloud connection, container build, GPU
inference, or cloud video render has been performed. IP assignment and the four
other implementation branches are required for that acceptance step.
