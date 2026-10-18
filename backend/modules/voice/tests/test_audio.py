import struct

import numpy as np
import pytest

from backend.modules.voice import audio
from backend.modules.voice.config import SAMPLE_RATE, SAMPLES_PER_FRAME
from contracts.models import StageFailure


def tone(freq, seconds, rate=SAMPLE_RATE, amp=0.5):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def dominant_hz(x, rate=SAMPLE_RATE):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.argmax(spec) * rate / len(x)


def float_wav(samples, rate):
    data = samples.astype("<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_pcm16_roundtrip_and_inspect():
    x = tone(440, 0.5)
    data = audio.encode_wav_pcm16(x)
    y, rate = audio.decode_wav(data)
    assert rate == SAMPLE_RATE and len(y) == len(x)
    assert np.max(np.abs(x - y)) < 1e-3
    assert audio.inspect_wav(data) == (SAMPLE_RATE, 1, len(x))


def test_decode_float32_wav():
    x = tone(300, 0.25, 24000)
    y, rate = audio.decode_wav(float_wav(x, 24000))
    assert rate == 24000 and np.allclose(x, y)


def test_decode_garbage_raises_stage_failure():
    with pytest.raises(StageFailure) as exc:
        audio.decode_wav(b"not a wav")
    assert exc.value.error.code == "VOICE_AUDIO_INVALID"


def test_resample_24k_to_48k_keeps_length_and_pitch():
    x = tone(500, 2.0, 24000)
    y = audio.resample(x, 24000)
    assert len(y) == 96000
    assert abs(dominant_hz(y) - 500) < 2
    assert np.max(np.abs(y)) < 0.55


def test_resample_44k1_to_48k():
    y = audio.resample(tone(700, 1.0, 44100), 44100)
    assert len(y) == 48000 and abs(dominant_hz(y) - 700) < 2


def test_trim_keeps_speech_and_margins():
    speech = tone(300, 1.0)
    x = np.concatenate([np.zeros(SAMPLE_RATE), speech, np.zeros(SAMPLE_RATE)])
    y = audio.trim_silence(x)
    assert len(speech) < len(y) < len(speech) + SAMPLE_RATE * 0.25
    assert np.max(np.abs(y[: SAMPLE_RATE // 40])) < 1e-6  # lead margin is still silent


def test_silent_audio_rejected():
    with pytest.raises(StageFailure) as exc:
        audio.trim_silence(np.zeros(1000, dtype=np.float32))
    assert exc.value.error.code == "VOICE_SILENT_AUDIO"


def test_normalize_level_hits_ceiling_and_fades():
    y = audio.normalize_level(tone(300, 1.0, amp=0.01))
    assert np.max(np.abs(y)) <= audio.PEAK_CEILING + 1e-6
    assert abs(y[0]) < 1e-3 and abs(y[-1]) < 1e-3


@pytest.mark.parametrize("speed", [1.03, 1.08])
def test_time_stretch_length_and_pitch(speed):
    x = tone(220, 2.0)
    y = audio.time_stretch(x, speed)
    assert len(y) == audio.stretched_length(len(x), speed)
    assert abs(len(y) - len(x) / speed) < 1
    mid = y[SAMPLE_RATE // 4 : -SAMPLE_RATE // 4]
    assert abs(dominant_hz(mid) - 220) < 6
    assert np.max(np.abs(mid)) > 0.4


def test_time_stretch_identity():
    x = tone(220, 0.2)
    assert audio.time_stretch(x, 1.0) is x


def test_pad_to_frames_only_appends_silence():
    x = tone(300, 0.5)
    padded, frames = audio.pad_to_frames(x)
    assert len(padded) == frames * SAMPLES_PER_FRAME and frames == 15
    assert np.array_equal(padded[: len(x)], x) and not padded[len(x) :].any()
    exact, f2 = audio.pad_to_frames(np.ones(3 * SAMPLES_PER_FRAME, dtype=np.float32))
    assert f2 == 3 and len(exact) == 3 * SAMPLES_PER_FRAME
