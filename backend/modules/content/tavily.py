"""Minimal Tavily REST adapter: research create/poll and image search."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import httpx

from contracts.models import PipelineError, StageFailure

BASE_URL = "https://api.tavily.com"
RUNNING = {"pending", "in_progress", "processing"}
MAX_TRIES = 4


def _fail(stage: str, code: str, message: str, retryable: bool = False) -> StageFailure:
    return StageFailure(PipelineError(code=code, stage=stage, message=message, retryable=retryable))


def make_client(api_key: str) -> httpx.AsyncClient:
    # Tests monkeypatch this to inject httpx.MockTransport.
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=httpx.Timeout(60.0, connect=15.0),
    )


async def _request(client: httpx.AsyncClient, stage: str, method: str, url: str, **kw: Any) -> dict:
    """One JSON call with bounded backoff on network/429/5xx; auth/input errors fail at once."""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            resp = await client.request(method, url, **kw)
        except httpx.TransportError as exc:
            if attempt == MAX_TRIES:
                raise _fail(stage, "TAVILY_UNAVAILABLE", f"Tavily network error: {exc}", True) from exc
            await asyncio.sleep(2 ** attempt)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == MAX_TRIES:
                raise _fail(stage, "TAVILY_UNAVAILABLE", f"Tavily HTTP {resp.status_code} after {attempt} tries", True)
            try:
                delay = min(float(resp.headers.get("Retry-After", "")), 60.0)
            except ValueError:
                delay = float(2 ** attempt)
            await asyncio.sleep(delay)
            continue
        if resp.status_code in (401, 403):
            raise _fail(stage, "TAVILY_AUTH", f"Tavily rejected the API key (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise _fail(stage, "TAVILY_BAD_REQUEST", f"Tavily HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise _fail(stage, "TAVILY_BAD_RESPONSE", "Tavily returned non-JSON", True) from exc
        if not isinstance(data, dict):
            raise _fail(stage, "TAVILY_BAD_RESPONSE", "Tavily returned a non-object JSON body", True)
        return data
    raise AssertionError("unreachable")


async def create_research(client: httpx.AsyncClient, query: str, model: str) -> dict:
    data = await _request(client, "research", "POST", "/research",
                          json={"input": query, "model": model, "stream": False})
    if not data.get("request_id"):
        raise _fail("research", "TAVILY_BAD_RESPONSE", "Tavily research response has no request_id")
    return data


async def poll_research(
    client: httpx.AsyncClient,
    request_id: str,
    *,
    interval: float,
    deadline_s: float,
    on_poll: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """Poll until completed. Returns the completed raw JSON; failure/unknown status raises."""
    stop = time.monotonic() + deadline_s
    while True:
        data = await _request(client, "research", "GET", f"/research/{request_id}")
        status = str(data.get("status", "")).lower()
        if status == "completed":
            return data
        if status == "failed":
            raise _fail("research", "TAVILY_RESEARCH_FAILED",
                        f"Tavily research {request_id} failed: {str(data.get('error', ''))[:300]}")
        if status not in RUNNING:
            raise _fail("research", "TAVILY_BAD_RESPONSE", f"Unknown Tavily research status {status!r}")
        if on_poll:
            await on_poll(status)
        if time.monotonic() >= stop:
            # Request ID is saved by the caller; a retry resumes polling instead of re-paying.
            raise _fail("research", "TAVILY_RESEARCH_TIMEOUT",
                        f"Tavily research {request_id} still {status} after {deadline_s:.0f}s", True)
        await asyncio.sleep(interval)


async def search_images(client: httpx.AsyncClient, query: str) -> dict:
    return await _request(client, "images", "POST", "/search", json={
        "query": query,
        "include_images": True,
        "include_image_descriptions": True,
        "max_results": 5,
    })
