"""The T6 device-check report works on a session shaped like a real one."""

import struct

from pipeline.analysis.device_check import check
from tests.test_ingest import FieldSession, imu


def airpods_minutes(n_minutes, t0=100.0, drop_after_speech=False, speech_at=()):
    packets = []
    for m in range(n_minutes):
        for k in range(0, 3000, 5):
            t = t0 + 60 * m + k / 50
            if drop_after_speech and any(s <= t < s + 3 for s in speech_at):
                continue
            packets.append(
                imu("phone", 3000 * m + k, t, rate=50, loc="head") | {"device": "airpods"}
            )
    return packets


def make_session(tmp_path, drop_after_speech=False, locked=True, started_locked=False):
    fs = FieldSession(tmp_path)
    speech = [130.0, 160.0, 190.0]
    phone = [imu("phone", 5 * k, 100 + 5 * k / 33, rate=33) for k in range(0, 3 * 33 * 60 // 5)]
    events = [{"type": "event", "name": "prompt", "start": s, "t_phone": s} for s in speech]
    if started_locked:
        # Started from the Watch with the phone already locked: only the final unlock is logged.
        events.append({"type": "event", "name": "app_foreground", "t_phone": 279.0})
    elif locked:
        events.append({"type": "event", "name": "app_background", "t_phone": 101.0})
    fs.phone_chunk(
        phone + airpods_minutes(3, drop_after_speech=drop_after_speech, speech_at=speech) + events
    )
    header = b'{"format":"watch_hf","first_index":{"accel":0,"motion":0}}\n'
    body = b"".join(struct.pack("<Bd3f", 1, 100 + k / 800, 0, 0, 1) for k in range(1600))
    body += b"".join(struct.pack("<Bd13f", 2, 100 + k / 200, *([0.0] * 13)) for k in range(400))
    (fs.dir / "watch_hf" / "000000.bin").write_bytes(header + body)
    import hashlib

    data = header + body
    fs.journal.append(
        {"j": "chunk_received", "file": f"sessions/{fs.dir.name}/watch_hf/000000.bin",
         "sha256": hashlib.sha256(data).hexdigest(), "kind": "hf"}
    )  # fmt: skip
    fs.journal.append({"j": "health", "unix": 0, "battery_phone": 0.9, "battery_watch": 0.8})
    fs.journal.append({"j": "health", "unix": 1200, "battery_phone": 0.85, "battery_watch": 0.7})
    fs.watch_summary(0, 1)
    return fs.close()


def test_t6_passes_on_a_clean_locked_session(tmp_path):
    results = check(make_session(tmp_path))
    assert results["phone_coverage"]["pass"]
    assert results["airpods_during_speech"]["pass"]
    assert results["watch_high_rate_hz"]["accel"] > 790
    assert results["battery_used"]["watch"] == {"percent": 10.0, "minutes": 20.0}
    assert results["T6"] == "PASS"


def test_t6_fails_when_the_ingest_fails(tmp_path):
    # Watch files under another session ID are not in this journal: the ingest refuses them.
    session = make_session(tmp_path)
    (session / "watch_hf" / "000001.bin").write_bytes(b"stray")
    results = check(session)
    assert results["ingest"] == {"status": "FAIL", "pass": False}
    assert results["T6"] == "FAIL"


def test_t6_fails_when_the_phone_was_never_locked(tmp_path):
    # The app stays in the foreground (screen kept on, pocket mode): not the locked case T6 tests.
    results = check(make_session(tmp_path, locked=False))
    assert results["phone_locked"] == {"fraction": 0.0, "pass": False}
    assert results["T6"] == "FAIL"


def test_t6_fails_when_airpods_stop_during_speech(tmp_path):
    results = check(make_session(tmp_path, drop_after_speech=True))
    assert not results["airpods_during_speech"]["pass"]
    assert results["T6"] == "FAIL"


def test_t6_counts_a_phone_locked_before_start(tmp_path):
    # Field session 20261018-210809-P01 was started from the Watch with the phone already locked.
    results = check(make_session(tmp_path, started_locked=True))
    assert results["phone_locked"]["fraction"] > 0.98
    assert results["phone_locked"]["pass"]
