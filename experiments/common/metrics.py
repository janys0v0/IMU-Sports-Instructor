"""Model-agnostic metrics: anything that yields SMPL global rotations and joint positions
(common.mobileposer_runner.Output or an equivalent) can be scored against a session.

There is no optical ground truth, so two kinds of reference are used:
- Sensor-observed bones: each calibrated device measures the orientation of the bone it is
  strapped to (forearm, thigh, head). The model's global rotation of that joint is compared with
  it, whether or not the device was given to the model.
- Annotated activities (annotations/<session>.json): repetition counts and the motion each
  activity should produce (arms overhead, knee flexion, head yaw).
"""

import json

import numpy as np
from scipy.signal import find_peaks

from . import paths
from .session import SENSOR_JOINT, Session

FPS = 30.0
# SMPL joints
PELVIS, HEAD = 0, 15
HIP = {"left": 1, "right": 2}
KNEE = {"left": 4, "right": 5}
ANKLE = {"left": 7, "right": 8}
WRIST = {"left": 20, "right": 21}


def load_annotation(session_name):
    path = paths.ANNOTATIONS / f"{session_name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def reference(session: Session, n=None):
    """Each device's sensor orientation over all segments, first n frames: loc -> (ori, valid)."""
    out = {}
    for loc in session.locs:
        out[loc] = (
            np.concatenate([s.devices[loc].ori for s in session.segments])[:n],
            np.concatenate([s.devices[loc].valid for s in session.segments])[:n],
        )
    return out


def angle_deg(Ra, Rb):
    """Geodesic angle between rotation matrices, degrees."""
    c = (np.trace(np.swapaxes(Ra, -1, -2) @ Rb, axis1=-2, axis2=-1) - 1) / 2
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def yaw_deg(R):
    """Heading of a bone's forward (z) axis in the body frame; + = toward the subject's left."""
    f = R[..., :, 2]
    return np.degrees(np.arctan2(f[..., 0], f[..., 2]))


def knee_flexion_deg(joints, side):
    u = joints[:, HIP[side]] - joints[:, KNEE[side]]
    v = joints[:, ANKLE[side]] - joints[:, KNEE[side]]
    c = np.sum(u * v, 1) / np.linalg.norm(u, axis=1) / np.linalg.norm(v, axis=1)
    return 180 - np.degrees(np.arccos(np.clip(c, -1, 1)))


def wrist_height_m(joints, side):
    return joints[:, WRIST[side], 1] - joints[:, PELVIS, 1]


def signals(out, ref):
    """Named time series used by the metrics and the plots."""
    sig = {
        "t": out.t,
        "wrist_height_right": wrist_height_m(out.joints, "right"),
        "wrist_height_left": wrist_height_m(out.joints, "left"),
        "knee_flexion_right": knee_flexion_deg(out.joints, "right"),
        "knee_flexion_left": knee_flexion_deg(out.joints, "left"),
        "head_yaw_model": yaw_deg(out.glb[:, HEAD]),
    }
    if "head" in ref:
        sig["head_yaw_airpods"] = yaw_deg(ref["head"][0])
    for loc, (ori, _) in ref.items():
        sig[f"orientation_error_{loc}"] = angle_deg(out.glb[:, SENSOR_JOINT[loc]], ori)
    return sig


def _window(t, a):
    return (t >= a["start"]) & (t <= a["end"])


def _peaks(x, height, prominence):
    idx, _ = find_peaks(x, height=height, prominence=prominence, distance=int(0.6 * FPS))
    return idx


def score(out, session: Session, annotation=None):
    """Metrics dict for one model output on one session."""
    ref = reference(session, len(out.t))
    sig = signals(out, ref)
    t = sig["t"]
    result = {"orientation_error_deg": {}}
    for loc, (_, valid) in ref.items():
        e = sig[f"orientation_error_{loc}"][valid]
        result["orientation_error_deg"][loc] = {
            "mean": round(float(e.mean()), 1),
            "median": round(float(np.median(e)), 1),
        }
    if not annotation:
        return result, sig

    side = annotation.get("watch_side", "right")
    other = "left" if side == "right" else "right"
    acts = {}
    for a in annotation["activities"]:
        w = _window(t, a)
        kind, r = (
            a["type"],
            {"window_s": [a["start"], a["end"]], "reported_reps": a.get("reported_reps")},
        )
        if kind == "standing":
            r.update(
                wrist_height_right_m=round(float(sig["wrist_height_right"][w].mean()), 2),
                wrist_height_left_m=round(float(sig["wrist_height_left"][w].mean()), 2),
            )
        elif kind == "jumping_jacks":
            h = sig[f"wrist_height_{side}"][w]
            pk = _peaks(h, height=0.4, prominence=0.3)
            r.update(
                detected_reps=len(pk),
                peak_wrist_height_m=round(float(h[pk].mean()), 2) if len(pk) else None,
                peak_other_wrist_height_m=round(
                    float(sig[f"wrist_height_{other}"][w][pk].mean()), 2
                )
                if len(pk)
                else None,
            )
        elif kind == "squats":
            k = (sig["knee_flexion_right"][w] + sig["knee_flexion_left"][w]) / 2
            pk = _peaks(k, height=60, prominence=30)
            r.update(
                detected_reps=len(pk),
                peak_knee_flexion_deg=round(float(k[pk].mean()), 1) if len(pk) else None,
            )
        elif kind == "head_turns" and "head_yaw_airpods" in sig:
            m, s = sig["head_yaw_model"][w], sig["head_yaw_airpods"][w]
            r.update(
                airpods_left_deg=round(float(s.max()), 1),
                model_left_deg=round(float(m.max()), 1),
                airpods_right_deg=round(float(s.min()), 1),
                model_right_deg=round(float(m.min()), 1),
                yaw_rmse_deg=round(float(np.sqrt(np.mean((m - s) ** 2))), 1),
            )
        for loc in ref:
            e = sig[f"orientation_error_{loc}"][w]
            r.setdefault("orientation_error_deg", {})[loc] = round(float(e.mean()), 1)
        acts[a["name"]] = r
    result["activities"] = acts
    return result, sig
