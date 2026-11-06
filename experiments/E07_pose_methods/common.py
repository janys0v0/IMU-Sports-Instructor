"""E07 method contract and shared geometry.

Every method writes results/<player>/method_<name>.npz on the dataset's 30 Hz grid with:
    hum    (n, 3)  right upper arm's long axis (shoulder -> elbow), unit, trunk frame
    fore   (n, 3)  right forearm's long axis (elbow -> wrist), unit, trunk frame
    elbow  (n,)    elbow flexion, degrees (NaN where the method gives none)
    valid  (n,)    bool
Trunk frame = OpenSim convention: x forward, y up, z to the body's right. NaN rows are allowed
(e.g. a method without an upper-arm estimate leaves `hum` NaN).

Frames: every sensor quaternion in the dataset rotates sensor axes into one world frame (x
magnetic north, z up; commercial sensors are turned to magnetic north by E06's heading step).
The body frame is fixed at each Calibrate hold from the phone (forward = into the thigh's front,
the pipeline's calibration) and each segment is taken to be aligned with it during the hold
(standing, arms hanging).
"""

from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from .data import OUT, load  # noqa: F401

DOWN = np.array([0.0, -1.0, 0.0])


FORWARD = {}  # (player, segment) -> forward heading (rad) in the Apple world, set by set_forward()


def set_forward(d, player, mode="thigh"):
    """Body forward per segment. "screen": the pipeline's rule (into the pocket phone's screen,
    wrong when the phone sits turned in the pocket). "thigh": the mean horizontal lean of the
    thigh's long axis while it is tilted > 15 deg (the knee goes forward in ready stance, crouches
    and lunges), independent of how the phone sits."""
    FORWARD.clear()
    if mode == "screen":
        return
    for k in np.unique(d["seg"]):
        m = d["seg"] == k
        Rh = Rotation.from_quat(d["phone_hold_quat"][k]).as_matrix()
        a = Rh.T @ np.array([0.0, 0.0, -1.0])
        v = Rotation.from_quat(d["phone_quat"][m]).as_matrix() @ a
        tilt = np.degrees(np.arccos(np.clip(-v[:, 2], -1, 1)))
        h = v[tilt > 15, :2].sum(0)
        FORWARD[(player, int(k))] = float(np.arctan2(h[1], h[0]))


def body_basis(phone_hold_quat, pocket_screen="leg", key=None):
    """World <- body (columns: forward, up, right) at a hold."""
    R_IS = Rotation.from_quat(phone_hold_quat).as_matrix()
    normal = R_IS @ np.array([0.0, 0.0, 1.0])
    fwd = -normal if pocket_screen == "leg" else normal
    if key in FORWARD:
        fwd = np.array([np.cos(FORWARD[key]), np.sin(FORWARD[key]), 0.0])
    up = np.array([0.0, 0.0, 1.0])
    fwd = fwd - up * fwd.dot(up)
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    return np.stack([fwd, up, right], 1)


def segment_rot(d, dev):
    """World <- segment rotations (n, 3, 3) for a device: the sensor's orientation times the
    sensor-to-segment rotation from its segment's hold (segment = body frame during the hold)."""
    R = Rotation.from_quat(d[f"{dev}_quat"]).as_matrix()
    out = np.empty_like(R)
    for k in np.unique(d["seg"]):
        m = d["seg"] == k
        B = body_basis(d["phone_hold_quat"][k], key=(str(d.get("player", "")), int(k)))
        s2b = Rotation.from_quat(d[f"{dev}_hold_quat"][k]).as_matrix().T @ B
        out[m] = R[m] @ s2b
    return out


def static_trunk(d):
    """The body frame of each segment's hold, as if the trunk never turned (Apple-only fallback)."""
    out = np.empty((len(d["t"]), 3, 3))
    for k in np.unique(d["seg"]):
        out[d["seg"] == k] = body_basis(
            d["phone_hold_quat"][k], key=(str(d.get("player", "")), int(k))
        )
    return out


def in_trunk(R_trunk, R_seg, axis=DOWN):
    """A segment axis (segment frame) in the trunk frame."""
    v = np.einsum("nji,njk,k->ni", R_trunk, R_seg, axis)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def angle_between(a, b):
    return np.degrees(np.arccos(np.clip(np.sum(a * b, -1), -1, 1)))


def elbow_from_dirs(hum, fore):
    return angle_between(hum, fore)


def save(player, name, hum, fore, elbow=None, valid=None, **extra):
    elbow = elbow_from_dirs(hum, fore) if elbow is None else elbow
    valid = np.isfinite(fore).all(1) if valid is None else valid
    path = OUT / player / f"method_{name}.npz"
    np.savez_compressed(path, hum=hum, fore=fore, elbow=elbow, valid=valid, **extra)
    return path


def methods(player):
    return sorted(p.stem[len("method_") :] for p in (OUT / player).glob("method_*.npz"))


def load_method(player, name):
    z = np.load(OUT / player / f"method_{name}.npz", allow_pickle=True)
    return {k: z[k] for k in z.files}


__all__ = [
    "Path",
    "body_basis",
    "segment_rot",
    "static_trunk",
    "in_trunk",
    "angle_between",
    "save",
    "methods",
    "load_method",
    "load",
    "OUT",
]
