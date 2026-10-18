from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from contracts.models import (
    AlignmentResult,
    AudioBundle,
    CharacterSpec,
    DialogueTurn,
    Runtime,
    UtteranceAudio,
    VoiceRequest,
)

from . import audio, clients, mock
from .config import MAX_SPEEDUP, SAMPLE_RATE, SPEEDUP_STEP, VoiceSettings
from .errors import fail
from .text import build_srt, build_words, normalize_transcript, tokenize

RESYNTH_CODES = {
    "ALIGNMENT_INCOMPLETE",
    "ALIGNMENT_INVALID",
    "ALIGNMENT_LOW_CONFIDENCE",
    "ALIGNMENT_TEXT_MISMATCH",
    "VOICE_SILENT_AUDIO",
    "VOICE_IMPLAUSIBLE_AUDIO",
}
MIN_SEC_PER_WORD, MAX_SEC_PER_WORD = 0.12, 1.5


class Provider(Protocol):
    timing_quality: str
    is_mock: bool

    async def synthesize(self, turn: DialogueTurn, attempt: int) -> tuple[np.ndarray, int]: ...

    async def align(self, turn: DialogueTurn, wav: bytes) -> tuple[AlignmentResult, dict[str, Any]]: ...


class MockProvider:
    timing_quality = "mock"
    is_mock = True

    async def synthesize(self, turn: DialogueTurn, attempt: int) -> tuple[np.ndarray, int]:
        return mock.mock_audio(turn.speaker_id, turn.text), SAMPLE_RATE

    async def align(self, turn: DialogueTurn, wav: bytes) -> tuple[AlignmentResult, dict[str, Any]]:
        result = mock.mock_alignment(turn.dialogue_id, normalize_transcript(turn.text), wav)
        return result, result.model_dump(mode="json")


class LiveProvider:
    timing_quality = "forced_alignment"
    is_mock = False

    def __init__(self, runtime: Runtime, cfg: VoiceSettings, characters: dict[str, CharacterSpec], http: Any):
        self.runtime, self.cfg, self.characters = runtime, cfg, characters
        self.tts = clients.ChatterboxClient(http, cfg)
        self.aligner = clients.WhisperXClient(http, cfg)
        self._refs: dict[str, bytes] = {}

    def reference_wav(self, speaker_id: str) -> bytes:
        if speaker_id not in self._refs:
            ref = self.characters[speaker_id].voice_reference
            if ref is None:
                raise fail(
                    "VOICE_REFERENCE_MISSING",
                    f"Character '{speaker_id}' has no voice_reference; Chatterbox needs a reference WAV",
                )
            path = self.runtime.path(ref.key)
            if not path.is_file():
                raise fail("VOICE_REFERENCE_MISSING", f"Voice reference not found for '{speaker_id}': {ref.key}")
            data = path.read_bytes()
            if audio.sha256_hex(data) != ref.sha256:
                raise fail("VOICE_REFERENCE_MISMATCH", f"Voice reference for '{speaker_id}' does not match its sha256")
            self._refs[speaker_id] = data
        return self._refs[speaker_id]

    async def synthesize(self, turn: DialogueTurn, attempt: int) -> tuple[np.ndarray, int]:
        data = await self.tts.synthesize(
            text=normalize_transcript(turn.text),
            dialogue_id=turn.dialogue_id,
            reference_wav=self.reference_wav(turn.speaker_id),
            seed=turn.order * 100 + attempt,
        )
        return audio.decode_wav(data)

    async def align(self, turn: DialogueTurn, wav: bytes) -> tuple[AlignmentResult, dict[str, Any]]:
        result, payload = await self.aligner.align(
            wav=wav, dialogue_id=turn.dialogue_id, transcript=normalize_transcript(turn.text)
        )
        quality = payload.get("quality") or {}
        mean_score, similarity = quality.get("mean_score"), quality.get("asr_similarity")
        if mean_score is not None and mean_score < self.cfg.min_align_score:
            raise fail(
                "ALIGNMENT_LOW_CONFIDENCE",
                f"{turn.dialogue_id}: alignment confidence {mean_score:.2f} < {self.cfg.min_align_score}",
                retryable=True,
            )
        if similarity is not None and similarity < self.cfg.min_asr_similarity:
            raise fail(
                "ALIGNMENT_TEXT_MISMATCH",
                f"{turn.dialogue_id}: ASR transcript matches the script only {similarity:.2f}",
                retryable=True,
            )
        return result, payload


@dataclass
class Clip:
    turn: DialogueTurn
    samples: np.ndarray  # prepared 48 kHz mono, before speed/padding


@dataclass
class Final:
    wav: bytes
    sha: str
    frames: int
    sample_count: int
    duration_ms: int
    words: list
    provider_payload: dict[str, Any]


def _validate_request(request: VoiceRequest) -> dict[str, CharacterSpec]:
    chars = {c.character_id: c for c in request.characters}
    if len(chars) != 2:
        raise fail("VOICE_REQUEST_INVALID", "Exactly one CharacterSpec per speaker is required")
    if request.script.project_id != request.project_id:
        raise fail("VOICE_REQUEST_INVALID", "Script belongs to a different project")
    for i, turn in enumerate(request.script.turns, 1):
        if turn.order != i or turn.dialogue_id != f"d{i:03d}":
            raise fail("VOICE_REQUEST_INVALID", f"Turn {i} must have order {i} and id d{i:03d}")
        if turn.speaker_id not in chars:
            raise fail("VOICE_REQUEST_INVALID", f"No character for speaker '{turn.speaker_id}'")
        if not any(t.meaningful for t in tokenize(turn.text)):
            raise fail("VOICE_REQUEST_INVALID", f"{turn.dialogue_id} has no speakable words")
    return chars


def _prepare(provider: Provider, turn: DialogueTurn, raw: np.ndarray, rate: int) -> np.ndarray:
    x = audio.resample(raw, rate)
    if not provider.is_mock:
        x = audio.trim_silence(x)
        words = sum(1 for t in tokenize(turn.text) if t.meaningful)
        seconds = len(x) / SAMPLE_RATE
        if not MIN_SEC_PER_WORD * words <= seconds <= MAX_SEC_PER_WORD * words + 3.0:
            raise fail(
                "VOICE_IMPLAUSIBLE_AUDIO",
                f"{turn.dialogue_id}: {seconds:.1f}s of audio for {words} words",
                retryable=True,
            )
    return audio.normalize_level(x)


def _finalize(clip: Clip, speed: float) -> tuple[bytes, int, int]:
    x = audio.time_stretch(clip.samples, speed)
    padded, frames = audio.pad_to_frames(x)
    return audio.encode_wav_pcm16(padded), frames, len(padded)


def _total_frames(clips: list[Clip], speed: float) -> int:
    return sum(audio.frames_for(audio.stretched_length(len(c.samples), speed)) for c in clips)


def _choose_speed(clips: list[Clip], budget: int) -> float:
    if _total_frames(clips, 1.0) <= budget:
        return 1.0
    steps = int(round((MAX_SPEEDUP - 1.0) / SPEEDUP_STEP))
    for k in range(1, steps + 1):
        speed = round(1.0 + k * SPEEDUP_STEP, 4)
        if _total_frames(clips, speed) <= budget:
            return speed
    raise _over_budget(_total_frames(clips, MAX_SPEEDUP), budget)


def _over_budget(measured: int, budget: int, speed: float = MAX_SPEEDUP):
    return fail(
        "AUDIO_DURATION_OUT_OF_RANGE",
        f"measured_frames={measured} ({measured / 30:.2f}s) exceeds budget_frames={budget} "
        f"({budget / 30:.2f}s) at {speed}x speed (maximum allowed {MAX_SPEEDUP}x); shorten the script",
    )


async def _synth_prepared(provider: Provider, turn: DialogueTurn, attempt: int, retries: int) -> tuple[Clip, int]:
    while True:
        try:
            raw, rate = await provider.synthesize(turn, attempt)
            samples = await asyncio.to_thread(_prepare, provider, turn, raw, rate)
            return Clip(turn, samples), attempt
        except Exception as exc:
            code = getattr(getattr(exc, "error", None), "code", None)
            if code not in RESYNTH_CODES or attempt >= retries:
                raise
            attempt += 1


async def _align_clip(provider: Provider, clip: Clip, speed: float, retries: int, attempt: int) -> tuple[Clip, Final]:
    turn = clip.turn
    while True:
        wav, frames, sample_count = await asyncio.to_thread(_finalize, clip, speed)
        sha = audio.sha256_hex(wav)
        duration_ms = round(sample_count * 1000 / SAMPLE_RATE)
        try:
            result, payload = await provider.align(turn, wav)
            if result.audio_sha256 != sha or result.dialogue_id != turn.dialogue_id:
                raise fail(
                    "ALIGNMENT_AUDIO_MISMATCH",
                    f"{turn.dialogue_id}: aligner reported a different audio hash than the canonical WAV",
                    retryable=True,
                )
            words = build_words(turn.dialogue_id, turn.text, result.words, duration_ms)
            return clip, Final(wav, sha, frames, sample_count, duration_ms, words, payload)
        except Exception as exc:
            code = getattr(getattr(exc, "error", None), "code", None)
            if code not in RESYNTH_CODES or attempt >= retries:
                raise
            attempt += 1
            clip, attempt = await _synth_prepared(provider, turn, attempt, retries)


async def _write_clip(runtime: Runtime, base: str, clip: Clip, final: Final, quality: str) -> UtteranceAudio:
    turn = clip.turn
    key = f"{base}/{turn.dialogue_id}"
    wav = await runtime.write_bytes(f"{key}/audio.wav", final.wav, "audio/wav")
    transcript = await runtime.write_bytes(f"{key}/transcript.txt", (turn.text + "\n").encode(), "text/plain")
    words_doc = {
        "dialogue_id": turn.dialogue_id,
        "audio_sha256": final.sha,
        "transcript": turn.text,
        "words": [w.model_dump(mode="json") for w in final.words],
    }
    words_file = await runtime.write_bytes(
        f"{key}/words.json", (json.dumps(words_doc, ensure_ascii=False, indent=2) + "\n").encode(), "application/json"
    )
    srt = await runtime.write_bytes(f"{key}/subtitles.srt", build_srt(final.words).encode(), "application/x-subrip")
    await runtime.write_json(f"{key}/alignment_raw.json", final.provider_payload)
    return UtteranceAudio(
        dialogue_id=turn.dialogue_id,
        speaker_id=turn.speaker_id,
        wav=wav,
        transcript=turn.text,
        transcript_file=transcript,
        words_file=words_file,
        srt_file=srt,
        duration_ms=final.duration_ms,
        frame_count=final.frames,
        sample_count=final.sample_count,
        words=final.words,
        timing_quality=quality,
    )


async def _run(provider: Provider, request: VoiceRequest, runtime: Runtime, cfg: VoiceSettings) -> AudioBundle:
    turns = sorted(request.script.turns, key=lambda t: t.order)
    retries = 0 if provider.is_mock else cfg.resynth_attempts
    clips: list[tuple[Clip, int]] = []
    for turn in turns:
        clips.append(await _synth_prepared(provider, turn, 0, retries))
    speed = _choose_speed([c for c, _ in clips], request.max_speech_frames)

    finals: list[tuple[Clip, Final]] = []
    for clip, attempt in clips:
        finals.append(await _align_clip(provider, clip, speed, retries, attempt))
    total = sum(f.frames for _, f in finals)
    if total > request.max_speech_frames:
        raise _over_budget(total, request.max_speech_frames, speed)

    base = f"projects/{request.project_id}/voice/v{request.script.script_revision}"
    utterances = [await _write_clip(runtime, base, c, f, provider.timing_quality) for c, f in finals]
    bundle = AudioBundle(
        project_id=request.project_id,
        script_revision=request.script.script_revision,
        utterances=utterances,
        total_speech_frames=total,
    )
    await runtime.write_json(f"{base}/bundle.json", bundle.model_dump(mode="json"))
    return bundle


async def synthesize_dialogue(request: VoiceRequest, runtime: Runtime) -> AudioBundle:
    cfg = VoiceSettings.from_mapping(runtime.settings)
    characters = _validate_request(request)
    if runtime.mock_mode:
        return await _run(MockProvider(), request, runtime, cfg)
    async with clients.make_http_client(max(cfg.voice_timeout, cfg.alignment_timeout)) as http:
        return await _run(LiveProvider(runtime, cfg, characters, http), request, runtime, cfg)
