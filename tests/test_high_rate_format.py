"""W10 (Python side): the binary high-rate format reads back exactly what Swift wrote."""

import os
import struct
from pathlib import Path

import numpy as np
import pytest

from pipeline.ingest.high_rate import read_chunk, read_file

EXPORT = Path(os.environ.get("MSC_EXPORT_DIR", "/nonexistent")) / "watch_hf_sample.bin"


def test_W10_swift_chunk_round_trips_exactly():
    if not EXPORT.exists():
        pytest.skip("no exported Swift chunk (run tools/run_tests.sh)")
    chunk = read_file(EXPORT)
    assert chunk.header["format"] == "watch_hf"
    assert chunk.header["first_index"] == {"accel": 7, "motion": 3}
    expected_accel = [[100 + k / 800, 0.5, -1.25, k] for k in range(5)]
    np.testing.assert_array_equal(chunk.accel, np.array(expected_accel))
    np.testing.assert_array_equal(chunk.motion, np.array([[200.5] + [v / 4 for v in range(1, 14)]]))


def test_torn_tail_is_ignored():
    record = struct.pack("<Bd3f", 1, 1.0, 0.0, 0.0, 1.0)
    data = b'{"format":"watch_hf"}\n' + record * 3 + record[:9]
    chunk = read_chunk(data)
    assert len(chunk.accel) == 3
    assert chunk.whole_bytes == len(data) - 9
