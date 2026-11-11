"""Writes the S4 contract fixtures: synthetic streams with their expected stats and verdicts.

Run once when the rules change: .venv/bin/python -m tests.fixtures.contract.make_fixtures
Both the Swift tests (QualityContractTests) and tests/test_ingest.py check every fixture.
"""

import json
import random
from pathlib import Path

from pipeline.ingest.quality import stream_stats, stream_verdict

OUT = Path(__file__).parent


def stream(rate, seconds, start=100.0, drop=(), jitter=0.0, seed=1):
    rng = random.Random(seed)
    items = []
    for i in range(int(rate * seconds)):
        t = start + i / rate + (rng.uniform(-jitter, jitter) if jitter else 0.0)
        if not any(a <= t - start < b for a, b in drop):
            items.append([i, round(t, 6)])
    return items


CASES = {
    "clean_phone": ("phone", stream(33.5, 60), None),
    "watch_short_gaps": ("watch", stream(66.4, 60, drop=[(10, 10.3), (40, 40.2)]), None),
    "airpods_93pct": (
        "airpods",
        stream(50, 60, drop=[(5, 6), (20, 21.5), (30, 31), (50, 51)]),
        None,
    ),
    "phone_long_gap": ("phone", stream(33.5, 60, drop=[(20, 23)]), None),
    "window_late_start": ("watch", stream(60, 50, start=105), [100.0, 155.0]),
    "duplicates_and_jitter": (
        "phone",
        stream(60, 30, jitter=0.002) + [[10, 100.0 + 10 / 60]],
        None,
    ),
    "empty": ("phone", [], [0.0, 10.0]),
}

if __name__ == "__main__":
    for name, (device, items, window) in CASES.items():
        stats = stream_stats([tuple(x) for x in items], window=tuple(window) if window else None)
        expected = stats.as_dict() | {"verdict": stream_verdict(stats, device)}
        fixture = {
            "name": name,
            "device": device,
            "window": window,
            "items": items,
            "expected": expected,
        }
        (OUT / f"{name}.json").write_text(json.dumps(fixture, separators=(",", ":")) + "\n")
        print(name, expected["verdict"], expected["coverage"], expected["longest_gap_ms"])
