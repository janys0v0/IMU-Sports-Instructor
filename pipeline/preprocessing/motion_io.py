"""Load MotionStreamer recordings into per-device arrays.

Accepts a session folder containing `mac_stream.jsonl` (written by the Mac receiver)
or `stream.jsonl` (saved on the iPhone), or a path to either file.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# MobilePoser input slots (config.amass.combos): 0 left wrist, 1 right wrist,
# 2 left thigh/pocket, 3 right thigh/pocket, 4 head.
SLOTS = {"left_wrist": 0, "right_wrist": 1, "left_pocket": 2, "right_pocket": 3, "head": 4}


@dataclass
class DeviceStream:
    """One device's samples, sorted by device time, duplicates removed."""

    device: str
    loc: str
    t: np.ndarray  # CMDeviceMotion.timestamp, s since that device booted
    quat: np.ndarray  # (N, 4) x, y, z, w; rotates device axes into the reference frame
    user_acc: np.ndarray  # (N, 3) in g, device frame. Apple sign: minus physical acceleration
    gravity: np.ndarray  # (N, 3) in g, device frame (points down)
    rot_rate: np.ndarray  # (N, 3) rad/s, device frame
    boot_to_unix: float
    ref_frame: str

    @property
    def rate_hz(self):
        return 1.0 / float(np.median(np.diff(self.t)))

    def window(self, t0, t1):
        return (self.t >= t0) & (self.t <= t1)


@dataclass
class Recording:
    session: str
    path: Path
    streams: dict  # loc -> DeviceStream
    events: list = field(default_factory=list)
    syncs: list = field(default_factory=list)

    def last_event(self, name):
        matches = [e for e in self.events if e.get("name") == name]
        return matches[-1] if matches else None

    def setting(self, key, default=None):
        """Latest value of a setting carried on events (e.g. pocket_screen)."""
        for event in reversed(self.events):
            if key in event:
                return event[key]
        return default


def load_recording(path) -> Recording:
    path = Path(path)
    if path.is_dir():
        for name in ("mac_stream.jsonl", "stream.jsonl"):
            if (path / name).exists():
                path = path / name
                break
        else:
            raise FileNotFoundError(f"No mac_stream.jsonl or stream.jsonl in {path}")

    samples, meta, events, syncs, session = {}, {}, [], [], None
    with open(path) as f:
        for line in f:
            packet = json.loads(line)
            session = session or packet.get("session")
            kind = packet.get("type")
            if kind == "imu":
                loc = packet["loc"]
                samples.setdefault(loc, []).extend(packet["s"])
                meta.setdefault(loc, packet)
            elif kind == "event":
                events.append(packet)
            elif kind == "sync":
                syncs.append(packet)

    streams = {}
    for loc, rows in samples.items():
        arr = np.asarray(rows, dtype=float)
        arr = arr[np.argsort(arr[:, 0], kind="stable")]
        keep = np.concatenate([[True], np.diff(arr[:, 0]) > 1e-6])  # drop retried duplicates
        arr = arr[keep]
        m = meta[loc]
        streams[loc] = DeviceStream(
            device=m["device"],
            loc=loc,
            t=arr[:, 0],
            quat=arr[:, 1:5],
            user_acc=arr[:, 5:8],
            gravity=arr[:, 8:11],
            rot_rate=arr[:, 11:14],
            boot_to_unix=m.get("boot_to_unix", 0.0),
            ref_frame=m.get("ref_frame", ""),
        )
    events.sort(key=lambda e: e.get("t_phone", 0))
    return Recording(session=session, path=path, streams=streams, events=events, syncs=syncs)
