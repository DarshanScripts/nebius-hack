"""Run the real API using Nebius Token Factory, keeping existing module interfaces.

NEBIUS_API_KEY is server-only. It may be set in the environment or private .env.
Use --check for two small real capability requests without starting a server.
"""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel

from backend.core.config import ROOT, Settings
from backend.core.runtime import AppRuntime

BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"


def token_factory_settings(env_file: Path = ROOT / ".env", **overrides) -> Settings:
    values = {**dotenv_values(env_file), **os.environ}
    key = values.get("NEBIUS_API_KEY")
    if not key:
        raise ValueError("Set NEBIUS_API_KEY in your private .env or process environment.")
    # NEMOTRON_* names are retained as the existing Runtime/module interface.
    return Settings(
        _env_file=env_file, mock_mode=False, nemotron_base_url=BASE_URL,
        nemotron_api_key=key, nemotron_model=values.get("NEBIUS_MODEL") or DEFAULT_MODEL,
        nemotron_structured_mode="json_prompt", scene_agent_mode="single_call",
        nemotron_timeout_seconds=90, nemotron_max_tokens=4096, **overrides,
    )


class ProbeResult(BaseModel):
    ok: bool


async def check(settings: Settings) -> bool:
    runtime = AppRuntime(settings)
    report = {"provider": "Nebius Token Factory", "endpoint": BASE_URL,
              "model": settings.nemotron_model, "checks": {}}
    for mode in ("json_prompt", "tool_calling"):
        runtime._config.nemotron_structured_mode = mode
        started = time.monotonic()
        try:
            value = await runtime.structured(
                messages=[{"role": "user", "content": "Confirm this API check by returning ok=true."}],
                schema=ProbeResult,
            )
            report["checks"][mode] = {"passed": value.ok, "seconds": round(time.monotonic() - started, 2)}
        except Exception as exc:
            # Exception text/headers may contain provider details; report only type/code.
            error = getattr(exc, "error", None)
            report["checks"][mode] = {"passed": False, "error": error.code if error else type(exc).__name__}
    await runtime.write_json("capabilities/token-factory.json", report)
    print(json.dumps(report, indent=2))
    return all(result["passed"] for result in report["checks"].values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        settings = token_factory_settings(args.env_file)
    except ValueError:
        raise SystemExit("Set NEBIUS_API_KEY in the private .env or environment; check configuration values.") from None
    if args.check:
        raise SystemExit(0 if asyncio.run(check(settings)) else 1)
    import uvicorn
    from backend.app import create_app
    print(f"Text provider: Nebius Token Factory | model: {settings.nemotron_model} | mode: live")
    uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
