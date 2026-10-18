"""Standalone content demo: research -> dialogue -> images, with a small local Runtime.

    python -m backend.modules.content.demo --mock --output output/demos/content
    python -m backend.modules.content.demo --output output/demos/content --topic "..."   # live: needs .env keys
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from contracts.models import (
    ArtifactRef, CharacterSpec, DialogueRequest, ImageRequest, PipelineError, ResearchRequest, StageFailure,
)

from . import checks
from .service import find_images, generate_dialogue, run_research

PROJECT_ID = "demo-whatsapp-001"
TOPIC = "How does WhatsApp voice calling infrastructure work?"
CHARACTERS = [CharacterSpec(character_id="sundar", display_name="Sundar Pichai"),
              CharacterSpec(character_id="jensen", display_name="Jensen Huang")]


def _load_env(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


class DemoRuntime:
    """Implements contracts.models.Runtime for standalone runs. Core's runtime replaces it when integrated."""

    def __init__(self, root: Path, mock: bool, settings: dict[str, str]):
        self.mock_mode = mock
        self.artifact_root = root.resolve()
        self.settings = settings
        self.llm = None
        if not mock:
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(base_url=settings["NEMOTRON_BASE_URL"], api_key=settings["NEMOTRON_API_KEY"],
                                  model=settings["NEMOTRON_MODEL"], temperature=0.3, max_tokens=16384,
                                  max_retries=3,  # SDK backoff for transient 429/5xx (seen live: NVIDIA 500)
                                  timeout=float(settings.get("NEMOTRON_TIMEOUT_SECONDS", 180)))

    def path(self, key: str) -> Path:
        p = (self.artifact_root / key).resolve()
        if Path(key).is_absolute() or not p.is_relative_to(self.artifact_root):
            raise ValueError(f"artifact key escapes root: {key}")
        return p

    async def write_bytes(self, key: str, data: bytes, media_type: str) -> ArtifactRef:
        p = self.path(key)
        if p.exists():
            # Same immutability rule as core's AppRuntime: identical rewrites are fine, changes are not.
            if p.read_bytes() != data:
                raise ValueError(f"Refusing to overwrite immutable artifact: {key}")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        return ArtifactRef(key=key, media_type=media_type, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))

    async def write_json(self, key: str, value: Any) -> ArtifactRef:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return await self.write_bytes(key, data, "application/json")

    async def structured(self, *, messages, schema):
        """json_prompt strategy: plain call + model_validate_json, at most two corrective attempts."""
        if self.mock_mode:
            raise RuntimeError("structured() must not be called in mock mode")
        msgs = [*messages, {"role": "user", "content": "Respond with one JSON object matching this JSON Schema, no prose:\n"
                            + json.dumps(schema.model_json_schema())}]
        err = ""
        for _ in range(3):
            try:
                reply = await self.llm.ainvoke(msgs)
            except Exception as exc:  # same mapping as core's AppRuntime; provider text can carry headers/URLs
                raise StageFailure(PipelineError(code="MODEL_REQUEST_FAILED", stage="nemotron", retryable=True,
                                                 message=f"Nemotron request failed ({type(exc).__name__})")) from exc
            text = reply.content if isinstance(reply.content, str) else "".join(
                p.get("text", "") for p in reply.content if isinstance(p, dict))
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            try:
                return schema.model_validate_json(text)
            except Exception as exc:
                err = str(exc)[:2000]
                msgs = [*msgs, {"role": "assistant", "content": text},
                        {"role": "user", "content": f"That JSON is invalid:\n{err}\nReturn corrected JSON only."}]
        raise StageFailure(PipelineError(code="LLM_INVALID_OUTPUT", stage="structured", message=err, retryable=True))

    async def report_progress(self, **_: Any) -> None:
        return None


async def _write_once(rt: DemoRuntime, key: str, model) -> None:
    # A rerun of the same --project-id reuses saved Tavily results but gets fresh LLM output; keep the first copy.
    if not rt.path(key).exists():
        await rt.write_json(key, model.model_dump(mode="json"))


async def main(args: argparse.Namespace) -> int:
    settings = _load_env(Path(".env"))
    rt = DemoRuntime(Path(args.output), args.mock, settings)
    research = await run_research(ResearchRequest(project_id=args.project_id, topic=args.topic), rt)
    await _write_once(rt, f"projects/{args.project_id}/research/bundle.json", research)  # as core does
    print(f"research: {len(research.sources)} sources, {len(research.claims)} claims, mock={research.is_mock}, "
          f"request_id={research.tavily_request_id}")
    script = await generate_dialogue(DialogueRequest(project_id=args.project_id, research=research, characters=CHARACTERS), rt)
    await _write_once(rt, f"projects/{args.project_id}/script/v{script.script_revision}/script.json", script)  # as core does
    words = sum(checks.word_count(t.text) for t in script.turns)
    print(f"dialogue: rev {script.script_revision}, {len(script.turns)} turns, {words} words, title={script.title!r}")
    for t in script.turns:
        print(f"  {t.dialogue_id} s{t.scene_index} {t.speaker_id:6} {t.intent:9} {t.claim_ids} {t.text}")
    imgs = await find_images(ImageRequest(project_id=args.project_id, research=research, script=script), rt)
    for s in imgs.selections:
        print(f"  image s{s.query.scene_index:02d} {s.status:11} {s.asset.key if s.asset else s.reason}")
    print(f"artifacts under {rt.path(f'projects/{args.project_id}')}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="fixtures only; no provider calls")
    ap.add_argument("--output", default="output/demos/content")
    ap.add_argument("--topic", default=TOPIC)
    ap.add_argument("--project-id", default=PROJECT_ID)
    a = ap.parse_args()
    try:
        raise SystemExit(asyncio.run(main(a)))
    except StageFailure as exc:
        print(f"STAGE FAILURE: {exc.error.model_dump_json()}")
        raise SystemExit(2)
