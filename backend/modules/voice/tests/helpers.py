"""Fake GPU engines + ASGI routing so the real FastAPI service apps are exercised without torch/GPU."""

from __future__ import annotations

import importlib.util
import io
import wave
from pathlib import Path

import httpx
import numpy as np

from backend.modules.voice import clients
from backend.modules.voice.demo import attach_references, load_inputs
from backend.modules.voice.fake_runtime import FakeRuntime

GPU = Path(__file__).resolve().parents[1] / "gpu_services"


def load_service(name: str):
    spec = importlib.util.spec_from_file_location(f"svc_{name}", GPU / name / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeChatterbox:
    """Voiced tone of words * seconds_per_word surrounded by silence, at the native 24 kHz."""

    device, sr = "fake", 24000

    def __init__(self, seconds_per_word=0.3, silent_attempts=0):
        self.spw, self.calls, self.silent_attempts = seconds_per_word, [], silent_attempts

    def synthesize(self, text, ref_path, ref_sha, seed):
        self.calls.append((text, ref_sha, seed))
        n = int(len(text.split()) * self.spw * self.sr)
        pad = np.zeros(int(0.3 * self.sr), dtype=np.float32)
        t = np.arange(n) / self.sr
        body = (0.4 * np.sin(2 * np.pi * 200 * t) + 0.2 * np.sin(2 * np.pi * 400 * t)).astype(np.float32)
        if len(self.calls) <= self.silent_attempts:
            body = np.zeros_like(body)
        return np.concatenate([pad, body, pad])


class FakeAligner:
    """Finds the voiced region of the uploaded WAV and spreads words across it by character count."""

    device, align_model_name = "fake", "fake"

    def __init__(self, drop_last_word_calls=0, mean_score=0.8):
        self.drop, self.calls, self.mean_score = drop_last_word_calls, 0, mean_score

    def align(self, wav_path, transcript):
        with wave.open(str(wav_path), "rb") as w:
            rate, raw = w.getframerate(), w.readframes(w.getnframes())
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
        active = np.flatnonzero(np.abs(x) > 0.02)
        first, last = active[0] / rate, (active[-1] + 1) / rate
        tokens = transcript.split()
        weights = np.array([len(t) for t in tokens], dtype=float)
        edges = first + (last - first) * np.concatenate([[0], np.cumsum(weights) / weights.sum()])
        words = [
            {"word": tok, "start": float(edges[i]), "end": float(edges[i + 1]), "score": self.mean_score}
            for i, tok in enumerate(tokens)
        ]
        self.calls += 1
        if self.calls <= self.drop:
            words = words[:-1]
        return {"words": words, "duration_s": len(x) / rate}


class Router(httpx.AsyncBaseTransport):
    def __init__(self, tts_app, align_app):
        self.by_port = {8002: httpx.ASGITransport(app=tts_app), 8003: httpx.ASGITransport(app=align_app)}

    async def handle_async_request(self, request):
        return await self.by_port[request.url.port].handle_async_request(request)


def install_services(monkeypatch, chatterbox, aligner, *, voice_key="vk", align_key="ak"):
    tts = load_service("chatterbox").create_app(chatterbox, api_key=voice_key)
    aln = load_service("whisperx").create_app(aligner, api_key=align_key)
    monkeypatch.setattr(
        clients, "make_http_client", lambda timeout: httpx.AsyncClient(transport=Router(tts, aln), timeout=timeout)
    )


def live_runtime(tmp_path, *, voice_key="vk", align_key="ak") -> FakeRuntime:
    return FakeRuntime(
        tmp_path / "out",
        mock_mode=False,
        settings={"VOICE_API_KEY": voice_key, "ALIGNMENT_API_KEY": align_key, "VOICE_TIMEOUT_SECONDS": 30},
    )


async def live_request(runtime, *, with_references=True):
    from contracts.models import VoiceRequest

    script, chars = load_inputs(live=True)
    if with_references:
        assets = runtime.artifact_root.parent / "assets"
        for cid in ("sundar", "jensen"):
            d = assets / "voices" / cid
            d.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                t = np.arange(24000 * 6) / 24000
                tone = 110 if cid == "jensen" else 180
                w.writeframes((np.sin(2 * np.pi * tone * t) * 8000).astype("<i2").tobytes())
            (d / "reference.wav").write_bytes(buf.getvalue())
        await attach_references(runtime, script.project_id, chars, assets)
    return VoiceRequest(project_id=script.project_id, script=script, characters=chars), script
