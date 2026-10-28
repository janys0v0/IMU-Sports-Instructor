"""Merging a Watch session that recorded under its own ID ("-W") into the phone session it belongs to.

Found on device 2026-10-28: the Watch was unreachable at Start, started its own session 17 s later
and never joined, so 20261028-104120-P01 had no Watch files and 20261028-104137-W had all 47 min.
"""

from pipeline.ingest.ingest_field import ingest
from pipeline.ingest.merge_watch import merge
from tests.test_ingest import FieldSession, minutes_of

WATCH_SESSION = "20261020-120017-W"


def split_session(tmp_path):
    phone = FieldSession(tmp_path / "phone")
    for chunk in minutes_of("phone", 2):
        phone.phone_chunk(chunk)
    phone_dir = phone.close()
    watch = FieldSession(tmp_path / "watch", WATCH_SESSION)
    for chunk in minutes_of("watch", 2):
        watch.watch_chunk(chunk)
    watch.hf_chunk(0, 800)
    watch.hf_chunk(800, 800)
    watch.watch_summary(2, 2)
    return phone_dir, watch.close()


def test_merged_session_has_the_watch_data_and_passes(tmp_path):
    phone_dir, watch_dir = split_session(tmp_path)
    assert ingest(phone_dir)["status"] == "FAIL"  # no Watch data in the phone session
    out = merge(phone_dir, watch_dir)
    report = ingest(out)
    assert report["status"] == "PASS", report["file_problems"]
    assert report["streams"]["watch/segment1"]["coverage"] > 0.99
    assert report["watch_hf"]["status"] == "PASS"
    assert out.name == f"{phone_dir.name}+{WATCH_SESSION}"


def test_device_folders_are_left_untouched(tmp_path):
    phone_dir, watch_dir = split_session(tmp_path)
    before = {
        p: p.read_bytes() for d in (phone_dir, watch_dir) for p in d.rglob("*") if p.is_file()
    }
    merge(phone_dir, watch_dir)
    after = {p: p.read_bytes() for d in (phone_dir, watch_dir) for p in d.rglob("*") if p.is_file()}
    assert before == after


def test_watch_files_already_in_the_phone_session_are_kept_apart(tmp_path):
    # The phone session has the Watch's first minute; the -W session has later minutes.
    phone = FieldSession(tmp_path / "phone")
    for chunk in minutes_of("phone", 3):
        phone.phone_chunk(chunk)
    phone.watch_chunk(minutes_of("watch", 1)[0])
    phone_dir = phone.close()
    watch = FieldSession(tmp_path / "watch", WATCH_SESSION)
    for chunk in minutes_of("watch", 2, t0=160.0):
        watch.watch_chunk(chunk)
    watch_dir = watch.close()
    out = merge(phone_dir, watch_dir)
    report = ingest(out, phone_only=True)
    assert not report["file_problems"]
    assert {"watch/segment1", "watch/segment2"} <= set(report["streams"])
