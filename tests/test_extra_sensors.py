"""X4: recordings with the extra-sensor packets still load and ingest; UWB is optional."""

import json
import os
from pathlib import Path

import pytest

from pipeline.ingest.ingest_field import ingest
from pipeline.preprocessing.motion_io import load_recording
from tests.test_ingest import FieldSession

EXPORT = Path(os.environ.get("MSC_EXPORT_DIR", "/nonexistent")) / "x4_stream.jsonl"


@pytest.fixture
def x4_lines():
    if not EXPORT.exists():
        pytest.skip("no exported Swift stream (run tools/run_tests.sh)")
    return [json.loads(line) for line in EXPORT.read_text().splitlines()]


def test_X4_motion_io_ignores_new_packet_types(x4_lines):
    rec = load_recording(EXPORT)
    assert len(rec.streams["right_pocket"].t) == 1200
    assert {p["type"] for p in x4_lines} == {"imu", "baro", "mag", "audio_level"}


def test_X4_ingest_counts_extra_sensors_and_uwb_is_optional(x4_lines, tmp_path):
    fs = FieldSession(tmp_path)
    for k in range(0, len(x4_lines), 300):
        fs.phone_chunk(x4_lines[k : k + 300])
    report = ingest(fs.close(), phone_only=True)
    assert report["status"] in ("PASS", "WARN")
    assert report["extra_sensors"] == {"baro/phone": 20, "mag/phone": 20, "audio_level/phone": 240}
    assert "uwb/phone" not in report["extra_sensors"]
