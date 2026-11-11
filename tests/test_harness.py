"""Gate G0 (Python side): the pipeline loads recordings, synthetic and real."""

import json

import pytest

from pipeline.preprocessing.motion_io import load_recording
from pipeline.preprocessing.resample import resample
from tests.conftest import KEY_SESSIONS, recording_dir


def test_synthetic_session_loads_and_resamples(synthetic_session):
    rec = load_recording(synthetic_session)
    assert set(rec.streams) == {"left_pocket", "left_wrist"}
    phone = rec.streams["left_pocket"]
    assert len(phone.t) == 1200
    assert phone.rate_hz == pytest.approx(60, rel=1e-3)
    res = resample(phone)
    assert len(res.t) == pytest.approx(20 * 30, abs=2)


@pytest.mark.parametrize("session", KEY_SESSIONS)
def test_key_recordings_load_every_sample(session):
    path = recording_dir(session)
    expected = {}
    for line in (path / "mac_stream.jsonl").read_text().splitlines():
        p = json.loads(line)
        if p.get("type") == "imu":
            idx = {p["first_index"] + k for k in range(len(p["s"]))}
            expected.setdefault(p["loc"], set()).update(idx)
    rec = load_recording(path)
    for loc, indices in expected.items():
        assert len(rec.streams[loc].t) == len(indices), loc
