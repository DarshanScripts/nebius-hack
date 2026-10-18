"""Chatterbox Turbo TTS service (port 8002).

POST /v1/tts   Bearer VOICE_API_KEY; multipart text, dialogue_id, model, reference_audio [, seed]
GET  /health   readiness (never returns credentials)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import logging
import os
import re
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

log = logging.getLogger("chatterbox-service")
MODEL_NAME = "chatterbox-turbo"
MAX_TEXT_CHARS = 800
MAX_REFERENCE_BYTES = 50 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class ChatterboxEngine:
    """Loads Chatterbox Turbo once and keeps one conditioning set per reference WAV."""

    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model: Any = None
        self.sr = 24000
        self._conds: dict[str, Any] = {}

    def load(self) -> None:
        import torch
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is False")
        self.model = ChatterboxTurboTTS.from_pretrained(device=self.device)
        self.sr = int(self.model.sr)
        if self.model.conds is not None:  # real inference check using the bundled default voice
            self.model.generate("Ready.")

    def gpu_name(self) -> str | None:
        import torch

        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else None

    def synthesize(self, text: str, ref_path: Path, ref_sha: str, seed: int | None) -> np.ndarray:
        import torch

        if seed is not None:
            torch.manual_seed(seed)
        conds = self._conds.get(ref_sha)
        if conds is None:
            self.model.prepare_conditionals(str(ref_path))
            self._conds[ref_sha] = self.model.conds
        else:
            self.model.conds = conds
        wav = self.model.generate(text)
        return wav.squeeze(0).detach().cpu().numpy().astype(np.float32)


def pcm16_wav(samples: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def create_app(engine: Any | None = None, *, api_key: str | None = None, ref_cache: Path | None = None) -> FastAPI:
    state: dict[str, Any] = {"engine": engine, "ready": engine is not None, "error": None}
    key = api_key if api_key is not None else os.environ.get("VOICE_API_KEY", "")
    cache = ref_cache or Path(os.environ.get("VOICE_REF_CACHE", "/tmp/chatterbox_refs"))
    gate = asyncio.Lock()  # one active synthesis at a time

    def _load() -> None:
        try:
            eng = ChatterboxEngine(os.environ.get("VOICE_DEVICE", "cuda"))
            eng.load()
            state["engine"], state["ready"] = eng, True
            log.info("Chatterbox Turbo loaded on %s", eng.device)
        except Exception as exc:  # reported through /health, never crashes the process
            log.exception("model load failed")
            state["error"] = f"{type(exc).__name__}: {exc}"[:300]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if engine is None:
            threading.Thread(target=_load, daemon=True).start()
        yield

    app = FastAPI(title="Chatterbox Turbo TTS", lifespan=lifespan)

    def auth(authorization: str | None = Header(default=None)) -> None:
        if not key:
            raise HTTPException(503, "VOICE_API_KEY is not configured on the service")
        token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(token.encode(), key.encode()):
            raise HTTPException(401, "invalid bearer token")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        eng = state["engine"]
        gpu = None
        try:
            gpu = eng.gpu_name() if eng is not None and hasattr(eng, "gpu_name") else None
        except Exception:
            pass
        return {
            "status": "ok" if state["ready"] else ("error" if state["error"] else "loading"),
            "model_loaded": bool(state["ready"]),
            "model": MODEL_NAME,
            "device": getattr(eng, "device", None),
            "gpu": gpu,
            "error": state["error"],
        }

    @app.post("/v1/tts", dependencies=[Depends(auth)])
    async def tts(
        text: str = Form(...),
        dialogue_id: str = Form(...),
        model: str = Form(MODEL_NAME),
        seed: int | None = Form(None),
        reference_audio: UploadFile = File(...),
    ) -> Response:
        if not state["ready"]:
            raise HTTPException(503, state["error"] or "model is still loading", headers={"Retry-After": "5"})
        if model != MODEL_NAME:
            raise HTTPException(422, f"unsupported model '{model}', expected '{MODEL_NAME}'")
        if not ID_RE.match(dialogue_id):
            raise HTTPException(422, "invalid dialogue_id")
        text = " ".join(text.split())
        if not text or len(text) > MAX_TEXT_CHARS:
            raise HTTPException(422, f"text must contain 1-{MAX_TEXT_CHARS} characters")
        ref = await reference_audio.read(MAX_REFERENCE_BYTES + 1)
        if not ref or len(ref) > MAX_REFERENCE_BYTES:
            raise HTTPException(422, "reference_audio is empty or too large")
        sha = hashlib.sha256(ref).hexdigest()
        ref_path = cache / f"{sha}.wav"
        async with gate:  # also serializes the cache write below
            if not ref_path.exists():
                cache.mkdir(parents=True, exist_ok=True)
                tmp = ref_path.with_suffix(".tmp")
                tmp.write_bytes(ref)
                os.replace(tmp, ref_path)
            try:
                samples = await run_in_threadpool(state["engine"].synthesize, text, ref_path, sha, seed)
            except AssertionError as exc:  # e.g. "Audio prompt must be longer than 5 seconds!"
                raise HTTPException(422, f"reference audio rejected: {exc}") from exc
        if samples.size == 0:
            raise HTTPException(500, "model produced no audio")
        return Response(
            pcm16_wav(samples, state["engine"].sr),
            media_type="audio/wav",
            headers={"X-Dialogue-Id": dialogue_id},
        )

    return app


app = create_app()
