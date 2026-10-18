"""Small paid capability probes; no key or raw provider response is printed."""
import asyncio
import json
from datetime import datetime, timezone

import httpx

from backend.core.config import Settings


async def main():
    settings = Settings()
    key = settings.nemotron_api_key.get_secret_value()
    if not key:
        raise SystemExit("Set NEBIUS_API_KEY in the ignored .env first")
    result = {"model": settings.nemotron_model, "base_url": settings.nemotron_base_url,
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "json_prompt": False, "tool_calling": False, "selected_mode": None}
    body = {"model": settings.nemotron_model, "temperature": 0, "max_tokens": 256,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": 'Return only this JSON object: {"ok":true}'}]}
    async with httpx.AsyncClient(timeout=60) as client:
        endpoint = settings.nemotron_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}"}
        for mode in ("json_prompt", "tool_calling"):
            payload = dict(body)
            if mode == "tool_calling":
                payload["messages"] = [{"role": "user", "content": "Call record_probe with ok set to true."}]
                payload["tools"] = [{"type": "function", "function": {
                    "name": "record_probe", "description": "Record capability check",
                    "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                   "required": ["ok"], "additionalProperties": False}}}]
                payload["tool_choice"] = {"type": "function", "function": {"name": "record_probe"}}
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
                result[f"{mode}_http_status"] = response.status_code
                if response.is_success:
                    message = response.json()["choices"][0]["message"]
                    if mode == "json_prompt":
                        answer = message.get("content", "").strip()
                        if answer.startswith("```"):
                            answer = answer.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                        result[mode] = json.loads(answer) == {"ok": True}
                    else:
                        calls = message.get("tool_calls", [])
                        result[mode] = bool(calls and calls[0]["function"]["name"] == "record_probe"
                            and json.loads(calls[0]["function"]["arguments"]) == {"ok": True})
            except (httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError) as exc:
                result[f"{mode}_error_type"] = type(exc).__name__
    if result["tool_calling"]:
        result["selected_mode"] = "tool_calling"
    elif result["json_prompt"]:
        result["selected_mode"] = "json_prompt"
    target = settings.artifact_root / "capabilities/nemotron.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"Capability report: {target}")
    if result["selected_mode"]:
        print("Set NEMOTRON_STRUCTURED_MODE to the successful selected_mode; native JSON Schema support remains untested.")
    else:
        print("Neither mode passed. Check the configured endpoint/model/account before live inference.")


if __name__ == "__main__":
    asyncio.run(main())
