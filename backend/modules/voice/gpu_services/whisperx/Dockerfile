# WhisperX forced-alignment service. Build context: the REPOSITORY ROOT (as in infra/compose.gpu.yml).
#   docker build -f backend/modules/voice/gpu_services/whisperx/Dockerfile -t reel-whisperx .
#   docker run --gpus all -p 127.0.0.1:8003:8003 -e ALIGNMENT_API_KEY=... -v whisperx-models:/models reel-whisperx
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    TORCH_HOME=/models/torch \
    NLTK_DATA=/opt/nltk_data \
    ALIGNMENT_DEVICE=cuda

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Locked environment: torch 2.8.0 + CUDA 12.8 wheels (Blackwell sm_120 kernels), whisperx 3.8.6.
COPY backend/modules/voice/gpu_services/whisperx/requirements.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cu128 -r requirements.txt

# whisperx.align sentence-splits with NLTK punkt_tab; bake it in so startup needs no download.
RUN python -m nltk.downloader -d /opt/nltk_data punkt_tab

COPY backend/modules/voice/gpu_services/whisperx/app.py .

EXPOSE 8003
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=3 \
    CMD python -c "import json,sys,urllib.request; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:8003/health', timeout=8))['status']=='ok' else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "1"]
