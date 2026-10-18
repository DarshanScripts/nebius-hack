"""Explicit platform-only fixtures for the coordinator demo and regression checks.

These are injection helpers, never a fallback for missing live/team modules.
They do not implement any scene renderer or emit imitation MP4s.
"""
import io
import wave

from contracts.models import (
    AlignmentResult, AudioBundle, Claim, DialogueScript, DialogueTurn, ImageBundle,
    ImageQuery, ImageSelection, ResearchBundle, Source, UtteranceAudio, WordTiming,
)

LINES = [
    "What happens when I tap call?",
    "Our mock diagram begins with call setup signaling.",
    "Does signaling carry the entire conversation?",
    "This mock distinguishes setup messages from audio packets.",
    "Can those packets always travel directly?",
    "Our example draws a relay when direct connectivity fails.",
    "What if some audio packets disappear?",
    "The mock board illustrates a buffer smoothing packet arrival.",
    "Are these verified WhatsApp implementation details?",
    "No. These are explicit demonstration fixtures for our pipeline.",
    "What will ground the real explanation?",
    "Live research supplies cited claims and preserves technical uncertainty.",
]


async def research_fixture(request, runtime):
    raw = await runtime.write_json(f"projects/{request.project_id}/research/mock/raw.json",
                                   {"is_mock": True, "topic": request.topic})
    return ResearchBundle(project_id=request.project_id, topic=request.topic, tavily_request_id="mock-request",
        summary="Mock demonstration data, not verified research.",
        report_markdown="# Mock research\nDemonstration data only.", raw_response=raw, is_mock=True,
        sources=[Source(source_id=f"src{i:03}", title=f"Mock source {i}",
                        url=f"https://example.com/mock-source-{i}") for i in (1, 2)],
        claims=[Claim(claim_id=f"c{i:03}", text=f"Mock demonstration claim {i}",
                      source_ids=["src001"], evidence_type="general_industry_practice") for i in range(1, 7)])


async def script_fixture(request, runtime):
    return DialogueScript(project_id=request.project_id, script_revision=request.script_revision,
        title="Mock calling infrastructure", turns=[DialogueTurn(
            dialogue_id=f"d{i:03}", order=i, scene_index=(i-1)//2+1,
            speaker_id="sundar" if i % 2 else "jensen", text=line,
            intent="question" if i % 2 else "answer",
            claim_ids=[] if i % 2 else [f"c{i//2:03}"])
            for i, line in enumerate(LINES, 1)])


async def images_fixture(request, runtime):
    return ImageBundle(project_id=request.project_id, script_revision=request.script.script_revision,
        selections=[ImageSelection(query=ImageQuery(scene_index=i, dialogue_ids=[f"d{2*i-1:03}", f"d{2*i:03}"],
            query="mock calling infrastructure diagram", reason="Fixture only"),
            status="unavailable", reason="Platform fixture; vector fallback exercised") for i in range(1, 7)])


async def audio_fixture(request, runtime):
    utterances = []
    for turn in request.script.turns:
        base = f"projects/{request.project_id}/voice/v{request.script.script_revision}/{turn.dialogue_id}"
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(b"\x00\x00" * 192000)
        wav = await runtime.write_bytes(f"{base}/audio.wav", buffer.getvalue(), "audio/wav")
        tokens = turn.text.split()
        words = [WordTiming(word_id=f"{turn.dialogue_id}_w{i+1:03}", text=token,
                 start_ms=100+i*3500//len(tokens), end_ms=100+(i+1)*3500//len(tokens)-10)
                 for i, token in enumerate(tokens)]
        transcript = await runtime.write_bytes(f"{base}/transcript.txt", turn.text.encode(), "text/plain")
        aligned = await runtime.write_json(f"{base}/words.json", AlignmentResult(dialogue_id=turn.dialogue_id,
            audio_sha256=wav.sha256, transcript=turn.text, words=words))
        srt = await runtime.write_bytes(f"{base}/subtitles.srt",
            f"1\n00:00:00,100 --> 00:00:03,600\n{turn.text}\n".encode(), "application/x-subrip")
        utterances.append(UtteranceAudio(dialogue_id=turn.dialogue_id, speaker_id=turn.speaker_id,
            wav=wav, transcript=turn.text, transcript_file=transcript, words_file=aligned, srt_file=srt,
            duration_ms=4000, frame_count=120, sample_count=192000, words=words, timing_quality="mock"))
    return AudioBundle(project_id=request.project_id, script_revision=request.script.script_revision,
                       utterances=utterances, total_speech_frames=1440)


SERVICES = {"run_research": research_fixture, "generate_dialogue": script_fixture,
            "find_images": images_fixture, "synthesize_dialogue": audio_fixture}
