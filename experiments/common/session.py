"""Load a recording as calibrated, body-frame inputs per device, ready for any pose model.

Same calibration as the live viewer and live/render_session.py: each Calibrate event starts a
segment; the phone sets the body heading, the Watch reuses it (clock mapped through
boot_to_unix), the AirPods use their own forward axis. Devices are kept separate so an
experiment can choose which ones a model sees, while every device stays available as a
reference signal.
"""

from dataclasses import dataclass, field

import numpy as np

from pipeline.live.live_viewer import calibrate_shared
from pipeline.pose.render_session import MIN_DEVICE_COVERAGE, segments
from pipeline.preprocessing.calibration import AIRPODS_FORWARD, calibrate, to_body
from pipeline.preprocessing.motion_io import SLOTS, load_recording
from pipeline.preprocessing.resample import MODEL_FPS, resample

from . import paths

# SMPL joint whose global rotation each sensor location follows (MobilePoser amass.joint_sets).
SENSOR_JOINT = {
    "left_wrist": 18,
    "right_wrist": 19,
    "left_pocket": 1,
    "right_pocket": 2,
    "head": 15,
}
SHORT = {
    "left_wrist": "lw",
    "right_wrist": "rw",
    "left_pocket": "lp",
    "right_pocket": "rp",
    "head": "h",
}


@dataclass
class Device:
    loc: str
    acc: np.ndarray  # (n, 3) body-frame acceleration, m/s^2
    ori: np.ndarray  # (n, 3, 3) bone orientation in the body frame
    valid: np.ndarray  # (n,) False inside sensor gaps
    passed: bool  # calibration check (still during the hold)
    rot_rate: np.ndarray = None  # (n, 3) device-frame rotation rate, rad/s


@dataclass
class Segment:
    t: np.ndarray  # (n,) seconds after Start, 30 Hz
    devices: dict = field(default_factory=dict)  # loc -> Device


@dataclass
class Session:
    name: str
    phone_loc: str
    segments: list

    @property
    def locs(self):
        """Device locations present in every segment."""
        return sorted(set.intersection(*(set(s.devices) for s in self.segments)))


def load_session(session, rate=MODEL_FPS) -> Session:
    """Calibrated device inputs resampled at `rate` Hz (MobilePoser: 30, IMUCoCo: 60)."""
    folder = paths.session_dir(session)
    rec = load_recording(folder)
    phone_loc = next(loc for loc, s in rec.streams.items() if s.device == "phone")
    phone = rec.streams[phone_loc]
    screen = rec.setting("pocket_screen", "leg")
    start = rec.last_event("start")["t_phone"] if rec.last_event("start") else phone.t[0]

    out = []
    for hold, t0, t1 in segments(rec, phone):
        cal_p = calibrate(phone, hold, pocket_screen=screen)
        res_p = resample(phone, rate=rate, t_start=t0, t_end=t1)
        acc, ori = to_body(cal_p, res_p)
        devices = {
            phone_loc: Device(
                phone_loc, acc, ori, res_p.valid, cal_p.checks["passed"], res_p.rot_rate
            )
        }
        n = len(res_p.t)
        for loc, stream in rec.streams.items():
            if loc == phone_loc or loc not in SLOTS:
                continue
            shift = phone.boot_to_unix - stream.boot_to_unix if stream.device == "watch" else 0.0
            window = (hold[0] + shift, hold[1] + shift)
            try:
                if loc == "head":
                    cal = calibrate(stream, window, forward_device=AIRPODS_FORWARD)
                elif stream.ref_frame == phone.ref_frame:
                    cal = calibrate_shared(stream, window, cal_p.R_MI)
                else:
                    continue
            except ValueError:
                continue  # no samples in the calibration hold
            res = resample(stream, rate=rate, t_start=t0 + shift, t_end=t1 + shift)
            if len(res.t) < MIN_DEVICE_COVERAGE * n or res.valid.mean() < MIN_DEVICE_COVERAGE:
                continue
            a, o = to_body(cal, res)
            devices[loc] = Device(loc, a, o, res.valid, cal.checks["passed"], res.rot_rate)
        n = min(len(d.acc) for d in devices.values())
        for d in devices.values():
            d.acc, d.ori, d.valid, d.rot_rate = d.acc[:n], d.ori[:n], d.valid[:n], d.rot_rate[:n]
        out.append(Segment(t=res_p.t[:n] - start, devices=devices))
    if not out:
        raise ValueError(f"{folder.name}: no calibrated segment")
    return Session(folder.name, phone_loc, out)


__all__ = [
    "Device",
    "Segment",
    "Session",
    "load_session",
    "SENSOR_JOINT",
    "SHORT",
    "SLOTS",
    "MODEL_FPS",
]
