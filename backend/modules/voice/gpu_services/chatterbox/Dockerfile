# Chatterbox Turbo TTS service. Build context: the REPOSITORY ROOT (as in infra/compose.gpu.yml).
#   docker build -f backend/modules/voice/gpu_services/chatterbox/Dockerfile -t reel-chatterbox .
# Run with GPU access and persistent caches (see ../README.md):
#   docker run --gpus all -p 127.0.0.1:8002:8002 -e VOICE_API_KEY=... -v chatterbox-models:/models reel-chatterbox
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    TORCH_HOME=/models/torch \
    VOICE_DEVICE=cuda \
    VOICE_REF_CACHE=/models/reference-cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Locked environment: torch 2.8.0 + CUDA 12.8 wheels (Blackwell sm_120 kernels).
COPY backend/modules/voice/gpu_services/chatterbox/requirements.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cu128 -r requirements.txt

# chatterbox-tts pins torch==2.6.0 (no Blackwell kernels), so install it without its dependency pins.
RUN pip install --no-deps chatterbox-tts==0.1.7

COPY backend/modules/voice/gpu_services/chatterbox/app.py .

EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=10s --start-period=900s --retries=3 \
    CMD python -c "import json,sys,urllib.request; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=8))['status']=='ok' else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
