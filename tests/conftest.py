"""Shared pytest fixtures. Run from the repo root: tools/run_tests.sh (or python -m pytest)."""

import json
from pathlib import Path

import pytest

from pipeline.paths import RECORDINGS

KEY_SESSIONS = [
    "20261008-153213-P01",  # reference routine, all 3 devices
    "20261008-153037-P01",  # no calibrate events (the timer bug)
    "20261008-152437-P01",  # AirPods start after the first calibration
    "20261008-150130-P01",  # 4 min, AirPods with 1 s gaps
]


def recording_dir(session: str) -> Path:
    """A real recording, or skip: data/recordings is not in git (and not in CI)."""
    path = RECORDINGS / session
    if not (path / "mac_stream.jsonl").exists():
        pytest.skip(f"recording {session} not available")
    return path


def still_sample(t: float) -> list:
    return [t, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0]


@pytest.fixture
def synthetic_session(tmp_path) -> Path:
    """A 20 s phone + Watch session at 60 Hz in today's packet format."""
    lines = [{"type": "event", "name": "start", "t_phone": 100.0, "unix": 1.79e9}]
    for device, loc in (("phone", "left_pocket"), ("watch", "left_wrist")):
        for first in range(0, 1200, 5):
            samples = [still_sample(100 + (first + k) / 60) for k in range(5)]
            lines.append(
                {
                    "type": "imu", "device": device, "loc": loc, "seq": first // 5,
                    "first_index": first, "rate_hz": 60, "boot_to_unix": 1.79e9,
                    "ref_frame": "xMagneticNorthZVertical", "s": samples,
                }
            )  # fmt: skip
    session = tmp_path / "20261020-120000-P99"
    session.mkdir()
    (session / "mac_stream.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return session
