"""R8: chunks written by the Swift recorder load with today's motion_io, unchanged.

tools/run_tests.sh runs the Swift test test_R8_exportSessionForPythonCheck first, which writes a
session to $MSC_EXPORT_DIR; this test skips when that export doesn't exist.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from pipeline.preprocessing.motion_io import load_recording

EXPORT = Path(os.environ.get("MSC_EXPORT_DIR", "/nonexistent"))
SESSION = EXPORT / "sessions" / "20261020-120000-P98"


@pytest.fixture
def exported():
    if not (SESSION / "journal.jsonl").exists():
        pytest.skip("no exported Swift session (run tools/run_tests.sh)")
    return SESSION


def test_R8_chunks_load_with_motion_io(exported, tmp_path):
    chunks = sorted((exported / "phone").glob("*.jsonl"))
    assert len(chunks) == 3  # 130 s at 60 s per chunk
    merged = tmp_path / "stream.jsonl"
    merged.write_bytes(b"".join(c.read_bytes() for c in chunks))
    rec = load_recording(merged)
    phone = rec.streams["left_pocket"]
    assert len(phone.t) == 130 * 12 * 5
    assert phone.rate_hz == pytest.approx(60, rel=0.01)


def test_R8_journal_hashes_match_files(exported):
    entries = [json.loads(line) for line in (exported / "journal.jsonl").read_text().splitlines()]
    closed = [e for e in entries if e["j"] == "chunk_closed"]
    assert [e["j"] for e in entries][0] == "session_open"
    assert entries[-1]["j"] == "session_close"
    for e in closed:
        data = (exported.parent.parent / e["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == e["sha256"]
