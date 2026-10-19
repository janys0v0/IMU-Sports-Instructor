"""Stage 3 gate (G3): the Mac ingest script, tests I1-I8 and the Python half of S4."""

import hashlib
import json
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from pipeline.ingest.ingest_field import clock_fit, ingest
from pipeline.ingest.quality import stream_stats, stream_verdict
from pipeline.preprocessing.motion_io import load_recording
from tests.conftest import KEY_SESSIONS, recording_dir, still_sample

FIXTURES = Path(__file__).parent / "fixtures" / "contract"
SESSION = "20261020-120000-P01"


class FieldSession:
    """Writes a session folder the way the phone and Watch do: chunks, journal, Watch summary."""

    def __init__(self, root: Path):
        self.dir = root / SESSION
        self.journal = [{"j": "session_open", "session": SESSION}]
        for sub in ("phone", "watch", "watch_hf"):
            (self.dir / sub).mkdir(parents=True)
        self.numbers = {"phone": 0, "watch": 0, "watch_hf": 0}

    def _write(self, sub, data: bytes, ext="jsonl") -> str:
        rel = f"{sub}/{self.numbers[sub]:06d}.{ext}"
        self.numbers[sub] += 1
        (self.dir / rel).write_bytes(data)
        return rel

    def phone_chunk(self, packets, segment=1):
        data = b"".join(json.dumps(p).encode() + b"\n" for p in packets)
        rel = self._write("phone", data)
        self.journal.append(
            {
                "j": "chunk_closed",
                "file": f"sessions/{SESSION}/{rel}",
                "sha256": sha(data),
                "segment": segment,
            }
        )
        return rel

    def watch_chunk(self, packets):
        data = b"".join(json.dumps(p).encode() + b"\n" for p in packets)
        rel = self._write("watch", data)
        self.journal.append(
            {
                "j": "chunk_received",
                "file": f"sessions/{SESSION}/{rel}",
                "sha256": sha(data),
                "kind": "60hz",
            }
        )
        return rel

    def hf_chunk(self, first_accel, n_accel):
        header = json.dumps(
            {"format": "watch_hf", "first_index": {"accel": first_accel, "motion": 0}}
        ).encode()
        body = b"".join(
            struct.pack("<Bd3f", 1, 100 + (first_accel + k) / 800, 0, 0, 1) for k in range(n_accel)
        )
        data = header + b"\n" + body
        rel = self._write("watch_hf", data, "bin")
        self.journal.append(
            {
                "j": "chunk_received",
                "file": f"sessions/{SESSION}/{rel}",
                "sha256": sha(data),
                "kind": "hf",
            }
        )
        return rel

    def segment(self, n):
        self.journal.append({"j": "segment_open", "segment": n})

    def watch_summary(self, chunks_60hz, chunks_hf):
        self.journal.append(
            {"j": "watch_summary", "chunks_60hz": chunks_60hz, "chunks_hf": chunks_hf}
        )

    def close(self):
        self.journal.append({"j": "session_close", "clean": True})
        (self.dir / "journal.jsonl").write_text("".join(json.dumps(e) + "\n" for e in self.journal))
        return self.dir


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def imu(device, first, t0, n=5, rate=60.0, loc=None):
    return {
        "type": "imu", "device": device, "loc": loc or {"phone": "right_pocket", "watch": "right_wrist"}[device],
        "first_index": first, "boot_to_unix": 1.79e9, "s": [still_sample(t0 + k / rate) for k in range(n)],
    }  # fmt: skip


def minutes_of(device, minutes, start_index=0, t0=100.0):
    """Packets for `minutes` of a 60 Hz stream, one list per minute."""
    out = []
    for m in range(minutes):
        out.append(
            [
                imu(device, start_index + 3600 * m + 5 * k, t0 + 60 * m + 5 * k / 60)
                for k in range(720)
            ]
        )
    return out


@pytest.fixture
def complete_session(tmp_path):
    fs = FieldSession(tmp_path)
    for chunk in minutes_of("phone", 2):
        fs.phone_chunk(chunk)
    for chunk in minutes_of("watch", 2):
        fs.watch_chunk(chunk)
    fs.hf_chunk(0, 800)
    fs.hf_chunk(800, 800)
    fs.watch_summary(2, 2)
    return fs.close()


def test_complete_session_passes(complete_session):
    report = ingest(complete_session)
    assert report["status"] == "PASS"
    assert report["verified"] is True
    assert report["chunks_verified"] == 6
    assert set(report["streams"]) == {"phone/segment1", "watch/segment1"}
    rec = load_recording(complete_session / "stream.jsonl")
    assert len(rec.streams["right_pocket"].t) == 7200


def test_I1_flipped_byte_fails_that_chunk_by_name(complete_session):
    path = complete_session / "phone" / "000001.jsonl"
    data = bytearray(path.read_bytes())
    data[1000] ^= 0xFF
    path.write_bytes(bytes(data))
    report = ingest(complete_session)
    assert report["status"] == "FAIL"
    assert {"file": "phone/000001.jsonl", "problem": "sha256 mismatch"} in report["file_problems"]


def test_I2_missing_extra_and_renamed_chunks_are_reported_not_merged(complete_session):
    (complete_session / "phone" / "000000.jsonl").rename(
        complete_session / "phone" / "000009.jsonl"
    )
    (complete_session / "watch" / "000001.jsonl").unlink()
    report = ingest(complete_session)
    problems = {(p["file"], p["problem"].split(" ")[0]) for p in report["file_problems"]}
    assert ("phone/000000.jsonl", "missing") in problems
    assert ("phone/000009.jsonl", "extra") in problems
    assert ("watch/000001.jsonl", "missing") in problems
    assert report["status"] == "FAIL"
    rec = load_recording(complete_session / "stream.jsonl")
    assert len(rec.streams["right_pocket"].t) == 3600, "the extra file isn't merged"


def test_I3_segments_merge_in_order_keyed_by_segment_and_index(tmp_path):
    fs = FieldSession(tmp_path)
    fs.phone_chunk(minutes_of("phone", 1)[0], segment=1)
    fs.segment(2)
    fs.phone_chunk(minutes_of("phone", 1, t0=500.0)[0], segment=2)  # indices restart at 0
    fs.watch_summary(0, 0)
    session = fs.close()
    report = ingest(session)
    assert report["segments"] == 2
    assert report["streams"]["phone/segment1"]["samples"] == 3600
    assert report["streams"]["phone/segment2"]["samples"] == 3600
    merged = [json.loads(line) for line in (session / "stream.jsonl").read_text().splitlines()]
    assert [p["segment"] for p in merged] == sorted(p["segment"] for p in merged)
    keys = {(p["segment"], p["first_index"]) for p in merged}
    assert len(keys) == len(merged), "(segment, index) is unique"


def test_I4_clock_fit_recovers_offset_and_drift():
    rng = np.random.default_rng(4)
    syncs = []
    for k in range(720):  # one ping every 5 s for an hour
        send = 1000.0 + 5 * k
        recv = send + 0.08 + rng.uniform(0, 0.02)
        mid = (send + recv) / 2
        watch = mid + 2.5 + 50e-6 * (mid - 1000.04) + rng.normal(0, 0.002)
        syncs.append({"t_phone_send": send, "t_phone_recv": recv, "t_watch": watch})
    fit = clock_fit(syncs)
    assert fit["offset_s"] == pytest.approx(2.5, abs=0.001)
    assert fit["drift_ppm"] == pytest.approx(50, abs=1)


def test_I5_reference_session_round_trips_exactly(tmp_path):
    ref = recording_dir("20261008-153213-P01") / "mac_stream.jsonl"
    packets = [json.loads(line) for line in ref.read_text().splitlines()]
    fs = FieldSession(tmp_path)
    for k in range(0, len(packets), 400):
        fs.phone_chunk(packets[k : k + 400])
    session = fs.close()
    report = ingest(session, phone_only=True)
    assert report["status"] in ("PASS", "WARN")
    before, after = load_recording(ref), load_recording(session / "stream.jsonl")
    assert set(before.streams) == set(after.streams)
    for loc in before.streams:
        np.testing.assert_array_equal(before.streams[loc].t, after.streams[loc].t)
        np.testing.assert_array_equal(before.streams[loc].quat, after.streams[loc].quat)
    # E03's numbers from the merged stream equal the committed E03 results.
    from experiments.common import stream_quality

    merged = tmp_path / "merged_session"
    merged.mkdir()
    shutil.copy(session / "stream.jsonl", merged / "mac_stream.jsonl")
    rec = stream_quality.load(merged)
    e03_path = Path("experiments/E03_stream_quality/results/20261008-153213-P01/metrics.json")
    e03 = json.loads(e03_path.read_text())
    stop = next(t for name, t in rec.events if name == "stop")
    for loc, info in e03["streams"].items():
        summary = rec.streams[loc].summary(0, stop)
        for key in ("samples", "missing_from_index", "gaps_over_100ms", "coverage", "delivered_hz"):
            assert summary[key] == info["whole_session"][key], (loc, key)


def test_I6_every_recording_still_loads_and_measures():
    from experiments.common import stream_quality
    from pipeline.paths import RECORDINGS

    sessions = sorted(p.parent for p in RECORDINGS.glob("*/mac_stream.jsonl"))
    if not sessions:
        pytest.skip("no recordings available")
    for session in sessions:
        rec = load_recording(session)
        assert rec.streams, session.name
        sq = stream_quality.load(session)
        for stream in sq.streams.values():
            stream.summary()


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_I7_S4_python_rules_match_contract_fixtures(fixture):
    f = json.loads(fixture.read_text())
    stats = stream_stats(
        [tuple(x) for x in f["items"]], window=tuple(f["window"]) if f["window"] else None
    )
    assert stats.as_dict() | {"verdict": stream_verdict(stats, f["device"])} == f["expected"]


def test_I8a_high_rate_still_on_watch_is_pending_not_failed(tmp_path):
    fs = FieldSession(tmp_path)
    for chunk in minutes_of("phone", 1):
        fs.phone_chunk(chunk)
    for chunk in minutes_of("watch", 1):
        fs.watch_chunk(chunk)
    fs.hf_chunk(0, 800)
    fs.watch_summary(1, 3)
    report = ingest(fs.close())
    assert report["watch_hf"]["status"] == "PENDING"
    assert report["status"] == "PENDING"
    assert report["verified"] is False


def test_I8b_all_high_rate_arrived_and_continuous(complete_session):
    report = ingest(complete_session)
    assert report["watch_hf"]["status"] == "PASS"
    assert report["watch_hf"]["samples"]["accel"] == 1600
    assert report["watch_hf"]["continuity_problems"] == []


def test_gaps_are_explained_by_nearby_events(tmp_path):
    fs = FieldSession(tmp_path)
    packets = minutes_of("phone", 1)[0]
    del packets[300:330]  # 2.5 s gap at t = 125 s
    packets.append({"type": "event", "name": "app_background", "t_phone": 125.5})
    fs.phone_chunk(packets)
    report = ingest(fs.close(), phone_only=True)
    gaps = report["streams"]["phone/segment1"]["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["causes"] == ["app_background"]
    assert gaps[0]["length_s"] == pytest.approx(2.517, abs=0.01)


def test_key_recordings_still_listed():
    assert len(KEY_SESSIONS) == 4


def test_stream_that_stops_early_fails_over_the_whole_session(tmp_path):
    # Field session 20261018-210809-P01: AirPods motion stopped after 37 s of a 25 min run, but
    # coverage over the stream's own span read 100 %.
    fs = FieldSession(tmp_path)
    for chunk in minutes_of("phone", 3):
        airpods = (
            [
                imu("phone", 5 * k, 100 + 5 * k / 50, rate=50, loc="head") | {"device": "airpods"}
                for k in range(600)
            ]
            if not fs.numbers["phone"]
            else []
        )
        fs.phone_chunk(chunk + airpods)
    report = ingest(fs.close(), phone_only=True)
    phone, head = report["streams"]["phone/segment1"], report["streams"]["airpods/segment1"]
    assert phone["verdict"] == "PASS"
    assert head["coverage"] == pytest.approx(1 / 3, abs=0.02)
    assert head["verdict"] == "FAIL"
    assert head["gaps"][-1]["length_s"] == pytest.approx(120, abs=1)


def test_watch_stream_window_uses_the_clock_fit(tmp_path):
    # The Watch clock runs 5000 s ahead; its stream stops after 1 of 2 minutes.
    fs = FieldSession(tmp_path)
    syncs = [
        {"type": "sync", "t_phone_send": t, "t_phone_recv": t + 0.01, "t_watch": t + 5000.005}
        for t in np.arange(100, 220, 5.0)
    ]
    phone = minutes_of("phone", 2)
    fs.phone_chunk(phone[0] + syncs)
    fs.phone_chunk(phone[1])
    fs.watch_chunk(minutes_of("watch", 1, t0=5100.0)[0])
    report = ingest(fs.close(), phone_only=True)
    watch = report["streams"]["watch/segment1"]
    assert watch["coverage"] == pytest.approx(0.5, abs=0.02)
    assert watch["verdict"] == "FAIL"
