"""WhisperX forced-alignment service (port 8003).

POST /v1/align  Bearer ALIGNMENT_API_KEY; multipart audio (final WAV), dialogue_id, transcript, language=en
GET  /health    readiness (never returns credentials)

The known transcript is force-aligned to the uploaded audio; no ASR or diarization is needed.
Set WHISPERX_TRANSCRIBE=true to additionally run Whisper ASR as a text-mismatch quality check.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import hmac
import logging
import os
import re
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

log = logging.getLogger("whisperx-service")
MAX_AUDIO_BYTES = 25 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _norm_tokens(text: str) -> list[str]:
    out = []
    for tok in text.lower().replace("\u2019", "'").split():
        tok = "".join(ch for ch in tok if ch.isalnum() or ch == "'").strip("'")
        if tok:
            out.append(tok)
    return out


def text_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm_tokens(a), _norm_tokens(b), autojunk=False).ratio()


def to_ms(seconds: float) -> int:
    return max(0, int(round(float(seconds) * 1000)))


def build_response(dialogue_id: str, sha: str, transcript: str, aligned_words: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert WhisperX word dicts to the AlignmentResult wire shape; words without timing are omitted."""
    words, scores = [], []
    for w in aligned_words:
        if w.get("start") is None or w.get("end") is None:
            continue
        start, end = to_ms(w["start"]), to_ms(w["end"])
        words.append(
            {"word_id": f"{dialogue_id}_w{len(words) + 1:03d}", "text": str(w["word"]), "start_ms": start, "end_ms": max(end, start)}
        )
        if w.get("score") is not None:
            scores.append(float(w["score"]))
    return {
        "dialogue_id": dialogue_id,
        "audio_sha256": sha,
        "transcript": transcript,
        "words": words,
        "quality": {
            "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
            "min_score": round(min(scores), 4) if scores else None,
            "words_in_transcript": len(transcript.split()),
            "words_aligned": len(words),
        },
    }


class WhisperXEngine:
    def __init__(self, device: str, align_model: str, transcribe: bool, asr_model: str, compute_type: str):
        self.device, self.align_model_name = device, align_model
        self.transcribe, self.asr_model_name, self.compute_type = transcribe, asr_model, compute_type
        self.model: Any = None
        self.meta: Any = None
        self.asr: Any = None

    def load(self) -> None:
        import torch
        import whisperx

        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is False")
        self.model, self.meta = whisperx.load_align_model(
            language_code="en", device=self.device, model_name=self.align_model_name or None
        )
        if self.transcribe:
            self.asr = whisperx.load_model(self.asr_model_name, self.device, compute_type=self.compute_type, language="en")
        import numpy as np

        silence = np.zeros(16000, dtype=np.float32)  # real GPU inference smoke test
        whisperx.align([{"text": "ready", "start": 0.0, "end": 1.0}], self.model, self.meta, silence, self.device)

    def gpu_name(self) -> str | None:
        import torch

        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else None

    def align(self, wav_path: Path, transcript: str) -> dict[str, Any]:
        import whisperx

        audio = whisperx.load_audio(str(wav_path))
        duration = len(audio) / 16000
        result = whisperx.align(
            [{"text": transcript, "start": 0.0, "end": duration}],
            self.model, self.meta, audio, self.device, return_char_alignments=False,
        )
        words = [w for seg in result["segments"] for w in seg["words"]]
        out: dict[str, Any] = {"words": words, "duration_s": duration}
        if self.asr is not None:
            asr = self.asr.transcribe(audio, batch_size=4)
            text = " ".join(seg["text"].strip() for seg in asr["segments"])
            out["asr_text"], out["asr_similarity"] = text, round(text_similarity(transcript, text), 4)
        return out


def create_app(engine: Any | None = None, *, api_key: str | None = None) -> FastAPI:
    state: dict[str, Any] = {"engine": engine, "ready": engine is not None, "error": None}
    key = api_key if api_key is not None else os.environ.get("ALIGNMENT_API_KEY", "")
    gate = asyncio.Lock()  # one active alignment at a time

    def _load() -> None:
        try:
            eng = WhisperXEngine(
                os.environ.get("ALIGNMENT_DEVICE", "cuda"),
                os.environ.get("ALIGNMENT_MODEL", "WAV2VEC2_ASR_BASE_960H"),
                os.environ.get("WHISPERX_TRANSCRIBE", "false").lower() in ("1", "true", "yes"),
                os.environ.get("WHISPERX_ASR_MODEL", "small.en"),
                os.environ.get("WHISPERX_COMPUTE_TYPE", "float16"),
            )
            eng.load()
            state["engine"], state["ready"] = eng, True
            log.info("WhisperX aligner loaded on %s", eng.device)
        except Exception as exc:
            log.exception("model load failed")
            state["error"] = f"{type(exc).__name__}: {exc}"[:300]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if engine is None:
            threading.Thread(target=_load, daemon=True).start()
        yield

    app = FastAPI(title="WhisperX forced alignment", lifespan=lifespan)

    def auth(authorization: str | None = Header(default=None)) -> None:
        if not key:
            raise HTTPException(503, "ALIGNMENT_API_KEY is not configured on the service")
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
            "align_model": getattr(eng, "align_model_name", None),
            "asr_enabled": bool(getattr(eng, "asr", None)),
            "device": getattr(eng, "device", None),
            "gpu": gpu,
            "error": state["error"],
        }

    @app.post("/v1/align", dependencies=[Depends(auth)])
    async def align(
        audio: UploadFile = File(...),
        dialogue_id: str = Form(...),
        transcript: str = Form(...),
        language: str = Form("en"),
    ) -> dict[str, Any]:
        if not state["ready"]:
            raise HTTPException(503, state["error"] or "model is still loading", headers={"Retry-After": "5"})
        if language != "en":
            raise HTTPException(422, "only language=en is supported")
        if not ID_RE.match(dialogue_id):
            raise HTTPException(422, "invalid dialogue_id")
        transcript = " ".join(transcript.split())
        if not transcript:
            raise HTTPException(422, "transcript is empty")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(422, "audio is empty or too large")
        sha = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio.wav"
            path.write_bytes(data)
            async with gate:
                try:
                    raw = await run_in_threadpool(state["engine"].align, path, transcript)
                except HTTPException:
                    raise
                except Exception as exc:
                    log.exception("alignment failed")
                    raise HTTPException(500, f"alignment failed: {type(exc).__name__}") from exc
        resp = build_response(dialogue_id, sha, transcript, raw["words"])
        resp["quality"]["duration_s"] = round(raw["duration_s"], 4)
        if "asr_similarity" in raw:
            resp["quality"].update(asr_text=raw["asr_text"], asr_similarity=raw["asr_similarity"])
        return resp

    return app


app = create_app()
