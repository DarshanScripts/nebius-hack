"""Artifact IO and the one configured LangChain/Nemotron client."""
import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import ValidationError

from backend.core.config import Settings
from contracts.models import ArtifactRef, PipelineError, StageFailure, T
from contracts.validation import artifact_path, canonical_json


def atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class AppRuntime:
    def __init__(self, settings: Settings, progress: Callable[..., Awaitable[None]] | None = None):
        self.mock_mode = settings.mock_mode
        self.artifact_root = settings.artifact_root.resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.settings = settings.runtime_mapping()
        self._config = settings
        self._llm = None
        self._progress = progress
        self._write_lock = asyncio.Lock()

    @property
    def llm(self):
        if self._llm is None:
            if not self._config.nemotron_api_key.get_secret_value():
                raise StageFailure(PipelineError(code="MISSING_CONFIGURATION", stage="nemotron",
                                                 message="NEMOTRON_API_KEY is required"))
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                base_url=self._config.nemotron_base_url,
                api_key=self._config.nemotron_api_key.get_secret_value(),
                model=self._config.nemotron_model, temperature=0.3, max_tokens=16384,
                timeout=self._config.nemotron_timeout_seconds, max_retries=1,
            )
        return self._llm

    def path(self, key: str) -> Path:
        return artifact_path(self.artifact_root, key)

    async def write_bytes(self, key: str, data: bytes, media_type: str) -> ArtifactRef:
        path = self.path(key)
        # Immutable versioned artifacts: identical retries are idempotent.
        async with self._write_lock:
            if path.exists():
                if await asyncio.to_thread(path.read_bytes) != data:
                    raise ValueError(f"Refusing to overwrite immutable artifact: {key}")
            else:
                await asyncio.to_thread(atomic_replace, path, data)
        return ArtifactRef(key=key, media_type=media_type,
                           sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))

    async def write_json(self, key: str, value) -> ArtifactRef:
        return await self.write_bytes(key, canonical_json(value), "application/json")

    async def structured(self, *, messages: list[dict[str, str]], schema: type[T]) -> T:
        if self.mock_mode:
            raise StageFailure(PipelineError(code="MOCK_LLM_DISABLED", stage="nemotron",
                                             message="Mock modules must return explicit fixtures"))
        conversation = list(messages)
        mode = self._config.nemotron_structured_mode
        if mode == "json_prompt":
            conversation.insert(0, {"role": "system", "content":
                "Return ONLY one JSON object, with no reasoning or commentary. Match this JSON Schema: "
                + json.dumps(schema.model_json_schema())})
        for attempt in range(3):
            try:
                if mode == "tool_calling":
                    model = self.llm.with_structured_output(schema, method="function_calling")
                    result = await model.ainvoke(conversation)
                    return result if isinstance(result, schema) else schema.model_validate(result)
                response = await self.llm.ainvoke(conversation)
                # reasoning_content/additional_kwargs are deliberately never parsed.
                content = response.content
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content
                                      if isinstance(part, dict) and part.get("type") == "text")
                answer = content.strip()
                if answer.startswith("```") and answer.endswith("```"):
                    answer = answer.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return schema.model_validate_json(answer)
            except (ValidationError, ValueError, TypeError) as exc:
                if attempt == 2:
                    raise StageFailure(PipelineError(code="STRUCTURED_OUTPUT_INVALID", stage="nemotron",
                        message=f"{schema.__name__} failed validation after three attempts", retryable=True)) from exc
                conversation.append({"role": "user", "content":
                    f"Your last result did not validate: {str(exc)[:2500]}. Return the corrected JSON object."})
            except StageFailure:
                raise
            except Exception as exc:
                # Provider exception strings can contain sensitive headers/URLs. Keep public errors generic.
                raise StageFailure(PipelineError(code="MODEL_REQUEST_FAILED", stage="nemotron",
                    message="The configured Nemotron request failed; check connectivity/model/account", retryable=True)) from exc
        raise AssertionError("unreachable")

    async def report_progress(self, *, project_id: str, job_id: str, stage: str,
                              progress: float, scene_id: str | None = None) -> None:
        if not 0 <= progress <= 1:
            raise ValueError("Progress must be between 0 and 1")
        if self._progress:
            await self._progress(project_id=project_id, job_id=job_id, stage=stage,
                                 progress=progress, scene_id=scene_id)
