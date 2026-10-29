"""Merge a Watch session recorded under its own ID ("-W") into the phone session it belongs to.

Usage (repo root):
    .venv/bin/python -m pipeline.ingest.merge_watch data/recordings/field/<phone> data/recordings/field/<watch-W>

When the Watch cannot reach the phone at Start it records under its own ID, so the phone session
has no (or only some) Watch files. The Watch's own copy of the same session (read off the Watch
when the link dropped before everything was sent) merges the same way; chunks the phone already
has are skipped. This writes a new folder `<phone>+<watch>` next to the phone
session (both device folders stay untouched): the phone session plus the Watch session's chunks,
added to the journal as received chunks (SHA-256 checked again) in Watch segments after any the
phone session already has. Then run the ingest on the new folder.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from pipeline.ingest.ingest_field import check_files, read_jsonl, relative, watch_segments

SUBDIRS = {"watch": "60hz", "watch_hf": "hf"}


def session_id(journal):
    return next((e.get("session") for e in journal if e.get("j") == "session_open"), None)


def merge(phone_dir: Path, watch_dir: Path, out_dir: Path = None) -> Path:
    phone_dir, watch_dir = Path(phone_dir), Path(watch_dir)
    out = Path(out_dir) if out_dir else phone_dir.parent / f"{phone_dir.name}+{watch_dir.name}"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(phone_dir, out)
    for derived in (
        "stream.jsonl",
        "ingest_report.json",
        "device_check.json",
        "reconstruction.mp4",
    ):
        (out / derived).unlink(missing_ok=True)

    journal, _ = read_jsonl(out / "journal.jsonl")
    watch_journal, _ = read_jsonl(watch_dir / "journal.jsonl")
    verified, problems = check_files(watch_dir, watch_journal)
    if problems:
        raise SystemExit(f"{watch_dir.name}: {problems}")

    # Watch segments already in the phone session come first; the merged ones continue after them.
    existing = {}
    for e in journal:
        if e.get("j") in ("chunk_received", "chunk_closed") and "/watch" in e.get("file", ""):
            existing[relative(e["file"])] = e
    have = watch_segments(out)
    # The Watch's own copy of this same session keeps its segments; a separate "-W" session goes
    # after whatever Watch segments the phone session already has.
    same_session = session_id(journal) == session_id(watch_journal)
    offset = (
        0
        if same_session
        else max([have.get(rel, e.get("segment", 1)) for rel, e in existing.items()], default=0)
    )
    their_segments = watch_segments(watch_dir)

    added = []
    for rel, e in sorted(verified.items()):
        sub = rel.split("/")[0]
        if sub not in SUBDIRS:
            continue
        name = Path(rel).name
        target = f"{sub}/{name}"
        data = (watch_dir / rel).read_bytes()
        if (out / target).exists():
            if (out / target).read_bytes() == data:
                continue  # the phone already has this exact chunk
            target = f"{sub}/{watch_dir.name}-{name}"
        (out / sub).mkdir(exist_ok=True)
        (out / target).write_bytes(data)
        segment = offset + their_segments.get(rel, e.get("segment", 1))
        added.append(
            {
                "j": "chunk_received",
                "file": f"sessions/{out.name}/{target}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "kind": SUBDIRS[sub],
                "segment": segment,
                "merged_from": watch_dir.name,
            }
        )
    counts = {kind: sum(1 for a in added if a["kind"] == kind) for kind in SUBDIRS.values()}
    for e in journal:
        if e.get("j") == "chunk_received" and e.get("kind") in counts:
            counts[e["kind"]] += 1
    entries = [e for e in journal if e.get("j") != "watch_summary"] + added
    entries.append({"j": "watch_summary", "chunks_60hz": counts["60hz"], "chunks_hf": counts["hf"]})
    entries.append({"j": "merged_watch_session", "from": watch_dir.name, "chunks": len(added)})
    (out / "journal.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("phone_session", type=Path)
    p.add_argument("watch_session", type=Path)
    args = p.parse_args(argv)
    out = merge(args.phone_session, args.watch_session)
    print(f"Merged into {out}\nNext: .venv/bin/python -m pipeline.ingest.ingest_field {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
