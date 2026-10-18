"""Stand-alone voice demo.

    python -m backend.modules.voice.demo --mock --output output/demos/voice
    python -m backend.modules.voice.demo --live --env .env --assets assets --output output/demos/voice
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from contracts.models import ArtifactRef, CharacterSpec, DialogueScript, StageFailure, VoiceRequest

from . import audio
from .fake_runtime import FakeRuntime
from .service import synthesize_dialogue
from .validate import validate_bundle

FIXTURES = Path(__file__).parent / "fixtures"
MOCK_PREFIX = "MOCK FIXTURE: "


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("\"'")
    return {**env, **{k: v for k, v in os.environ.items() if k in env or k.endswith(("_URL", "_KEY"))}}


def load_inputs(live: bool) -> tuple[DialogueScript, list[CharacterSpec]]:
    script = json.loads((FIXTURES / "script.json").read_text(encoding="utf-8"))
    if live:
        for turn in script["turns"]:
            turn["text"] = turn["text"].removeprefix(MOCK_PREFIX)
        script["title"] = script["title"].removeprefix("MOCK: ")
    chars = json.loads((FIXTURES / "characters.json").read_text(encoding="utf-8"))
    return DialogueScript.model_validate(script), [CharacterSpec.model_validate(c) for c in chars]


async def attach_references(runtime: FakeRuntime, project_id: str, chars: list[CharacterSpec], assets: Path) -> None:
    for c in chars:
        src = assets / "voices" / c.character_id / "reference.wav"
        if not src.is_file():
            raise SystemExit(f"missing reference WAV: {src}")
        data = src.read_bytes()
        key = f"projects/{project_id}/inputs/voices/{c.character_id}/reference.wav"
        c.voice_reference = await runtime.write_bytes(key, data, "audio/wav")
        txt = src.with_name("reference.txt")
        if txt.is_file():
            c.reference_transcript = txt.read_text(encoding="utf-8").strip()


async def main_async(args: argparse.Namespace) -> int:
    out = Path(args.output)
    if out.exists() and args.clean:
        shutil.rmtree(out)
    settings = load_env(Path(args.env)) if args.live else {}
    runtime = FakeRuntime(out, mock_mode=not args.live, settings=settings)
    script, chars = load_inputs(args.live)
    if args.live:
        await attach_references(runtime, script.project_id, chars, Path(args.assets))
    request = VoiceRequest(project_id=script.project_id, script=script, characters=chars)
    try:
        bundle = await synthesize_dialogue(request, runtime)
    except StageFailure as exc:
        print(f"STAGE FAILURE {exc.error.code} (retryable={exc.error.retryable}): {exc.error.message}", file=sys.stderr)
        return 2
    print(f"mode={'live' if args.live else 'mock'} script_revision={bundle.script_revision}")
    for u in bundle.utterances:
        print(
            f"  {u.dialogue_id} {u.speaker_id:6s} {u.frame_count:4d} frames {u.duration_ms:5d} ms "
            f"{len(u.words):3d} words quality={u.timing_quality} {u.wav.key}"
        )
    print(f"total_speech_frames={bundle.total_speech_frames} ({bundle.total_speech_frames / 30:.2f}s, budget 1599)")
    problems = validate_bundle(bundle, script, runtime)
    print("acceptance checks:", "PASS" if not problems else "FAIL")
    for p in problems:
        print("  -", p)
    print("bundle:", runtime.path(f"projects/{script.project_id}/voice/v{script.script_revision}/bundle.json"))
    return 0 if not problems else 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="deterministic tone/synthetic timing; no services needed")
    mode.add_argument("--live", action="store_true", help="call the Chatterbox and WhisperX services from --env")
    p.add_argument("--output", default="output/demos/voice")
    p.add_argument("--env", default=".env")
    p.add_argument("--assets", default="assets")
    p.add_argument("--clean", action="store_true", help="delete the output directory first")
    sys.exit(asyncio.run(main_async(p.parse_args())))


if __name__ == "__main__":
    main()
