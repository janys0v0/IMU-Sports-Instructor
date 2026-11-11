"""Stream statistics and the session check, shared with the app.

The same rules run in Swift (MotionStreamerCore/Quality) and here; both read
quality_thresholds.json, and the contract fixtures in tests/fixtures/contract/ keep them identical
(test S4).
"""

import json
from dataclasses import asdict, dataclass

import numpy as np

from pipeline.paths import THRESHOLDS


def thresholds() -> dict:
    return json.loads(THRESHOLDS.read_text())


@dataclass
class StreamStats:
    samples: int = 0
    duplicates: int = 0
    missing_from_index: int = 0
    backwards_timestamps: int = 0
    delivered_hz: float = 0.0
    expected_at_delivered_rate: int = 0
    coverage: float = 0.0
    gaps_over_threshold: int = 0
    longest_gap_ms: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def stream_stats(items, window=None, gap_s=None) -> StreamStats:
    """items: (index, t) for every received sample in arrival order, duplicates included.
    window: (t0, t1) the stream should cover; defaults to first -> last sample."""
    gap_s = thresholds()["gap_s"] if gap_s is None else gap_s
    st = StreamStats()
    if not items:
        return st
    order = sorted(range(len(items)), key=lambda k: (items[k][0], k))
    unique = []
    for k in order:
        if unique and unique[-1][0] == items[k][0]:
            st.duplicates += 1
        else:
            unique.append(items[k])
    first, last = unique[0], unique[-1]
    st.missing_from_index = (last[0] - first[0] + 1) - len(unique)
    t0, t1 = window if window is not None else (first[1], last[1])
    inside = [u for u in unique if t0 <= u[1] <= t1]
    st.samples = len(inside)
    dt = np.diff([u[1] for u in inside]) * 1000
    st.backwards_timestamps = int((dt < 0).sum())
    if len(dt) == 0:
        return st
    st.delivered_hz = round(1000 / float(np.median(dt)), 2)
    st.expected_at_delivered_rate = int(round((t1 - t0) * float(np.median(1000 / dt))))
    if st.expected_at_delivered_rate:
        st.coverage = round(st.samples / st.expected_at_delivered_rate, 4)
    gaps = dt[dt > gap_s * 1000]
    st.gaps_over_threshold = len(gaps)
    st.longest_gap_ms = round(float(gaps.max() if len(gaps) else dt.max()), 1)
    return st


def stream_verdict(stats: StreamStats, device: str) -> str:
    """PASS / WARN / FAIL for one stream (design §6, session check)."""
    t = thresholds()["session_check"]
    airpods = device == "airpods"
    pass_cov = t["airpods_pass_min_coverage"] if airpods else t["pass_min_coverage"]
    warn_cov = t["airpods_warn_min_coverage"] if airpods else t["warn_min_coverage"]
    longest_s = stats.longest_gap_ms / 1000
    if stats.samples == 0:
        return "FAIL"
    if stats.coverage >= pass_cov and longest_s <= t["max_gap_s_pass"]:
        return "PASS"
    if stats.coverage >= warn_cov and longest_s <= t["max_gap_s_warn"]:
        return "WARN"
    return "FAIL"


def worst(verdicts) -> str:
    order = ["PASS", "WARN", "PENDING", "FAIL"]
    return max(verdicts, key=order.index, default="PASS")
