"""Exercise the frozen speech contracts against deployed services, using .env.

Requires a reference WAV, FFmpeg, and the root Python environment. This script is
a client for Member 3's services; it does not install or implement those services.
"""
import argparse
import asyncio
import hashlib
import io
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path
from uuid import uuid4

import httpx

from backend.core.config import Settings
from contracts.models import AlignmentResult

TEXT = "This is a generated demonstration of voice synthesis and word alignment."


def finalize_wav(raw_path: Path, normalized_path: Path) -> tuple[bytes, int]:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Install FFmpeg before running this check")
    result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(raw_path), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(normalized_path)],
        capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError("FFmpeg could not decode/normalize the speech service response")
    with wave.open(str(normalized_path), "rb") as stream:
        count = stream.getnframes()
        if count <= 0:
            raise RuntimeError("Speech service returned empty audio")
        pcm = stream.readframes(count)
    padded = ((count + 1599) // 1600) * 1600
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(pcm + b"\0\0" * (padded-count))
    data = buffer.getvalue()
    normalized_path.write_bytes(data)
    return data, padded


async def check(args):
    settings = Settings()
    reference = settings.assets_root / f"voices/{args.character}/reference.wav"
    if not reference.is_file():
        raise RuntimeError(f"Upload the reference WAV to {reference}")
    voice_key = settings.voice_api_key.get_secret_value()
    alignment_key = settings.alignment_api_key.get_secret_value()
    if not voice_key or not alignment_key:
        raise RuntimeError("Fill VOICE_API_KEY and ALIGNMENT_API_KEY with the deployed services' shared secrets")
    output = args.output / f"{args.character}-{uuid4().hex[:12]}"
    output.mkdir(parents=True, exist_ok=False)
    async with httpx.AsyncClient(follow_redirects=False) as client:
        response = await client.post(settings.voice_api_url, headers={"Authorization": f"Bearer {voice_key}"},
            data={"text": TEXT, "dialogue_id": "d001", "model": settings.voice_model},
            files={"reference_audio": ("reference.wav", reference.read_bytes(), "audio/wav")},
            timeout=settings.voice_timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError(f"TTS returned HTTP {response.status_code}; inspect the service logs")
        if "audio/" not in response.headers.get("content-type", ""):
            raise RuntimeError("TTS response is not an audio payload; check the URL and any login proxy")
        raw = output / "raw.wav"
        raw.write_bytes(response.content)
        audio, sample_count = finalize_wav(raw, output / "audio.wav")
        response = await client.post(settings.alignment_api_url,
            headers={"Authorization": f"Bearer {alignment_key}"},
            data={"dialogue_id": "d001", "transcript": TEXT, "language": "en"},
            files={"audio": ("audio.wav", audio, "audio/wav")}, timeout=settings.alignment_timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError(f"Alignment returned HTTP {response.status_code}; inspect the service logs")
        payload = response.json()
        # Service diagnostics are outside the frozen application model.
        (output / "alignment_raw.json").write_text(json.dumps(payload, indent=2) + "\n")
        alignment = AlignmentResult.model_validate({name: payload[name] for name in AlignmentResult.model_fields})
    digest = hashlib.sha256(audio).hexdigest()
    if alignment.dialogue_id != "d001" or alignment.transcript != TEXT or alignment.audio_sha256 != digest:
        raise RuntimeError("Alignment identity/transcript/SHA does not match the exact normalized WAV")
    end = 0
    for index, word in enumerate(alignment.words, 1):
        if word.word_id != f"d001_w{index:03}" or not end <= word.start_ms < word.end_ms <= round(sample_count*1000/48000):
            raise RuntimeError("Word IDs or timestamps violate the clip-local timing contract")
        end = word.end_ms
    normalize = lambda value: "".join(re.findall(r"\w+", value.casefold()))
    if normalize(" ".join(w.text for w in alignment.words)) != normalize(TEXT):
        raise RuntimeError("Alignment omitted or changed spoken words")
    (output / "words.json").write_text(alignment.model_dump_json(indent=2) + "\n")
    (output / "transcript.txt").write_text(TEXT + "\n")
    summary = {"character": args.character, "sample_rate_hz": 48000, "channels": 1,
        "sample_count": sample_count, "frame_count": sample_count // 1600, "audio_sha256": digest,
        "aligned_words": len(alignment.words), "audio": str(output / "audio.wav"),
        "alignment": str(output / "words.json"), "contract_check_passed": True}
    (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print("Listen to audio.wav and inspect words.json. This check does not measure speaker similarity or perceptual alignment accuracy.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--character", choices=["sundar", "jensen"], default="sundar")
    parser.add_argument("--output", type=Path, default=Path("output/speech-check"))
    args = parser.parse_args()
    try:
        asyncio.run(check(args))
    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
        # HTTP client exception strings can include query parameters; keep them private.
        message = str(exc) if isinstance(exc, RuntimeError) else f"Request/contract failure ({type(exc).__name__})"
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
