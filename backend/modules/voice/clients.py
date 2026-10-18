from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import ValidationError

from contracts.models import AlignmentResult

from .config import VoiceSettings
from .errors import fail

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


def make_http_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))


async def _post(
    http: httpx.AsyncClient, url: str, key: str, *, service: str, attempts: int, **kwargs: Any
) -> httpx.Response:
    if not key:
        raise fail(f"{service}_NOT_CONFIGURED", f"{service.lower()} bearer key is not configured", retryable=False)
    last = "no response"
    for attempt in range(attempts):
        retry_after = None
        try:
            resp = await http.post(url, headers={"Authorization": f"Bearer {key}"}, **kwargs)
        except httpx.TransportError as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code < 400:
                return resp
            detail = resp.text[:300]
            if resp.status_code in (401, 403):
                raise fail(f"{service}_AUTH_FAILED", f"{url} rejected the bearer token ({resp.status_code})")
            if resp.status_code not in TRANSIENT_STATUS:
                raise fail(f"{service}_REJECTED", f"{url} returned {resp.status_code}: {detail}")
            last = f"HTTP {resp.status_code}: {detail}"
            try:
                retry_after = min(float(resp.headers.get("Retry-After", "")), 30.0)
            except ValueError:
                pass
        if attempt + 1 < attempts:
            await asyncio.sleep(retry_after if retry_after is not None else min(2.0**attempt, 8.0))
    raise fail(f"{service}_UNAVAILABLE", f"{url} unavailable after {attempts} attempts ({last})", retryable=True)


class ChatterboxClient:
    def __init__(self, http: httpx.AsyncClient, cfg: VoiceSettings):
        self.http, self.cfg = http, cfg

    async def synthesize(self, *, text: str, dialogue_id: str, reference_wav: bytes, seed: int | None = None) -> bytes:
        data = {"text": text, "dialogue_id": dialogue_id, "model": self.cfg.voice_model}
        if seed is not None:
            data["seed"] = str(seed)
        resp = await _post(
            self.http, self.cfg.voice_api_url, self.cfg.voice_api_key, service="VOICE",
            attempts=self.cfg.max_attempts, data=data,
            files={"reference_audio": ("reference.wav", reference_wav, "audio/wav")},
        )
        return resp.content


class WhisperXClient:
    def __init__(self, http: httpx.AsyncClient, cfg: VoiceSettings):
        self.http, self.cfg = http, cfg

    async def align(self, *, wav: bytes, dialogue_id: str, transcript: str) -> tuple[AlignmentResult, dict[str, Any]]:
        resp = await _post(
            self.http, self.cfg.alignment_api_url, self.cfg.alignment_api_key, service="ALIGNMENT",
            attempts=self.cfg.max_attempts,
            data={"dialogue_id": dialogue_id, "transcript": transcript, "language": "en"},
            files={"audio": ("audio.wav", wav, "audio/wav")},
        )
        try:
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("words") == []:
                raise fail("ALIGNMENT_INCOMPLETE", f"{dialogue_id}: aligner returned no timed words", retryable=True)
            result = AlignmentResult.model_validate({k: payload[k] for k in AlignmentResult.model_fields})
        except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
            raise fail("ALIGNMENT_BAD_RESPONSE", f"Alignment service response invalid: {exc}", retryable=True) from exc
        return result, payload
