from __future__ import annotations

import json

from contracts.models import AudioBundle, DialogueScript, Runtime

from . import audio
from .config import SAMPLE_RATE, SAMPLES_PER_FRAME


def validate_bundle(bundle: AudioBundle, script: DialogueScript, runtime: Runtime, budget: int = 1599) -> list[str]:
    """Independent acceptance checks against the files actually on disk. Returns a list of problems."""
    problems: list[str] = []
    if bundle.script_revision != script.script_revision:
        problems.append("script_revision mismatch")
    if [u.dialogue_id for u in bundle.utterances] != [t.dialogue_id for t in script.turns]:
        problems.append("utterances do not match script turn order")
    if bundle.total_speech_frames != sum(u.frame_count for u in bundle.utterances):
        problems.append("total_speech_frames != clip sum")
    if bundle.total_speech_frames > budget:
        problems.append(f"total_speech_frames {bundle.total_speech_frames} > budget {budget}")
    for u, turn in zip(bundle.utterances, script.turns):
        tag = u.dialogue_id
        if u.speaker_id != turn.speaker_id or u.transcript != turn.text:
            problems.append(f"{tag}: speaker/transcript differs from script")
        for ref in (u.wav, u.transcript_file, u.words_file, u.srt_file):
            path = runtime.path(ref.key)
            if not path.is_file():
                problems.append(f"{tag}: missing {ref.key}")
            elif audio.sha256_hex(path.read_bytes()) != ref.sha256 or path.stat().st_size != ref.size_bytes:
                problems.append(f"{tag}: hash/size mismatch for {ref.key}")
        if not u.wav.key.endswith(".wav") or u.wav.media_type != "audio/wav":
            problems.append(f"{tag}: wav key/media type")
        try:
            data = runtime.path(u.wav.key).read_bytes()
            rate, channels, samples = audio.inspect_wav(data)
        except Exception as exc:
            problems.append(f"{tag}: undecodable WAV ({exc})")
            continue
        if (rate, channels) != (SAMPLE_RATE, 1):
            problems.append(f"{tag}: WAV is {rate} Hz/{channels} ch, expected 48000 Hz mono PCM16")
        if samples != u.sample_count or samples != u.frame_count * SAMPLES_PER_FRAME:
            problems.append(f"{tag}: sample_count {samples} != frame_count*1600")
        if u.duration_ms != round(samples * 1000 / SAMPLE_RATE):
            problems.append(f"{tag}: duration_ms not derived from measured samples")
        doc = json.loads(runtime.path(u.words_file.key).read_text(encoding="utf-8"))
        if doc["audio_sha256"] != u.wav.sha256:
            problems.append(f"{tag}: words.json audio_sha256 does not match WAV")
        if [w["word_id"] for w in doc["words"]] != [w.word_id for w in u.words]:
            problems.append(f"{tag}: words.json differs from bundle words")
        prev_end, seen = 0, set()
        for i, w in enumerate(u.words, 1):
            if w.word_id != f"{tag}_w{i:03d}" or w.word_id in seen:
                problems.append(f"{tag}: unexpected word id {w.word_id}")
            seen.add(w.word_id)
            if not (prev_end <= w.start_ms < w.end_ms <= u.duration_ms):
                problems.append(f"{tag}: {w.word_id} timing {w.start_ms}-{w.end_ms} not ordered/in clip")
            prev_end = w.end_ms
    return problems
