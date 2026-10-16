"""Read the Watch's binary high-rate chunks (docs/plan/design.md §2).

Each chunk: one JSON header line ending in "\n", then little-endian records:
    tag 1 accel  (800 Hz): t float64, ax ay az float32 (g)
    tag 2 motion (200 Hz): t float64, 13 x float32 (qx qy qz qw ax ay az gx gy gz rx ry rz)
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ACCEL_TAG, MOTION_TAG = 1, 2
SIZES = {ACCEL_TAG: 1 + 8 + 3 * 4, MOTION_TAG: 1 + 8 + 13 * 4}


@dataclass
class HighRateChunk:
    header: dict
    accel: np.ndarray  # (N, 4): t, ax, ay, az
    motion: np.ndarray  # (M, 14): t, then the 13 motion values
    whole_bytes: int  # bytes holding the header and whole records (the rest is a torn tail)


def read_chunk(data: bytes) -> HighRateChunk:
    nl = data.index(b"\n")
    header = json.loads(data[:nl])
    accel, motion = [], []
    i = nl + 1
    while i < len(data):
        size = SIZES.get(data[i], 0)
        if size == 0 or i + size > len(data):
            break
        t = np.frombuffer(data, "<f8", 1, i + 1)[0]
        n = 3 if data[i] == ACCEL_TAG else 13
        values = np.frombuffer(data, "<f4", n, i + 9).astype(np.float64)
        (accel if data[i] == ACCEL_TAG else motion).append(np.concatenate([[t], values]))
        i += size
    return HighRateChunk(
        header,
        np.array(accel).reshape(-1, 4),
        np.array(motion).reshape(-1, 14),
        i,
    )


def read_file(path: Path) -> HighRateChunk:
    return read_chunk(Path(path).read_bytes())
