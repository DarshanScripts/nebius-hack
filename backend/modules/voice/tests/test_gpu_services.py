import asyncio
import hashlib
import io
import wave

import httpx
import numpy as np

from .helpers import FakeAligner, FakeChatterbox, load_service


def req(app, method, url, **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc") as c:
            return await c.request(method, url, **kw)

    return asyncio.run(go())


def ref_wav():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
        w.writeframes(np.zeros(24000, dtype="<i2").tobytes())
    return buf.getvalue()


def tts_app(tmp_path, engine=None, key="k"):
    return load_service("chatterbox").create_app(engine or FakeChatterbox(), api_key=key, ref_cache=tmp_path / "refs")


def test_chatterbox_health_has_no_credentials(tmp_path):
    r = req(tts_app(tmp_path, key="super-secret"), "GET", "/health")
    assert r.status_code == 200 and r.json()["model_loaded"] is True
    assert "super-secret" not in r.text


def test_chatterbox_requires_bearer(tmp_path):
    files = {"reference_audio": ("r.wav", ref_wav(), "audio/wav")}
    data = {"text": "hello world", "dialogue_id": "d001", "model": "chatterbox-turbo"}
    app = tts_app(tmp_path)
    assert req(app, "POST", "/v1/tts", data=data, files=files).status_code == 401
    assert req(app, "POST", "/v1/tts", data=data, files=files, headers={"Authorization": "Bearer x"}).status_code == 401
    r = req(tts_app(tmp_path, key=""), "POST", "/v1/tts", data=data, files=files, headers={"Authorization": "Bearer "})
    assert r.status_code == 503


def test_chatterbox_returns_native_rate_wav_and_caches_reference(tmp_path):
    engine = FakeChatterbox(0.2)
    app = tts_app(tmp_path, engine)
    ref = ref_wav()
    files = {"reference_audio": ("r.wav", ref, "audio/wav")}
    data = {"text": "hello  there world", "dialogue_id": "d001", "model": "chatterbox-turbo", "seed": "7"}
    r = req(app, "POST", "/v1/tts", data=data, files=files, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(r.content)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    assert engine.calls == [("hello there world", hashlib.sha256(ref).hexdigest(), 7)]
    assert (tmp_path / "refs" / f"{hashlib.sha256(ref).hexdigest()}.wav").read_bytes() == ref


def test_chatterbox_validation(tmp_path):
    app, h = tts_app(tmp_path), {"Authorization": "Bearer k"}
    files = {"reference_audio": ("r.wav", ref_wav(), "audio/wav")}
    base = {"text": "hi", "dialogue_id": "d001", "model": "chatterbox-turbo"}
    assert req(app, "POST", "/v1/tts", data={**base, "model": "other"}, files=files, headers=h).status_code == 422
    assert req(app, "POST", "/v1/tts", data={**base, "text": "  "}, files=files, headers=h).status_code == 422
    assert req(app, "POST", "/v1/tts", data={**base, "dialogue_id": "../x"}, files=files, headers=h).status_code == 422
    assert req(app, "POST", "/v1/tts", data={**base, "text": "x" * 900}, files=files, headers=h).status_code == 422


def test_whisperx_align_response_matches_contract(tmp_path):
    app = load_service("whisperx").create_app(FakeAligner(), api_key="k")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(48000)
        t = np.arange(48000) / 48000
        w.writeframes((np.sin(2 * np.pi * 200 * t) * 9000).astype("<i2").tobytes())
    wav = buf.getvalue()
    r = req(
        app, "POST", "/v1/align", headers={"Authorization": "Bearer k"},
        data={"dialogue_id": "d001", "transcript": "How  does calling work?", "language": "en"},
        files={"audio": ("a.wav", wav, "audio/wav")},
    )
    assert r.status_code == 200
    body = r.json()
    from contracts.models import AlignmentResult

    result = AlignmentResult.model_validate({k: body[k] for k in AlignmentResult.model_fields})
    assert result.audio_sha256 == hashlib.sha256(wav).hexdigest()
    assert result.transcript == "How does calling work?"
    assert [w.word_id for w in result.words] == [f"d001_w00{i}" for i in range(1, 5)]
    assert all(w.end_ms >= w.start_ms for w in result.words)
    assert body["quality"]["mean_score"] == 0.8


def test_whisperx_auth_and_language(tmp_path):
    app = load_service("whisperx").create_app(FakeAligner(), api_key="k")
    kw = dict(data={"dialogue_id": "d001", "transcript": "hi", "language": "en"}, files={"audio": ("a.wav", b"x", "audio/wav")})
    assert req(app, "POST", "/v1/align", **kw).status_code == 401
    kw["data"]["language"] = "fr"
    assert req(app, "POST", "/v1/align", headers={"Authorization": "Bearer k"}, **kw).status_code == 422


def test_build_response_omits_untimed_words_and_converts_ms():
    mod = load_service("whisperx")
    body = mod.build_response(
        "d009", "abc", "a b c",
        [{"word": "a", "start": 0.0804, "end": 0.2406, "score": 0.9}, {"word": "b"}, {"word": "c", "start": 0.3, "end": 0.5}],
    )
    assert [(w["word_id"], w["start_ms"], w["end_ms"]) for w in body["words"]] == [("d009_w001", 80, 241), ("d009_w002", 300, 500)]
    assert body["quality"]["words_aligned"] == 2 and body["quality"]["words_in_transcript"] == 3


def test_asr_similarity():
    mod = load_service("whisperx")
    assert mod.text_similarity("How does calling work?", "how does calling work") == 1.0
    assert mod.text_similarity("How does calling work", "completely different sentence here") < 0.3


def test_chatterbox_concurrent_same_reference_does_not_race(tmp_path):
    app = tts_app(tmp_path, FakeChatterbox(0.1))
    ref = ref_wav()
    data = {"text": "hello world", "dialogue_id": "d001", "model": "chatterbox-turbo"}

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc") as c:
            return await asyncio.gather(
                *[
                    c.post("/v1/tts", data=data, files={"reference_audio": ("r.wav", ref, "audio/wav")},
                           headers={"Authorization": "Bearer k"})
                    for _ in range(6)
                ]
            )

    assert [r.status_code for r in asyncio.run(go())] == [200] * 6
