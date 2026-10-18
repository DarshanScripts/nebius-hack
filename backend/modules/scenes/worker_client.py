"""Async client for the Node render worker (POST /jobs, GET /jobs/{id}, POST /validate)."""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from contracts.models import FinalRenderRequest, PipelineError, PreviewRequest, RenderResult, SourceValidationResult, StageFailure


def setting(runtime: Any, name: str, default: Any = None) -> Any:
    """Read a server setting from runtime.settings (either case), falling back to the environment."""
    s = getattr(runtime, "settings", None) or {}
    for k in (name, name.lower()):
        if k in s and s[k] not in (None, ""):
            return s[k]
    return os.environ.get(name, default)


class RenderWorkerClient:
    def __init__(self, base_url: str, token: str | None, timeout_s: float, poll_interval_s: float = 1.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or ""
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s

    @classmethod
    def from_runtime(cls, runtime: Any) -> RenderWorkerClient:
        return cls(
            str(setting(runtime, "RENDER_WORKER_URL", "http://localhost:8001")),
            setting(runtime, "RENDER_WORKER_TOKEN", ""),
            float(setting(runtime, "RENDER_JOB_TIMEOUT_SECONDS", 900)),
            float(setting(runtime, "RENDER_POLL_INTERVAL_SECONDS", 1.0)),
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _fail(self, code: str, stage: str, message: str, retryable: bool, scene_id: str | None) -> StageFailure:
        return StageFailure(PipelineError(code=code, stage=stage, message=message, retryable=retryable, scene_id=scene_id))

    async def _request(self, method: str, path: str, *, json: Any = None, stage: str, scene_id: str | None) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as c:
                return await c.request(method, f"{self.base_url}{path}", json=json, headers=self._headers())
        except httpx.HTTPError as e:
            raise self._fail("RENDER_WORKER_UNAVAILABLE", stage, f"render worker at {self.base_url} unreachable: {e!r}", True, scene_id) from e

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            return str(resp.json().get("error", {}).get("message", resp.text))[:4000]
        except ValueError:
            return resp.text[:4000]

    async def health(self) -> dict[str, Any]:
        resp = await self._request("GET", "/health", stage="render_worker", scene_id=None)
        resp.raise_for_status()
        return resp.json()

    async def validate(self, request: PreviewRequest) -> SourceValidationResult:
        scene_id = request.slot.scene_id
        resp = await self._request("POST", "/validate", json=request.model_dump(mode="json"), stage="scene_validate", scene_id=scene_id)
        if resp.status_code == 401:
            raise self._fail("RENDER_WORKER_UNAUTHORIZED", "scene_validate", "render worker rejected RENDER_WORKER_TOKEN", False, scene_id)
        if resp.status_code != 200:
            raise self._fail("RENDER_WORKER_ERROR", "scene_validate", f"HTTP {resp.status_code}: {self._error_message(resp)}", True, scene_id)
        return SourceValidationResult.model_validate(resp.json())

    async def run(
        self,
        request: PreviewRequest | FinalRenderRequest,
        on_progress: Callable[[float], Awaitable[None]] | None = None,
    ) -> RenderResult:
        """Submit (idempotent) and poll until completed/failed or the deadline. Returns the terminal RenderResult."""
        stage = "final" if request.kind == "final" else "scene_preview"
        scene_id = None if request.kind == "final" else request.slot.scene_id
        body = request.model_dump(mode="json")
        deadline = time.monotonic() + self.timeout_s
        resubmits = 0

        async def submit() -> None:
            resp = await self._request("POST", "/jobs", json=body, stage=stage, scene_id=scene_id)
            if resp.status_code == 401:
                raise self._fail("RENDER_WORKER_UNAUTHORIZED", stage, "render worker rejected RENDER_WORKER_TOKEN", False, scene_id)
            if resp.status_code == 409:
                raise self._fail("JOB_ID_CONFLICT", stage, self._error_message(resp), False, scene_id)
            if resp.status_code == 422:
                raise self._fail("RENDER_INPUT_INVALID", stage, self._error_message(resp), False, scene_id)
            if resp.status_code != 202:
                raise self._fail("RENDER_WORKER_ERROR", stage, f"HTTP {resp.status_code}: {self._error_message(resp)}", True, scene_id)

        await submit()
        while True:
            if time.monotonic() > deadline:
                raise self._fail("RENDER_TIMEOUT", stage, f"render job {request.job_id} exceeded {self.timeout_s:.0f}s", True, scene_id)
            resp = await self._request("GET", f"/jobs/{request.job_id}", stage=stage, scene_id=scene_id)
            if resp.status_code == 404 and resubmits < 1:
                resubmits += 1  # worker restarted and lost its in-memory queue: resubmit the identical input once
                await submit()
                continue
            if resp.status_code != 200:
                raise self._fail("RENDER_WORKER_ERROR", stage, f"HTTP {resp.status_code}: {self._error_message(resp)}", True, scene_id)
            result = RenderResult.model_validate(resp.json())
            if on_progress is not None:
                await on_progress(result.progress)
            if result.status in ("completed", "failed"):
                return result
            await asyncio.sleep(self.poll_interval_s)
