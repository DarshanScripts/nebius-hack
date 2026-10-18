"""Small standalone Runtime for the scenes demo/tests (plan.md section 2/12).

Core's real Runtime (member 1) replaces this in the integrated API. It
implements the same protocol: checked artifact paths, atomic immutable
writes, structured output with bounded repair, and a progress callback.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from contracts.models import ArtifactRef, PipelineError, StageFailure


class FixtureRuntime:
    def __init__(
        self,
        artifact_root: Path,
        *,
        mock_mode: bool = True,
        settings: Mapping[str, Any] | None = None,
        llm: Any = None,
        structured_handler: Callable[[list[dict[str, str]], type[BaseModel]], BaseModel] | None = None,
    ) -> None:
        self.mock_mode = mock_mode
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.settings = dict(settings or {})
        self.llm = llm
        self._structured_handler = structured_handler
        self.progress_events: list[dict[str, Any]] = []

    def path(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key or "\0" in key or any(p in ("", "..") for p in key.split("/")):
            raise ValueError(f"invalid artifact key: {key!r}")
        full = (self.artifact_root / key).resolve()
        if self.artifact_root not in full.parents:
            raise ValueError(f"artifact key escapes root: {key!r}")
        return full

    async def write_bytes(self, key: str, data: bytes, media_type: str) -> ArtifactRef:
        full = self.path(key)
        sha = hashlib.sha256(data).hexdigest()
        if full.exists():
            if hashlib.sha256(full.read_bytes()).hexdigest() != sha:
                raise FileExistsError(f"refusing to overwrite immutable artifact {key}")
        else:
            full.parent.mkdir(parents=True, exist_ok=True)
            tmp = full.with_name(f".{full.name}.tmp-{os.getpid()}")
            tmp.write_bytes(data)
            tmp.replace(full)
        return ArtifactRef(key=key, media_type=media_type, sha256=sha, size_bytes=len(data))

    async def write_json(self, key: str, value: Any) -> ArtifactRef:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        data = json.dumps(value, indent=2, ensure_ascii=False).encode()
        return await self.write_bytes(key, data, "application/json")

    async def structured(self, *, messages: list[dict[str, str]], schema: type[BaseModel]) -> Any:
        if self._structured_handler is not None:
            return self._structured_handler(messages, schema)
        if self.llm is None:
            raise StageFailure(PipelineError(code="LLM_UNAVAILABLE", stage="structured", message="no LLM configured for this runtime"))
        # json_prompt strategy: normal call + model_validate_json + at most two corrections.
        convo = list(messages) + [{"role": "user", "content": "Reply with ONLY a JSON object matching this JSON Schema:\n" + json.dumps(schema.model_json_schema())}]
        last = ""
        for _ in range(3):
            reply = await self.llm.ainvoke(convo)
            text = _final_text(reply)
            try:
                return schema.model_validate_json(_strip_fence(text))
            except ValidationError as e:
                last = str(e)[:2000]
                convo += [{"role": "assistant", "content": text}, {"role": "user", "content": f"That JSON was invalid:\n{last}\nReturn the corrected JSON object only."}]
        raise StageFailure(PipelineError(code="STRUCTURED_OUTPUT_INVALID", stage="structured", message=last, retryable=True))

    async def report_progress(self, *, project_id: str, job_id: str, stage: str, progress: float, scene_id: str | None = None) -> None:
        self.progress_events.append({"project_id": project_id, "job_id": job_id, "stage": stage, "progress": progress, "scene_id": scene_id})


def _final_text(reply: Any) -> str:
    content = getattr(reply, "content", reply)
    if isinstance(content, list):  # content blocks: keep only final text, never reasoning
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content)


def _strip_fence(text: str) -> str:
    t = text.strip()
    if "</think>" in t:
        t = t.split("</think>", 1)[1].strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def live_llm_from_env() -> Any:
    """ChatOpenAI against the configured NEMOTRON_* endpoint (never a hardcoded provider)."""
    from langchain_openai import ChatOpenAI

    missing = [k for k in ("NEMOTRON_BASE_URL", "NEMOTRON_API_KEY", "NEMOTRON_MODEL") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"live mode needs {', '.join(missing)} in the environment")
    return ChatOpenAI(
        base_url=os.environ["NEMOTRON_BASE_URL"],
        api_key=os.environ["NEMOTRON_API_KEY"],
        model=os.environ["NEMOTRON_MODEL"],
        timeout=float(os.environ.get("NEMOTRON_TIMEOUT_SECONDS", "180")),
        temperature=0.2,
    )
