"""Deterministic fixture SceneContext from the plan.md section 12 recipe.

Every artifact referenced is a real file written through the runtime, so
hashes and byte sizes are real. All content is explicitly MOCK data.
"""
from __future__ import annotations

import array
import hashlib
import io
import json
import math
import struct
import wave
import zlib
from typing import Any

from contracts.models import (
    AudioBundle,
    CharacterSpec,
    Claim,
    DialogueScript,
    DialogueTurn,
    ImageBundle,
    ImageQuery,
    ImageSelection,
    ResearchBundle,
    SceneContext,
    SceneSlot,
    Source,
    TimedUtterance,
    Timeline,
    UtteranceAudio,
    WordTiming,
)

PROJECT_ID = "demo-whatsapp-001"
FRAMES_PER_CLIP = 120  # 192000 samples = 4000 ms
SAMPLES_PER_FRAME = 1600
SAMPLE_RATE = 48000
EXPECTED_BOUNDARIES = [0, 273, 543, 813, 1083, 1353, 1800]

LINES: list[tuple[str, str, list[str]]] = [
    ("hook", "Jensen, when I tap call on WhatsApp, what actually happens?", []),
    ("answer", "First, your phone signals WhatsApp servers to find and ring the other device.", ["c001"]),
    ("question", "So the servers carry my voice too?", []),
    ("answer", "Not always. Media can flow peer to peer, or through a relay when networks block that.", ["c002"]),
    ("challenge", "Relays sound slow. Why not always go direct?", []),
    ("answer", "Firewalls and NAT often prevent direct paths, so relays keep calls connecting.", ["c003"]),
    ("question", "And who can listen in along the way?", []),
    ("answer", "Calls are end to end encrypted, so relays forward packets they cannot read.", ["c004"]),
    ("question", "What happens when my signal gets weak?", []),
    ("answer", "The app adapts bitrate and smooths jitter, trading some quality to stay live.", ["c005"]),
    ("question", "So what is the big picture?", []),
    ("takeaway", "Signaling sets up the call, media takes the best path, and encryption protects it end to end.", ["c006"]),
]

CLAIMS = [
    ("c001", "MOCK fixture claim: call setup starts with a signaling exchange through the service's servers.", "documented"),
    ("c002", "MOCK fixture claim: call media may travel directly between devices or via a relay.", "general_industry_practice"),
    ("c003", "MOCK fixture claim: NAT and firewalls commonly block direct peer-to-peer media.", "general_industry_practice"),
    ("c004", "MOCK fixture claim: calls are described as end-to-end encrypted.", "documented"),
    ("c005", "MOCK fixture claim: real-time voice apps typically adapt bitrate and buffer jitter.", "inference"),
    ("c006", "MOCK fixture claim: signaling, media routing and encryption are separate layers.", "inference"),
]


def canonical_hash(value: Any) -> str:
    """plan.md section 9: sorted keys, compact separators, UTF-8."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def compute_context_hash(ctx: SceneContext) -> str:
    payload = ctx.model_dump(mode="json")
    payload.pop("context_hash", None)
    return canonical_hash(payload)


# ---------------------------------------------------------------- media
def _wav(words: list[WordTiming], speaker: str) -> bytes:
    n = FRAMES_PER_CLIP * SAMPLES_PER_FRAME
    base = 220.0 if speaker == "sundar" else 165.0
    samples = array.array("h", bytes(2 * n))
    for w in words:
        a, b = w.start_ms * SAMPLE_RATE // 1000, w.end_ms * SAMPLE_RATE // 1000
        for i in range(a, b):
            env = 0.25 * math.sin(math.pi * (i - a) / (b - a))
            samples[i] = int(env * 32767 * math.sin(2 * math.pi * base * i / SAMPLE_RATE))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def _encode_png(width: int, height: int, px, channels: int) -> bytes:
    raw = b"".join(b"\x00" + b"".join(bytes(px(x, y)) for x in range(width)) for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    color_type = 6 if channels == 4 else 2
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _png(width: int, height: int) -> bytes:
    """A simple MOCK diagram image (two phones and a relay), pure stdlib."""
    def px(x: int, y: int) -> tuple[int, int, int]:
        for cx in (90, width - 90):  # phones
            if abs(x - cx) < 40 and abs(y - height // 2) < 75:
                return (17, 24, 39) if (abs(x - cx) > 32 or abs(y - height // 2) > 67) else (226, 232, 240)
        if abs(x - width // 2) < 45 and abs(y - 70) < 40:  # relay
            return (234, 88, 12)
        if abs(y - height // 2) < 4 and 130 < x < width - 130:  # direct path
            return (22, 163, 74)
        return (255, 255, 255)

    return _encode_png(width, height, px, 3)


def _character_png(rgb: tuple[int, int, int], width: int = 210, height: int = 288) -> bytes:
    """MOCK transparent character cut-out (RGBA): head + shoulders, the rest fully transparent."""
    def px(x: int, y: int) -> tuple[int, int, int, int]:
        head = (x - width / 2) ** 2 + (y - height * 0.3) ** 2 < (width * 0.22) ** 2
        body = y > height * 0.55 and abs(x - width / 2) < width * 0.42 * min(1.0, (y - height * 0.5) / (height * 0.2))
        return (*rgb, 255) if head or body else (0, 0, 0, 0)

    return _encode_png(width, height, px, 4)


def _mock_words(dialogue_id: str, text: str) -> list[WordTiming]:
    tokens = text.split()
    start, end = 200, 3700
    step = (end - start) / len(tokens)
    return [
        WordTiming(word_id=f"{dialogue_id}_w{i + 1:03d}", text=tok, start_ms=int(start + i * step), end_ms=int(start + (i + 0.85) * step))
        for i, tok in enumerate(tokens)
    ]


def _srt(words: list[WordTiming]) -> str:
    def ts(ms: int) -> str:
        return f"00:00:{ms // 1000:02d},{ms % 1000:03d}"
    return f"1\n{ts(words[0].start_ms)} --> {ts(words[-1].end_ms)}\n{' '.join(w.text for w in words)}\n"


# ---------------------------------------------------------------- timeline
def build_timeline(project_id: str, script_revision: int, frame_counts: list[int]) -> Timeline:
    """Section 7 allocation (member 1 owns the canonical one; this mirrors it for fixtures)."""
    utts: list[TimedUtterance] = []
    cursor = 15
    for i, fc in enumerate(frame_counts):
        utts.append(TimedUtterance(dialogue_id=f"d{i + 1:03d}", start_frame=cursor, end_frame=cursor + fc))
        cursor += fc + (6 if i % 2 == 0 else 24)
    bounds = [0] + [utts[2 * g + 1].end_frame + 12 for g in range(5)] + [1800]
    scenes = [
        SceneSlot(scene_id=f"s{g + 1:02d}", index=g + 1, start_frame=bounds[g], end_frame=bounds[g + 1], dialogue_ids=[f"d{2 * g + 1:03d}", f"d{2 * g + 2:03d}"])
        for g in range(6)
    ]
    return Timeline(project_id=project_id, script_revision=script_revision, utterances=utts, scenes=scenes)


async def build_fixture_context(runtime: Any, project_id: str = PROJECT_ID, *, character_pngs: bool = False) -> SceneContext:
    """character_pngs=True adds MOCK transparent character PNGs (exercises the shell's image path)."""
    base = f"projects/{project_id}"
    raw = await runtime.write_json(f"{base}/research/raw.json", {"mock": True, "note": "MOCK research fixture; not a Tavily response"})
    research = ResearchBundle(
        project_id=project_id,
        topic="How does WhatsApp voice calling infrastructure work?",
        tavily_request_id="mock-request-001",
        summary="MOCK summary for fixture development. Not a completed real research result.",
        report_markdown="# MOCK research report\n\nDemonstration data only.",
        sources=[
            Source(source_id="src001", title="Mock source one", url="https://example.com/mock-source-1"),
            Source(source_id="src002", title="Mock source two", url="https://example.com/mock-source-2"),
        ],
        claims=[
            Claim(claim_id=cid, text=text, source_ids=["src001" if i % 2 == 0 else "src002"], evidence_type=ev, caveat="Fixture inference; not verified." if ev == "inference" else None)
            for i, (cid, text, ev) in enumerate(CLAIMS)
        ],
        uncertainties=["MOCK: exact topology and codecs are not documented in this fixture."],
        raw_response=raw,
        is_mock=True,
    )
    turns = [
        DialogueTurn(dialogue_id=f"d{i + 1:03d}", order=i + 1, scene_index=i // 2 + 1, speaker_id="sundar" if i % 2 == 0 else "jensen", text=text, intent=intent, claim_ids=claims)
        for i, (intent, text, claims) in enumerate(LINES)
    ]
    script = DialogueScript(project_id=project_id, script_revision=1, title="How WhatsApp calls work (mock)", turns=turns)
    await runtime.write_json(f"{base}/script/v1/script.json", script)

    png = await runtime.write_bytes(f"{base}/images/v1/s03-mock-diagram.png", _png(480, 300), "image/png")
    selections = []
    for g in range(6):
        q = ImageQuery(scene_index=g + 1, dialogue_ids=[f"d{2 * g + 1:03d}", f"d{2 * g + 2:03d}"], query=f"mock query for scene {g + 1}", reason="MOCK fixture query")
        if g == 2:
            selections.append(ImageSelection(query=q, status="selected", asset=png, image_url="https://example.com/mock-image.png", description="MOCK generated diagram: direct path vs relay"))
        else:
            selections.append(ImageSelection(query=q, status="unavailable", reason="MOCK: no image selected for this fixture scene"))
    images = ImageBundle(project_id=project_id, script_revision=1, selections=selections)

    utterances = []
    for t in turns:
        words = _mock_words(t.dialogue_id, t.text)
        vbase = f"{base}/voice/v1/{t.dialogue_id}"
        wav = await runtime.write_bytes(f"{vbase}/audio.wav", _wav(words, t.speaker_id), "audio/wav")
        txt = await runtime.write_bytes(f"{vbase}/transcript.txt", t.text.encode(), "text/plain")
        wj = await runtime.write_json(f"{vbase}/words.json", {"dialogue_id": t.dialogue_id, "audio_sha256": wav.sha256, "transcript": t.text, "words": [w.model_dump() for w in words]})
        srt = await runtime.write_bytes(f"{vbase}/subtitles.srt", _srt(words).encode(), "application/x-subrip")
        utterances.append(UtteranceAudio(
            dialogue_id=t.dialogue_id, speaker_id=t.speaker_id, wav=wav, transcript=t.text, transcript_file=txt, words_file=wj, srt_file=srt,
            duration_ms=4000, frame_count=FRAMES_PER_CLIP, sample_count=FRAMES_PER_CLIP * SAMPLES_PER_FRAME, words=words, timing_quality="mock",
        ))
    audio = AudioBundle(project_id=project_id, script_revision=1, utterances=utterances, total_speech_frames=FRAMES_PER_CLIP * 12)
    await runtime.write_json(f"{base}/voice/v1/bundle.json", audio)

    timeline = build_timeline(project_id, 1, [u.frame_count for u in utterances])
    assert [s.start_frame for s in timeline.scenes] + [1800] == EXPECTED_BOUNDARIES, timeline.scenes
    await runtime.write_json(f"{base}/timeline.json", timeline)

    images_by_id: dict[str, Any] = {"sundar": None, "jensen": None}
    if character_pngs:
        for cid, rgb in (("sundar", (37, 99, 235)), ("jensen", (22, 163, 74))):
            images_by_id[cid] = await runtime.write_bytes(f"{base}/inputs/characters/{cid}-mock.png", _character_png(rgb), "image/png")
    characters = [
        CharacterSpec(character_id="sundar", display_name="Sundar Pichai", image=images_by_id["sundar"]),
        CharacterSpec(character_id="jensen", display_name="Jensen Huang", image=images_by_id["jensen"]),
    ]
    ctx = SceneContext(
        project_id=project_id, research=research, script=script, images=images, audio=audio, timeline=timeline,
        characters=characters, timeline_hash=canonical_hash(timeline.model_dump(mode="json")), context_hash="0" * 64,
    )
    ctx = ctx.model_copy(update={"context_hash": compute_context_hash(ctx)})
    await runtime.write_json(f"{base}/context.json", ctx)
    return ctx
