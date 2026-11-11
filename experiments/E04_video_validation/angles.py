"""Joint angles from video (Apple Vision 3D) and IMU (SMPL) poses, and how well they agree.

Angles are computed the same way from both joint sets, from 3D joint positions only, so they do
not depend on either system's world frame:
- elbow / knee flexion: 0° straight, 90° at a right angle;
- shoulder elevation: angle between the upper arm and the trunk's downward axis (0° arm down,
  90° arm out to the side or front).
"""

import numpy as np

# SMPL joint indices (MobilePoser output) for the common names.
SMPL_INDEX = {
    "root": 0, "l_hip": 1, "r_hip": 2, "l_knee": 4, "r_knee": 5, "l_ankle": 7, "r_ankle": 8,
    "neck": 12, "l_shoulder": 16, "r_shoulder": 17, "l_elbow": 18, "r_elbow": 19,
    "l_wrist": 20, "r_wrist": 21,
}  # fmt: skip

# Apple Vision 3D joint names (VNHumanBodyPose3DObservation) for the same common names.
VISION_NAMES = {
    "human_root_3D": "root", "human_center_shoulder_3D": "neck",
    "human_left_hip_3D": "l_hip", "human_right_hip_3D": "r_hip",
    "human_left_knee_3D": "l_knee", "human_right_knee_3D": "r_knee",
    "human_left_ankle_3D": "l_ankle", "human_right_ankle_3D": "r_ankle",
    "human_left_shoulder_3D": "l_shoulder", "human_right_shoulder_3D": "r_shoulder",
    "human_left_elbow_3D": "l_elbow", "human_right_elbow_3D": "r_elbow",
    "human_left_wrist_3D": "l_wrist", "human_right_wrist_3D": "r_wrist",
}  # fmt: skip

ANGLES = ("r_elbow", "l_elbow", "r_knee", "l_knee", "r_shoulder", "l_shoulder")


def _angle(u, v):
    cos = np.sum(u * v, axis=-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1))
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def flexion(a, b, c):
    """Flexion at joint b of the chain a-b-c: 0° when straight."""
    return 180 - _angle(a - b, c - b)


def elevation(shoulder, elbow, neck, root):
    """Upper arm vs the trunk's downward axis (neck -> root)."""
    return _angle(elbow - shoulder, root - neck)


def angles(j: dict) -> dict:
    """Common-name joints {name: (n, 3)} -> {angle name: (n,) degrees}."""
    out = {}
    for s in ("r", "l"):
        out[f"{s}_elbow"] = flexion(j[f"{s}_shoulder"], j[f"{s}_elbow"], j[f"{s}_wrist"])
        out[f"{s}_knee"] = flexion(j[f"{s}_hip"], j[f"{s}_knee"], j[f"{s}_ankle"])
        out[f"{s}_shoulder"] = elevation(j[f"{s}_shoulder"], j[f"{s}_elbow"], j["neck"], j["root"])
    return out


def smpl_joints(joints: np.ndarray) -> dict:
    """(n, 24, 3) SMPL joints -> common names."""
    return {name: joints[:, i] for name, i in SMPL_INDEX.items()}


def _swap_sides(name: str) -> str:
    if name.startswith("l_"):
        return "r_" + name[2:]
    if name.startswith("r_"):
        return "l_" + name[2:]
    return name


def vision_joints(frames: list, mirrored: bool):
    """Vision frames -> (t, common-name joints). Only frames with every needed joint are kept.
    A mirrored video (Photo Booth's default) shows the left side as the right: swap the names."""
    keep = [f for f in frames if all(n in f["joints"] for n in VISION_NAMES)]
    t = np.array([f["t"] for f in keep])
    joints = {}
    for vname, name in VISION_NAMES.items():
        key = _swap_sides(name) if mirrored else name
        joints[key] = np.array([f["joints"][vname] for f in keep], float).reshape(-1, 3)
    return t, joints


def to_video_time(t_after_start, start_unix: float, alignment: dict):
    """Seconds after IMU Start -> seconds into the video (alignment.json's rule)."""
    return (
        t_after_start + start_unix - alignment["video_start_unix_metadata"] + alignment["offset_s"]
    )


def compare(t_video, video, t_imu, imu) -> dict:
    """IMU angle interpolated at the video frames that fall inside the IMU span."""
    t_video, video = np.asarray(t_video), np.asarray(video)
    inside = (t_video >= t_imu[0]) & (t_video <= t_imu[-1])
    if inside.sum() < 3:
        return {"n": 0}
    v = video[inside]
    i = np.interp(t_video[inside], t_imu, imu)
    d = i - v
    return {
        "n": int(inside.sum()),
        "bias_deg": round(float(d.mean()), 2),
        "rmse_deg": round(float(np.sqrt(np.mean(d**2))), 2),
        "mae_deg": round(float(np.abs(d).mean()), 2),
        "r": round(float(np.corrcoef(v, i)[0, 1]), 3) if v.std() > 0 and i.std() > 0 else None,
    }


def best_lag(t_video, video, t_imu, imu, search_s=1.0, step=0.02) -> float:
    """Shift (s) to add to IMU times that best correlates the two angle series."""
    best = (-np.inf, 0.0)
    for lag in np.arange(-search_s, search_s + step / 2, step):
        inside = (t_video >= t_imu[0] + lag) & (t_video <= t_imu[-1] + lag)
        if inside.sum() < 10:
            continue
        i = np.interp(t_video[inside], t_imu + lag, imu)
        r = np.corrcoef(video[inside], i)[0, 1]
        if r > best[0]:
            best = (r, float(lag))
    return round(best[1], 2)
