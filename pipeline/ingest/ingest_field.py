"""Check a field session copied from the phone, and merge it for analysis (design §10).

Usage (repo root):
    .venv/bin/python -m pipeline.ingest.ingest_field data/recordings/field/<session>

Reads the phone's journal, verifies every chunk's SHA-256, finds missing, extra and unclosed
chunks, measures each stream (per segment) with the same rules as the app, explains gaps with the
events around them, fits the Watch clock to the phone's, checks the high-rate stream, and writes:
    ingest_report.json   status PASS / WARN / PENDING / FAIL and every finding
    stream.jsonl         all packets in order, loadable by pipeline.preprocessing.motion_io
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from pipeline.ingest.high_rate import read_file as read_high_rate
from pipeline.ingest.quality import stream_stats, stream_verdict, thresholds, worst

STREAM_DIRS = ("phone", "watch", "watch_hf")
# Events that explain a gap when they happen within this many seconds of it.
CAUSE_WINDOW_S = 2.0
CAUSE_EVENTS = {
    "airpods_disconnected", "airpods_connected", "watch_unreachable", "watch_reachable", "app_background",
    "app_inactive", "app_terminate", "app_memory_warning", "write_error", "clock_jump", "watch_workout_ended",
    "watch_silent", "resume",
}  # fmt: skip


def read_jsonl(path: Path):
    """Lines that parse; a torn last line is skipped."""
    entries, torn = [], 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            torn += 1
    return entries, torn


def relative(journal_path: str) -> str:
    """'sessions/<id>/phone/000000.jsonl' -> 'phone/000000.jsonl'."""
    parts = journal_path.split("/")
    return "/".join(parts[2:]) if parts[0] == "sessions" else journal_path


def check_files(session: Path, journal: list) -> tuple:
    """Every journalled chunk exists with the right SHA-256; nothing else is in the stream folders."""
    expected = {}
    for e in journal:
        if e.get("j") in ("chunk_closed", "chunk_received") and "file" in e:
            expected[relative(e["file"])] = e
    problems, verified = [], {}
    for rel, e in sorted(expected.items()):
        path = session / rel
        if not path.exists():
            problems.append({"file": rel, "problem": "missing"})
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != e.get("sha256"):
            problems.append({"file": rel, "problem": "sha256 mismatch"})
            continue
        verified[rel] = e
    for sub in STREAM_DIRS:
        for path in sorted((session / sub).glob("*")) if (session / sub).exists() else []:
            rel = f"{sub}/{path.name}"
            if path.name.endswith(".open"):
                problems.append(
                    {"file": rel, "problem": "unclosed chunk (open the app to recover it)"}
                )
            elif rel not in expected:
                problems.append(
                    {"file": rel, "problem": "extra file not in the journal (not merged)"}
                )
    return verified, problems


def watch_segments(session: Path) -> dict:
    """Watch chunk file -> segment, from the Watch's journal snapshot (segment 1 if unknown)."""
    snapshot = session / "watch_journal.jsonl"
    if not snapshot.exists():
        return {}
    entries, _ = read_jsonl(snapshot)
    return {
        relative(e["file"]): e.get("segment", 1) for e in entries if e.get("j") == "chunk_closed"
    }


def load_packets(session: Path, verified: dict) -> list:
    """Packets from verified JSON chunks, in journal order, each tagged with its segment.
    When the Watch's own chunks are present, they replace the Watch preview copied by the phone."""
    w_segments = watch_segments(session)
    has_watch_disk = any(rel.startswith("watch/") for rel in verified)
    packets = []
    for rel, e in verified.items():
        if not rel.endswith(".jsonl") or rel.startswith("watch_journal"):
            continue
        segment = e.get("segment") or w_segments.get(rel, 1)
        for p in read_jsonl(session / rel)[0]:
            if (
                rel.startswith("phone/")
                and p.get("type") == "imu"
                and p.get("device") == "watch"
                and has_watch_disk
            ):
                continue
            p["segment"] = segment
            packets.append(p)
    return packets


def stream_items(packets: list) -> dict:
    """(device, segment) -> [(index, t), ...] in arrival order."""
    items = {}
    for p in packets:
        if p.get("type") != "imu":
            continue
        key = (p["device"], p["segment"])
        items.setdefault(key, []).extend((p["first_index"] + k, s[0]) for k, s in enumerate(p["s"]))
    return items


def gaps_with_causes(items: list, events: list, gap_s: float, window=None, to_phone=None) -> list:
    """Gaps longer than gap_s, including a late start or early stop inside `window` (the
    stream's own clock); `to_phone` maps those times to the phone clock to find causes."""
    to_phone = to_phone or (lambda x: x)
    unique = sorted({i: t for i, t in items}.items())
    t = np.array([x[1] for x in unique])
    if window is not None:
        t = np.concatenate([[min(window[0], t[0])], t, [max(window[1], t[-1])]])
    out = []
    for k in np.nonzero(np.diff(t) > gap_s)[0]:
        start, end = to_phone(float(t[k])), to_phone(float(t[k + 1]))
        causes = sorted(
            {
                e["name"]
                for e in events
                if e.get("name") in CAUSE_EVENTS
                and "t_phone" in e
                and start - CAUSE_WINDOW_S <= e["t_phone"] <= end + CAUSE_WINDOW_S
            }
        )
        out.append(
            {
                "start": round(start, 3),
                "length_s": round(end - start, 3),
                "causes": causes or ["unknown"],
            }
        )
    return out


def clock_fit(syncs: list) -> dict:
    """Watch clock vs phone clock from the 5 s sync pings: offset (s) and drift (ppm)."""
    if len(syncs) < 3:
        return {"pings": len(syncs), "status": "too few pings"}
    mid = np.array([(s["t_phone_send"] + s["t_phone_recv"]) / 2 for s in syncs])
    offset = np.array([s["t_watch"] for s in syncs]) - mid
    slope, intercept = np.polyfit(mid - mid[0], offset, 1)
    residual = offset - (intercept + slope * (mid - mid[0]))
    return {
        "pings": len(syncs),
        "offset_s": round(float(intercept), 6),
        "drift_ppm": round(float(slope * 1e6), 3),
        "residual_ms_rms": round(float(np.sqrt(np.mean(residual**2)) * 1000), 3),
        "t0_phone": round(float(mid[0]), 6),
    }


def session_windows(packets: list, fit: dict) -> dict:
    """(device, segment) -> (t0, t1) the stream should cover, on that device's clock: the span
    of the phone's own stream, which runs from Start to Stop. The Watch's is mapped through the
    clock fit; without a fit the Watch keeps its own span."""
    spans = {}
    for (device, segment), items in stream_items(packets).items():
        if device == "phone":
            times = [t for _, t in items]
            spans[segment] = (min(times), max(times))
    windows = {}
    for device, segment in stream_items(packets):
        span = spans.get(segment)
        if span is None:
            continue
        if device == "watch":
            if "offset_s" not in fit:
                continue
            span = tuple(watch_time(t, fit) for t in span)
        windows[(device, segment)] = span
    return windows


def watch_time(t_phone: float, fit: dict) -> float:
    return t_phone + fit["offset_s"] + fit["drift_ppm"] * 1e-6 * (t_phone - fit["t0_phone"])


def phone_time(t_watch: float, fit: dict) -> float:
    rate = 1 + fit["drift_ppm"] * 1e-6
    return (t_watch - fit["offset_s"] + fit["drift_ppm"] * 1e-6 * fit["t0_phone"]) / rate


def extra_sensors(packets: list) -> dict:
    """Packets of the extra sensors (design §9) per type and device; UWB is optional."""
    counts = {}
    for p in packets:
        kind = p.get("type")
        if kind in ("baro", "mag", "audio_level", "uwb"):
            key = f"{kind}/{p.get('device', '?')}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def check_high_rate(session: Path, journal: list, verified: dict, phone_only: bool) -> dict:
    summary = next((e for e in reversed(journal) if e.get("j") == "watch_summary"), None)
    received = sorted(rel for rel in verified if rel.startswith("watch_hf/"))
    expected = summary.get("chunks_hf") if summary else None
    result = {"chunks_expected": expected, "chunks_received": len(received)}
    if summary is None and not any(rel.startswith("watch") for rel in verified):
        # No Watch data at all: a phone-only session, or the Watch never recorded.
        result["status"] = "SKIPPED" if phone_only else "FAIL"
        result["detail"] = "no Watch data in this session"
        return result
    if expected is None or len(received) < expected:
        result["status"] = "PENDING"
        result["detail"] = (
            "high-rate chunks still on the Watch: keep it near the phone until all are sent"
        )
        return result
    counts = {"accel": 0, "motion": 0}
    continuity = []
    for rel in received:
        chunk = read_high_rate(session / rel)
        first = chunk.header.get("first_index", {})
        for kind, n in (("accel", len(chunk.accel)), ("motion", len(chunk.motion))):
            if first.get(kind, counts[kind]) not in (counts[kind], 0):
                continuity.append(
                    f"{rel}: {kind} starts at {first.get(kind)}, expected {counts[kind]}"
                )
            counts[kind] = (first.get(kind, counts[kind]) or 0) + n
    result.update({"samples": counts, "continuity_problems": continuity})
    result["status"] = "FAIL" if continuity else "PASS"
    return result


def planned_devices(events):
    """Devices chosen at Go/No-Go: its `required` list, or (older app builds) the devices with a
    `<device>_live` check. None when the session has no Go/No-Go: every stream counts."""
    gonogo = next((e for e in events if e.get("name") == "gonogo"), None)
    if gonogo is None:
        return None
    if "required" in gonogo:
        return set(gonogo["required"]) | {"phone"}
    live = {
        c["id"][: -len("_live")]
        for c in gonogo.get("checks", [])
        if c.get("id", "").endswith("_live")
    }
    return (live | {"phone"}) if live else None


def ingest(session: Path, phone_only: bool = False) -> dict:
    journal_path = session / "journal.jsonl"
    if not journal_path.exists():
        raise FileNotFoundError(f"{journal_path} not found: is this a field session folder?")
    journal, torn = read_jsonl(journal_path)
    verified, problems = check_files(session, journal)
    packets = load_packets(session, verified)
    events = [p for p in packets if p.get("type") == "event"]
    gap_s = thresholds()["gap_s"]
    plan = planned_devices(events)

    fit = clock_fit([p for p in packets if p.get("type") == "sync"])
    windows = session_windows(packets, fit)
    streams = {}
    for (device, segment), items in sorted(stream_items(packets).items()):
        window = windows.get((device, segment))
        stats = stream_stats(items, window=window)
        if window is not None and stats.samples:
            # A late start or early stop is a gap too (the shared S4 rules count inner gaps only).
            times = sorted(t for _, t in items if window[0] <= t <= window[1])
            edge_ms = max(times[0] - window[0], window[1] - times[-1]) * 1000
            if edge_ms > gap_s * 1000:
                stats.gaps_over_threshold += 1
            stats.longest_gap_ms = round(max(stats.longest_gap_ms, edge_ms), 1)
        to_phone = (lambda t: phone_time(t, fit)) if device == "watch" and window else None
        streams[f"{device}/segment{segment}"] = {
            "device": device,
            "segment": segment,
            "verdict": stream_verdict(stats, device),
            # A device outside the Go/No-Go plan is measured and shown but cannot fail the session.
            "planned": plan is None or device in plan,
            **stats.as_dict(),
            "gaps": gaps_with_causes(items, events, gap_s, window, to_phone),
        }
    high_rate = check_high_rate(session, journal, verified, phone_only)
    file_status = "FAIL" if problems else "PASS"
    hf_status = "PASS" if high_rate["status"] == "SKIPPED" else high_rate["status"]
    verdicts = [s["verdict"] for s in streams.values() if s["planned"]]
    status = worst([file_status] + verdicts + [hf_status])
    report = {
        "session": session.name,
        "status": status,
        "verified": status in ("PASS", "WARN"),
        "segments": max([s["segment"] for s in streams.values()], default=1),
        "file_problems": problems,
        "journal_torn_lines": torn,
        "chunks_verified": len(verified),
        "streams": streams,
        "watch_hf": high_rate,
        "clock_fit": fit,
        "extra_sensors": extra_sensors(packets),
    }
    with open(session / "stream.jsonl", "w") as f:
        for p in packets:
            f.write(json.dumps(p) + "\n")
    (session / "ingest_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("session", type=Path)
    parser.add_argument(
        "--phone-only", action="store_true", help="the session had no Watch (not a failure)"
    )
    args = parser.parse_args(argv)
    report = ingest(args.session, phone_only=args.phone_only)
    print(f"{report['session']}: {report['status']}")
    for p in report["file_problems"]:
        print(f"  ✗ {p['file']}: {p['problem']}")
    for name, s in report["streams"].items():
        note = "" if s["planned"] else " (not in the Go/No-Go plan: ignored)"
        print(f"  {name}: {s['verdict']} coverage {s['coverage']:.3f}, {len(s['gaps'])} gaps{note}")
    print(f"  watch_hf: {report['watch_hf']['status']}")
    return 0 if report["status"] in ("PASS", "WARN", "PENDING") else 1


if __name__ == "__main__":
    sys.exit(main())
