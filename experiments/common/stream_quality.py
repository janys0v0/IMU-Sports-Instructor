"""Per-device stream quality from the raw packets of a recording (mac_stream.jsonl).

Uses each packet's sample indices (first_index + position) so missing samples are counted
exactly, not inferred from time gaps. All times are put on the phone clock (Watch samples are
mapped through each device's boot_to_unix) and given as seconds after Start.
"""

import json
from dataclasses import dataclass, field

import numpy as np

from . import paths

GAP_S = 0.1  # an inter-sample interval longer than this counts as a gap


@dataclass
class Stream:
    device: str
    loc: str
    requested_hz: float
    t: np.ndarray  # (n,) s after Start, phone clock, sorted by sample index
    index: np.ndarray  # (n,) sample index as sent by the device
    missing_t: np.ndarray  # (m,) estimated times of samples missing from the index sequence
    packet_t: np.ndarray  # (p,) time of each packet's last sample, s after Start
    delay_ms: np.ndarray  # (p,) Mac receive time minus that sample's time (clock offsets included)
    duplicates: int = 0

    @property
    def dt_ms(self):
        return np.diff(self.t) * 1000

    def rolling_hz(self, window_s=1.0, step_s=0.25):
        centers = np.arange(self.t[0] + window_s / 2, self.t[-1] - window_s / 2, step_s)
        counts = np.searchsorted(self.t, centers + window_s / 2) - np.searchsorted(
            self.t, centers - window_s / 2
        )
        return centers, counts / window_s

    def gaps(self, min_s=GAP_S):
        """(start, end) of every interval between consecutive samples longer than min_s."""
        k = np.nonzero(np.diff(self.t) > min_s)[0]
        return list(zip(self.t[k], self.t[k + 1]))

    def summary(self, t0=None, t1=None):
        t0 = self.t[0] if t0 is None else t0
        t1 = self.t[-1] if t1 is None else t1
        w = (self.t >= t0) & (self.t <= t1)
        dt = np.diff(self.t[w]) * 1000
        gaps = [g for g in self.gaps() if g[0] >= t0 and g[1] <= t1]
        expected = int(round((t1 - t0) * float(np.median(1000 / dt))))
        return {
            "requested_hz": self.requested_hz,
            "delivered_hz": round(1000 / float(np.median(dt)), 2),
            "interval_ms_median": round(float(np.median(dt)), 2),
            "interval_ms_p5_p95": [
                round(float(np.percentile(dt, 5)), 2),
                round(float(np.percentile(dt, 95)), 2),
            ],
            "samples": int(w.sum()),
            "expected_at_delivered_rate": expected,
            "coverage": round(int(w.sum()) / expected, 4) if expected else None,
            "missing_from_index": int(((self.missing_t >= t0) & (self.missing_t <= t1)).sum()),
            "duplicates": self.duplicates,
            "gaps_over_100ms": len(gaps),
            "longest_gap_ms": round(
                max([(b - a) * 1000 for a, b in gaps], default=float(dt.max())), 1
            ),
            "delivery_delay_ms_median": round(float(np.median(self.delay_ms)), 1),
        }


@dataclass
class Recording:
    name: str
    start: float  # Start event, phone clock
    events: list = field(default_factory=list)  # (name, s after Start)
    streams: dict = field(default_factory=dict)  # loc -> Stream


def load(session) -> Recording:
    folder = paths.session_dir(session)
    with open(folder / "mac_stream.jsonl") as f:
        packets = [json.loads(line) for line in f]
    # Early recordings (2026-09-30) have no Start event: start at the first phone sample instead.
    start = next(
        (p["t_phone"] for p in packets if p.get("type") == "event" and p.get("name") == "start"),
        None,
    )
    if start is None:
        start = min(
            p["s"][0][0] for p in packets if p.get("type") == "imu" and p.get("device") == "phone"
        )
    phone_boot = next(
        p["boot_to_unix"] for p in packets if p.get("type") == "imu" and p.get("device") == "phone"
    )
    by_loc = {}
    for p in packets:
        if p.get("type") == "imu":
            by_loc.setdefault(p["loc"], []).append(p)
    streams = {}
    for loc, ps in by_loc.items():
        device, boot = ps[0]["device"], ps[0]["boot_to_unix"]
        to_phone = boot - phone_boot if device == "watch" else 0.0  # Watch clock -> phone clock
        idx, t, pt, delay = [], [], [], []
        for p in ps:
            for k, s in enumerate(p["s"]):
                idx.append(p["first_index"] + k)
                t.append(s[0] + to_phone - start)
            last = p["s"][-1][0]
            pt.append(last + to_phone - start)
            delay.append((p["recv_mac_unix"] - (p["boot_to_unix"] + last)) * 1000)
        idx, t = np.asarray(idx), np.asarray(t)
        order = np.argsort(idx, kind="stable")
        idx, t = idx[order], t[order]
        keep = np.concatenate([[True], np.diff(idx) > 0])
        dup = int((~keep).sum())
        idx, t = idx[keep], t[keep]
        missing = np.setdiff1d(np.arange(idx[0], idx[-1] + 1), idx)
        missing_t = np.interp(missing, idx, t)
        streams[loc] = Stream(
            device,
            loc,
            float(ps[0].get("rate_hz", np.nan)),
            t,
            idx,
            missing_t,
            np.asarray(pt),
            np.asarray(delay),
            dup,
        )
    events = [
        (p["name"], p["t_phone"] - start)
        for p in packets
        if p.get("type") == "event" and "t_phone" in p
    ]
    return Recording(folder.name, start, events, streams)
