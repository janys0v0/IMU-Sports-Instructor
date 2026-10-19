"""Device test T6 (the stage 0b early check), from a session copied off the phone.

Usage (repo root):
    .venv/bin/python -m pipeline.analysis.device_check data/recordings/field/<session>

Runs the ingest, then checks T6's pass conditions (docs/plan/test-plan.md §4):
    the phone was locked (app in the background) for >= 80 % of the recording,
    phone and AirPods >= 95 % of expected samples (the phone was locked in a pocket),
    AirPods rate around each spoken phrase within 10 % of their normal rate,
    Watch high-rate stream close to 800 + 200 samples per second,
and the ingest itself passes; reports the battery used per device. Writes device_check.json next to the report.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from pipeline.ingest.high_rate import read_file as read_high_rate
from pipeline.ingest.ingest_field import ingest, read_jsonl

MIN_COVERAGE = 0.95
MIN_LOCKED_FRACTION = 0.8
SPEECH_RATE_TOLERANCE = 0.10
HIGH_RATE = {"accel": 800, "motion": 200}


def locked_fraction(packets):
    """Share of the recording the app spent in the background (phone locked), from the app's
    app_background / app_foreground events. Pocket mode keeps the app in the foreground."""
    t = [
        s[0]
        for p in packets
        if p.get("type") == "imu" and p.get("device") == "phone"
        for s in p["s"]
    ]
    if len(t) < 2:
        return 0.0
    start, end = min(t), max(t)
    changes = sorted(
        (p["t_phone"], p["name"] == "app_background")
        for p in packets
        if p.get("type") == "event" and p.get("name") in ("app_background", "app_foreground")
    )
    # A first event of app_foreground means the app was already in the background at Start
    # (e.g. started from the Watch with the phone locked).
    background, since = 0.0, (start if changes and not changes[0][1] else None)
    for at, entering in changes:
        if entering and since is None:
            since = at
        elif not entering and since is not None:
            background += max(0.0, min(at, end) - max(since, start))
            since = None
    if since is not None:
        background += max(0.0, end - max(since, start))
    return round(background / (end - start), 3)


def airpods_rate_around_speech(packets, window_s=3.0):
    """AirPods samples/s in the window after each spoken phrase vs. the whole session."""
    t = np.sort(
        [
            s[0]
            for p in packets
            if p.get("type") == "imu" and p.get("device") == "airpods"
            for s in p["s"]
        ]
    )
    prompts = [p for p in packets if p.get("type") == "event" and p.get("name") == "prompt"]
    if len(t) < 100 or not prompts:
        return None
    overall = (len(t) - 1) / (t[-1] - t[0])
    rates = []
    for p in prompts:
        start = p.get("start", p.get("t_phone"))
        if start is None:
            continue
        n = np.count_nonzero((t >= start) & (t < start + window_s))
        rates.append(n / window_s)
    if not rates:
        return None
    worst = min(rates)
    return {
        "normal_hz": round(overall, 1),
        "worst_after_speech_hz": round(worst, 1),
        "phrases": len(rates),
    }


def high_rate_check(session: Path, journal):
    """Rates from the high-rate chunks the phone journalled (files the ingest rejects are left out)."""
    names = {
        Path(e["file"]).name
        for e in journal
        if e.get("j") == "chunk_received" and e.get("kind") == "hf"
    }
    chunks = sorted(p for p in (session / "watch_hf").glob("*.bin") if p.name in names)
    if not chunks:
        return None
    t = {"accel": [], "motion": []}
    for path in chunks:
        c = read_high_rate(path)
        t["accel"] += list(c.accel[:, 0])
        t["motion"] += list(c.motion[:, 0])
    out = {}
    for kind, times in t.items():
        times = np.sort(times)
        out[kind] = round((len(times) - 1) / (times[-1] - times[0]), 1) if len(times) > 1 else 0.0
    return out


def battery_used(journal):
    health = [e for e in journal if e.get("j") == "health"]
    used = {}
    for key in ("battery_phone", "battery_watch"):
        levels = [e[key] for e in health if key in e]
        if len(levels) >= 2:
            minutes = (health[-1]["unix"] - health[0]["unix"]) / 60
            used[key.replace("battery_", "")] = {
                "percent": round((levels[0] - levels[-1]) * 100, 1),
                "minutes": round(minutes, 1),
            }
    return used


def check(session: Path, phone_only=False) -> dict:
    report = ingest(session, phone_only=phone_only)
    packets, _ = read_jsonl(session / "stream.jsonl")
    journal, _ = read_jsonl(session / "journal.jsonl")
    results = {}
    for name in ("phone", "airpods"):
        streams = [
            s for s in report["streams"].values() if s["device"] == name and s.get("planned", True)
        ]
        if streams:
            coverage = min(s["coverage"] for s in streams)
            results[f"{name}_coverage"] = {"value": coverage, "pass": coverage >= MIN_COVERAGE}
    locked = locked_fraction(packets)
    results["phone_locked"] = {"fraction": locked, "pass": locked >= MIN_LOCKED_FRACTION}
    airpods_planned = any(
        s["device"] == "airpods" and s.get("planned", True) for s in report["streams"].values()
    )
    speech = airpods_rate_around_speech(packets) if airpods_planned else None
    if speech:
        ok = speech["worst_after_speech_hz"] >= (1 - SPEECH_RATE_TOLERANCE) * speech["normal_hz"]
        results["airpods_during_speech"] = speech | {"pass": bool(ok)}
    rates = high_rate_check(session, journal)
    if rates:
        ok = all(rates[k] >= 0.95 * HIGH_RATE[k] for k in HIGH_RATE)
        results["watch_high_rate_hz"] = rates | {"pass": bool(ok)}
    results["battery_used"] = battery_used(journal)
    results["ingest"] = {"status": report["status"], "pass": report["status"] == "PASS"}
    results["T6"] = (
        "PASS"
        if all(v.get("pass", True) for v in results.values() if isinstance(v, dict))
        else "FAIL"
    )
    (session / "device_check.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("session", type=Path)
    parser.add_argument("--phone-only", action="store_true")
    args = parser.parse_args(argv)
    results = check(args.session, args.phone_only)
    print(json.dumps(results, indent=2))
    return 0 if results["T6"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
