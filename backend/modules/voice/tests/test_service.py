import asyncio
import dataclasses

import pytest

from backend.modules.voice.config import VoiceSettings
from backend.modules.voice.demo import load_inputs
from backend.modules.voice.fake_runtime import FakeRuntime
from backend.modules.voice.service import synthesize_dialogue
from backend.modules.voice.validate import validate_bundle
from contracts.models import StageFailure, VoiceRequest

from .helpers import FakeAligner, FakeChatterbox, install_services, live_request, live_runtime


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- mock mode


def mock_bundle(tmp_path):
    script, chars = load_inputs(live=False)
    runtime = FakeRuntime(tmp_path, mock_mode=True)
    req = VoiceRequest(project_id=script.project_id, script=script, characters=chars)
    return run(synthesize_dialogue(req, runtime)), script, runtime


def test_mock_bundle_matches_fixture_recipe(tmp_path):
    bundle, script, runtime = mock_bundle(tmp_path)
    assert len(bundle.utterances) == 12
    assert {u.frame_count for u in bundle.utterances} == {120}
    assert {u.duration_ms for u in bundle.utterances} == {4000}
    assert {u.sample_count for u in bundle.utterances} == {192000}
    assert bundle.total_speech_frames == 1440
    assert {u.timing_quality for u in bundle.utterances} == {"mock"}
    assert [u.speaker_id for u in bundle.utterances] == ["sundar", "jensen"] * 6
    assert validate_bundle(bundle, script, runtime) == []


def test_mock_is_deterministic(tmp_path):
    a, *_ = mock_bundle(tmp_path / "a")
    b, *_ = mock_bundle(tmp_path / "b")
    assert [u.wav.sha256 for u in a.utterances] == [u.wav.sha256 for u in b.utterances]
    assert [u.words for u in a.utterances] == [u.words for u in b.utterances]


def test_mock_artifact_layout(tmp_path):
    bundle, script, runtime = mock_bundle(tmp_path)
    base = "projects/demo-whatsapp-001/voice/v1"
    u = bundle.utterances[0]
    assert u.wav.key == f"{base}/d001/audio.wav"
    assert u.transcript_file.key == f"{base}/d001/transcript.txt"
    assert u.words_file.key == f"{base}/d001/words.json"
    assert u.srt_file.key == f"{base}/d001/subtitles.srt"
    assert runtime.path(f"{base}/bundle.json").is_file()
    assert runtime.path(u.transcript_file.key).read_text(encoding="utf-8") == script.turns[0].text + "\n"


def test_request_validation_rejects_missing_character(tmp_path):
    script, chars = load_inputs(live=False)
    runtime = FakeRuntime(tmp_path, mock_mode=True)
    req = VoiceRequest(project_id=script.project_id, script=script, characters=[chars[0], chars[0]])
    with pytest.raises(StageFailure) as exc:
        run(synthesize_dialogue(req, runtime))
    assert exc.value.error.code == "VOICE_REQUEST_INVALID"


# ---------------------------------------------------------------- live mode via real service apps


def test_live_flow_end_to_end(tmp_path, monkeypatch):
    chatterbox, aligner = FakeChatterbox(0.3), FakeAligner()
    install_services(monkeypatch, chatterbox, aligner)
    runtime = live_runtime(tmp_path)

    async def go():
        req, script = await live_request(runtime)
        return await synthesize_dialogue(req, runtime), script

    bundle, script = run(go())
    assert validate_bundle(bundle, script, runtime) == []
    assert {u.timing_quality for u in bundle.utterances} == {"forced_alignment"}
    assert bundle.total_speech_frames <= 1599
    assert len(chatterbox.calls) == 12
    # each speaker is conditioned on its own reference WAV
    refs = {text_ref[1] for text_ref in chatterbox.calls}
    assert len(refs) == 2
    # words carry the intended script text and fit inside the padded clip
    first = bundle.utterances[0]
    assert [w.text for w in first.words] == script.turns[0].text.split()
    assert first.words[0].start_ms >= 40 and first.words[-1].end_ms <= first.duration_ms
    assert first.sample_count == first.frame_count * 1600 and first.duration_ms == round(first.sample_count / 48)


def test_speedup_applied_only_when_needed_and_uniformly(tmp_path, monkeypatch):
    from backend.modules.voice import service

    chosen = []
    original = service._choose_speed

    def spy(clips, budget):
        speed = original(clips, budget)
        chosen.append((service._total_frames(clips, 1.0), speed))
        return speed

    monkeypatch.setattr(service, "_choose_speed", spy)
    install_services(monkeypatch, FakeChatterbox(0.435), FakeAligner())
    runtime = live_runtime(tmp_path)

    async def go():
        req, script = await live_request(runtime)
        return await synthesize_dialogue(req, runtime), script

    bundle, script = run(go())
    (raw_frames, speed), = chosen
    assert raw_frames > 1599 and 1.0 < speed <= 1.08
    assert 1500 < bundle.total_speech_frames <= 1599
    assert validate_bundle(bundle, script, runtime) == []

    # word timings were measured on the sped-up WAV: they still end inside each padded clip
    assert all(u.words[-1].end_ms <= u.duration_ms for u in bundle.utterances)


def test_duration_out_of_range_reports_measured_and_budget(tmp_path, monkeypatch):
    chatterbox = FakeChatterbox(0.5)
    install_services(monkeypatch, chatterbox, FakeAligner())
    runtime = live_runtime(tmp_path)

    async def go():
        req, _ = await live_request(runtime)
        return await synthesize_dialogue(req, runtime)

    with pytest.raises(StageFailure) as exc:
        run(go())
    err = exc.value.error
    assert err.code == "AUDIO_DURATION_OUT_OF_RANGE" and err.stage == "voice"
    assert "budget_frames=1599" in err.message and "measured_frames=" in err.message
    assert len(chatterbox.calls) == 12  # failed before spending GPU time on alignment


def test_incomplete_alignment_triggers_one_resynthesis(tmp_path, monkeypatch):
    chatterbox, aligner = FakeChatterbox(0.3), FakeAligner(drop_last_word_calls=1)
    install_services(monkeypatch, chatterbox, aligner)
    runtime = live_runtime(tmp_path)

    async def go():
        req, script = await live_request(runtime)
        return await synthesize_dialogue(req, runtime), script

    bundle, script = run(go())
    assert validate_bundle(bundle, script, runtime) == []
    assert len(chatterbox.calls) == 13
    assert chatterbox.calls[0][2] == 100 and chatterbox.calls[12][2] == 101  # d001 retried with a new seed


def test_persistent_incomplete_alignment_fails_with_recoverable_error(tmp_path, monkeypatch):
    install_services(monkeypatch, FakeChatterbox(0.3), FakeAligner(drop_last_word_calls=99))
    runtime = live_runtime(tmp_path)

    async def go():
        req, _ = await live_request(runtime)
        return await synthesize_dialogue(req, runtime)

    with pytest.raises(StageFailure) as exc:
        run(go())
    assert exc.value.error.code == "ALIGNMENT_INCOMPLETE" and exc.value.error.retryable
    assert not runtime.path("projects/demo-whatsapp-001/voice/v1/bundle.json").exists()


def test_low_alignment_confidence_is_rejected(tmp_path, monkeypatch):
    install_services(monkeypatch, FakeChatterbox(0.3), FakeAligner(mean_score=0.05))
    runtime = live_runtime(tmp_path)

    async def go():
        req, _ = await live_request(runtime)
        return await synthesize_dialogue(req, runtime)

    with pytest.raises(StageFailure) as exc:
        run(go())
    assert exc.value.error.code == "ALIGNMENT_LOW_CONFIDENCE"


def test_silent_synthesis_is_retried(tmp_path, monkeypatch):
    chatterbox = FakeChatterbox(0.3, silent_attempts=1)
    install_services(monkeypatch, chatterbox, FakeAligner())
    runtime = live_runtime(tmp_path)

    async def go():
        req, script = await live_request(runtime)
        return await synthesize_dialogue(req, runtime), script

    bundle, script = run(go())
    assert len(chatterbox.calls) == 13 and validate_bundle(bundle, script, runtime) == []


def test_wrong_bearer_key_is_not_retried_and_not_retryable(tmp_path, monkeypatch):
    install_services(monkeypatch, FakeChatterbox(), FakeAligner(), voice_key="server-secret")
    runtime = live_runtime(tmp_path, voice_key="wrong")

    async def go():
        req, _ = await live_request(runtime)
        return await synthesize_dialogue(req, runtime)

    with pytest.raises(StageFailure) as exc:
        run(go())
    assert exc.value.error.code == "VOICE_AUTH_FAILED" and not exc.value.error.retryable


def test_missing_voice_reference_is_a_clear_error(tmp_path, monkeypatch):
    install_services(monkeypatch, FakeChatterbox(), FakeAligner())
    runtime = live_runtime(tmp_path)

    async def go():
        req, _ = await live_request(runtime, with_references=False)
        return await synthesize_dialogue(req, runtime)

    with pytest.raises(StageFailure) as exc:
        run(go())
    assert exc.value.error.code == "VOICE_REFERENCE_MISSING"


def test_service_unreachable_is_retryable_stage_error(tmp_path, monkeypatch):
    runtime = live_runtime(tmp_path)
    runtime.settings.update(VOICE_API_URL="http://127.0.0.1:9/v1/tts")
    original = VoiceSettings.from_mapping
    monkeypatch.setattr(
        VoiceSettings, "from_mapping", staticmethod(lambda s: dataclasses.replace(original(s), max_attempts=1))
    )

    async def go():
        req, _ = await live_request(runtime)
        return await synthesize_dialogue(req, runtime)

    with pytest.raises(StageFailure) as exc:
        run(go())
    assert exc.value.error.code == "VOICE_UNAVAILABLE" and exc.value.error.retryable


@pytest.mark.parametrize("mock", [True, False])
def test_punctuation_only_turn_is_a_clean_request_error(tmp_path, mock):
    script, chars = load_inputs(live=False)
    script.turns[2].text = "— ..."
    runtime = FakeRuntime(tmp_path, mock_mode=mock)
    req = VoiceRequest(project_id=script.project_id, script=script, characters=chars)
    with pytest.raises(StageFailure) as exc:
        run(synthesize_dialogue(req, runtime))
    assert exc.value.error.code == "VOICE_REQUEST_INVALID"


def test_over_budget_after_resynthesis_reports_actual_speed(tmp_path, monkeypatch):
    # first pass fits at 1.0x; the retried clip is much longer, pushing the total over budget
    class GrowingChatterbox(FakeChatterbox):
        def synthesize(self, text, ref_path, ref_sha, seed):
            self.spw = 0.4 if len(self.calls) < 12 else 1.4
            return super().synthesize(text, ref_path, ref_sha, seed)

    install_services(monkeypatch, GrowingChatterbox(0.4), FakeAligner(drop_last_word_calls=1))
    runtime = live_runtime(tmp_path)

    async def go():
        req, _ = await live_request(runtime)
        return await synthesize_dialogue(req, runtime)

    with pytest.raises(StageFailure) as exc:
        run(go())
    assert exc.value.error.code == "AUDIO_DURATION_OUT_OF_RANGE"
    assert "at 1.0x speed" in exc.value.error.message
