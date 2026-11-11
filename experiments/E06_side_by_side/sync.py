"""Put a camera clip on the logger's clock from sound: ball hits are sharp, so the onset envelopes
of the camera's audio and the commercial logger's audio (timestamped) line up at one offset.

The audio is read with macOS's afconvert (no ffmpeg needed). Onsets: rise of the 10 ms RMS level in
dB, half-wave rectified, so loudness differences between microphones matter less than timing.
"""

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

RATE = 100.0  # envelope rate, Hz


def read_audio(path, sr=8000) -> np.ndarray:
    """Mono samples (-1..1) of any file afconvert can read (MOV, MP4 with sound, FLAC)."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "a.wav"
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{sr}", "-c", "1", str(path), str(out)],
            check=True, capture_output=True,
        )  # fmt: skip
        raw = out.read_bytes()
    # afconvert writes WAVE_FORMAT_EXTENSIBLE, which the wave module rejects: take the data chunk.
    i = 12
    while raw[i : i + 4] != b"data":
        i += 8 + int.from_bytes(raw[i + 4 : i + 8], "little")
    size = int.from_bytes(raw[i + 4 : i + 8], "little")
    return np.frombuffer(raw[i + 8 : i + 8 + size], np.int16).astype(float) / 32768


def onsets(x, sr=8000, rate=RATE) -> np.ndarray:
    hop = int(sr / rate)
    n = len(x) // hop
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-10)
    db = 20 * np.log10(rms)
    rise = np.clip(np.diff(db, prepend=db[0]), 0, None)
    return (rise - rise.mean()) / (rise.std() + 1e-9)


def offset_s(ref, other, rate=RATE, max_s=None) -> float:
    """Seconds `other` lags `ref` (event at ref time t is at other time t + offset), by FFT
    cross-correlation of the two onset envelopes."""
    n = 1 << int(np.ceil(np.log2(len(ref) + len(other))))
    c = np.fft.irfft(np.fft.rfft(other, n) * np.conj(np.fft.rfft(ref, n)), n)
    lags = np.r_[np.arange(0, n // 2), np.arange(-n // 2, 0)]
    if max_s is not None:
        c = np.where(np.abs(lags) <= max_s * rate, c, -np.inf)
    return float(lags[int(np.argmax(c))] / rate)


def logger_start_unix(flac, csv, tz="America/New_York") -> float:
    """Unix time of the logger audio file's first sample, from its timestamped level track
    (decibels every 50 ms) matched against the file's own level at the same rate."""
    d = pd.read_csv(csv)
    t = pd.to_datetime(d["timestamp"]).dt.tz_localize(tz).astype("int64").to_numpy() / 1e9
    grid = np.arange(t[0], t[-1], 1 / 20)
    track = np.interp(grid, t, d["decibels_db"].to_numpy(float))
    x = read_audio(flac)
    hop = 400  # 8000 Hz / 20 Hz
    n = len(x) // hop
    own = 20 * np.log10(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-10))

    def z(v):
        v = np.clip(v, -90, None)
        return (v - v.mean()) / (v.std() + 1e-9)

    lag = offset_s(z(own), z(track), rate=20.0, max_s=30)  # track time = file time + lag
    return float(grid[0] - lag)
