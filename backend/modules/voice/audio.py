from __future__ import annotations

import hashlib
import io
import math
import struct
import wave

import numpy as np

from .config import SAMPLE_RATE, SAMPLES_PER_FRAME
from .errors import fail

TARGET_RMS_DBFS = -20.0
PEAK_CEILING = 0.891  # -1 dBFS
LEAD_KEEP_MS = 50
TAIL_KEEP_MS = 120
SILENCE_REL_DB = -45.0


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Decode PCM (8/16/24/32-bit) or IEEE-float WAV bytes to mono float32 in [-1, 1]."""
    try:
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")
        pos, fmt, pcm = 12, None, None
        while pos + 8 <= len(data):
            cid, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
            body = data[pos + 8 : pos + 8 + size]
            if cid == b"fmt ":
                fmt = struct.unpack("<HHIIHH", body[:16])
                if fmt[0] == 0xFFFE and len(body) >= 26:
                    fmt = (struct.unpack("<H", body[24:26])[0], *fmt[1:])
            elif cid == b"data":
                pcm = body
                break
            pos += 8 + size + (size & 1)
        if fmt is None or pcm is None:
            raise ValueError("missing fmt or data chunk")
        tag, channels, rate, _, _, bits = fmt
        if tag == 3 and bits in (32, 64):
            x = np.frombuffer(pcm[: len(pcm) // (bits // 8) * (bits // 8)], dtype=f"<f{bits // 8}")
        elif tag == 1 and bits == 8:
            x = (np.frombuffer(pcm, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif tag == 1 and bits == 16:
            x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2") / 32768.0
        elif tag == 1 and bits == 24:
            raw = np.frombuffer(pcm[: len(pcm) // 3 * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            val = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
            x = np.where(val & 0x800000, val - 0x1000000, val) / 8388608.0
        elif tag == 1 and bits == 32:
            x = np.frombuffer(pcm[: len(pcm) // 4 * 4], dtype="<i4") / 2147483648.0
        else:
            raise ValueError(f"unsupported WAV encoding tag={tag} bits={bits}")
        x = np.asarray(x, dtype=np.float32)
        if channels > 1:
            x = x[: len(x) // channels * channels].reshape(-1, channels).mean(axis=1)
        if rate <= 0 or x.size == 0:
            raise ValueError("empty audio")
        return x, int(rate)
    except (ValueError, struct.error) as exc:
        raise fail("VOICE_AUDIO_INVALID", f"Speech service returned undecodable WAV: {exc}", retryable=True) from exc


def encode_wav_pcm16(samples: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def inspect_wav(data: bytes) -> tuple[int, int, int]:
    """Return (sample_rate, channels, sample_count) of a canonical PCM16 WAV."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("not 16-bit PCM")
        return w.getframerate(), w.getnchannels(), w.getnframes()


def resample(x: np.ndarray, rate_in: int, rate_out: int = SAMPLE_RATE) -> np.ndarray:
    """Band-limited FFT resampling with zero padding to avoid wrap-around ringing."""
    if rate_in == rate_out:
        return x.astype(np.float32, copy=False)
    pad = rate_in // 100 if rate_in % 100 == 0 and rate_out % 100 == 0 else 0
    xp = np.concatenate([np.zeros(pad), x.astype(np.float64), np.zeros(pad)])
    n_out = int(round(len(xp) * rate_out / rate_in))
    spec = np.fft.rfft(xp)
    new = np.zeros(n_out // 2 + 1, dtype=np.complex128)
    k = min(len(spec), len(new))
    new[:k] = spec[:k]
    y = np.fft.irfft(new, n_out) * (n_out / len(xp))
    cut = int(round(pad * rate_out / rate_in))
    return y[cut : len(y) - cut].astype(np.float32)


def trim_silence(x: np.ndarray, rate: int = SAMPLE_RATE) -> np.ndarray:
    """Trim leading/trailing silence conservatively, keeping a margin so speech is never clipped."""
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak <= 1e-4:
        raise fail("VOICE_SILENT_AUDIO", "Synthesized audio is silent", retryable=True)
    win = rate // 100
    n = len(x) // win
    rms = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1)) if n else np.array([peak])
    active = np.flatnonzero(rms > peak * 10 ** (SILENCE_REL_DB / 20))
    if active.size == 0:
        return x
    start = max(0, int(active[0]) * win - rate * LEAD_KEEP_MS // 1000)
    end = min(len(x), (int(active[-1]) + 1) * win + rate * TAIL_KEEP_MS // 1000)
    return x[start:end]


def normalize_level(x: np.ndarray) -> np.ndarray:
    """Remove DC, scale active speech to the target RMS without exceeding the peak ceiling, add short fades."""
    x = x.astype(np.float64) - float(np.mean(x))
    peak = float(np.max(np.abs(x)))
    if peak <= 1e-4:
        raise fail("VOICE_SILENT_AUDIO", "Synthesized audio is silent", retryable=True)
    active = x[np.abs(x) > peak * 0.02]
    rms = float(np.sqrt(np.mean(active**2))) if active.size else peak
    gain = min(10 ** (TARGET_RMS_DBFS / 20) / rms, PEAK_CEILING / peak, 10.0)
    x = x * gain
    fade_in, fade_out = min(len(x), SAMPLE_RATE // 200), min(len(x), SAMPLE_RATE // 100)
    x[:fade_in] *= np.linspace(0.0, 1.0, fade_in, endpoint=False)
    x[len(x) - fade_out :] *= np.linspace(1.0, 0.0, fade_out)
    return x.astype(np.float32)


def stretched_length(n: int, speed: float) -> int:
    return n if speed == 1.0 else math.ceil(n / speed)


def time_stretch(x: np.ndarray, speed: float) -> np.ndarray:
    """Pitch-preserving WSOLA speed change. Output length is exactly ceil(len(x) / speed)."""
    if speed == 1.0:
        return x
    win = 1920
    hs = win // 2
    tol = hs // 2
    w = np.hanning(win + 1)[:-1]
    ha = hs * speed
    out_len = stretched_length(len(x), speed)
    n_frames = math.ceil(out_len / hs) + 1
    xp = np.concatenate(
        [np.zeros(tol), x.astype(np.float64), np.zeros(int(n_frames * ha) + win + 3 * tol + hs)]
    )
    out = np.zeros(n_frames * hs + win)
    norm = np.zeros_like(out)
    prev = tol
    out[:win] += w * xp[prev : prev + win]
    norm[:win] += w
    for k in range(1, n_frames):
        template = xp[prev + hs : prev + 2 * hs]
        lo = tol + int(round(k * ha)) - tol
        region = xp[lo : lo + hs + 2 * tol]
        corr = np.correlate(region, template, "valid")
        cs = np.concatenate([[0.0], np.cumsum(region**2)])
        energy = cs[hs:] - cs[:-hs]
        score = corr / np.sqrt(energy * float(np.sum(template**2)) + 1e-9)
        pos = lo + int(np.argmax(score))
        out[k * hs : k * hs + win] += w * xp[pos : pos + win]
        norm[k * hs : k * hs + win] += w
        prev = pos
    y = out / np.maximum(norm, 1e-3)
    y = y[:out_len]
    if len(y) < out_len:
        y = np.pad(y, (0, out_len - len(y)))
    return y.astype(np.float32)


def frames_for(samples: int) -> int:
    return max(1, math.ceil(samples / SAMPLES_PER_FRAME))


def pad_to_frames(x: np.ndarray) -> tuple[np.ndarray, int]:
    """Append trailing silence only, so the clip holds exactly frame_count * 1600 samples."""
    frames = frames_for(len(x))
    return np.pad(x, (0, frames * SAMPLES_PER_FRAME - len(x))), frames
