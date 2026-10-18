"""Small stand-alone Runtime implementation for demos and tests (not used by the integrated API)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from contracts.models import ArtifactRef


class FakeRuntime:
    def __init__(self, artifact_root: Path, *, mock_mode: bool, settings: dict[str, Any] | None = None):
        self.mock_mode = mock_mode
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.settings = settings or {}
        self.llm = None

    def path(self, key: str) -> Path:
        if not key or key.startswith(("/", "\\")) or ":" in key.split("/")[0]:
            raise ValueError(f"invalid artifact key: {key!r}")
        resolved = (self.artifact_root / key).resolve()
        if self.artifact_root != resolved and self.artifact_root not in resolved.parents:
            raise ValueError(f"artifact key escapes root: {key!r}")
        return resolved

    async def write_bytes(self, key: str, data: bytes, media_type: str) -> ArtifactRef:
        return await asyncio.to_thread(self._write, key, data, media_type)

    def _write(self, key: str, data: bytes, media_type: str) -> ArtifactRef:
        target = self.path(key)
        if target.exists():  # same rule as the platform runtime: artifacts are immutable, identical rewrites are fine
            if target.read_bytes() != data:
                raise ValueError(f"Refusing to overwrite immutable artifact: {key}")
            return ArtifactRef(key=key, media_type=media_type, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
        return ArtifactRef(key=key, media_type=media_type, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))

    async def write_json(self, key: str, value: Any) -> ArtifactRef:
        data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n"
        return await self.write_bytes(key, data, "application/json")

    async def structured(self, *, messages: list[dict[str, str]], schema: type) -> Any:
        raise NotImplementedError("the voice module makes no LLM calls")

    async def report_progress(self, **kwargs: Any) -> None:
        return None
