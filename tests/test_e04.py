"""Stage 11 (E04): joint angles from video and IMU poses, alignment and agreement metrics."""

import numpy as np
import pytest

from experiments.E04_video_validation import angles as A


def test_flexion_is_zero_when_straight_and_90_at_a_right_angle():
    a = np.array([[0.0, 1, 0], [0.0, 1, 0]])
    b = np.zeros((2, 3))
    c = np.array([[0.0, -1, 0], [1.0, 0, 0]])
    assert A.flexion(a, b, c) == pytest.approx([0.0, 90.0])


def test_elevation_is_zero_with_the_arm_down_and_90_with_the_arm_out():
    neck = np.array([[0.0, 0.5, 0]] * 2)
    root = np.zeros((2, 3))
    shoulder = np.array([[0.2, 0.5, 0]] * 2)
    elbow = np.array([[0.2, 0.2, 0], [0.5, 0.5, 0]])
    assert A.elevation(shoulder, elbow, neck, root) == pytest.approx([0.0, 90.0])


def _pose(n=3):
    """A standing body with the right arm bent 90° at the elbow (same in both joint sets)."""
    j = {
        "root": [0, 0, 0], "neck": [0, 0.5, 0],
        "r_hip": [-0.1, 0, 0], "r_knee": [-0.1, -0.45, 0], "r_ankle": [-0.1, -0.9, 0],
        "l_hip": [0.1, 0, 0], "l_knee": [0.1, -0.45, 0], "l_ankle": [0.1, -0.9, 0],
        "r_shoulder": [-0.2, 0.5, 0], "r_elbow": [-0.2, 0.2, 0], "r_wrist": [-0.2, 0.2, 0.3],
        "l_shoulder": [0.2, 0.5, 0], "l_elbow": [0.2, 0.2, 0], "l_wrist": [0.2, -0.1, 0],
    }  # fmt: skip
    return {k: np.tile(np.array(v, float), (n, 1)) for k, v in j.items()}


def test_angle_set_from_common_joints():
    ang = A.angles(_pose())
    assert set(ang) == set(A.ANGLES)
    assert ang["r_elbow"] == pytest.approx([90.0] * 3)
    assert ang["l_elbow"] == pytest.approx([0.0] * 3)
    assert ang["r_knee"] == pytest.approx([0.0] * 3)
    assert ang["r_shoulder"] == pytest.approx([0.0] * 3)


def test_smpl_joints_map_to_the_common_names():
    pose = _pose(2)
    joints = np.zeros((2, 24, 3))
    for name, idx in A.SMPL_INDEX.items():
        joints[:, idx] = pose[name]
    assert A.angles(A.smpl_joints(joints))["r_elbow"] == pytest.approx([90.0, 90.0])


def _vision_frames(pose, t):
    return [
        {"t": float(ti), "joints": {v: pose[c][i].tolist() for v, c in A.VISION_NAMES.items()}}
        for i, ti in enumerate(t)
    ]


def test_vision_frames_load_and_a_mirrored_video_swaps_sides():
    frames = _vision_frames(_pose(3), [0.0, 0.1, 0.2])
    t, joints = A.vision_joints(frames, mirrored=False)
    assert t == pytest.approx([0.0, 0.1, 0.2])
    assert A.angles(joints)["r_elbow"] == pytest.approx([90.0] * 3)
    _, flipped = A.vision_joints(frames, mirrored=True)
    assert A.angles(flipped)["l_elbow"] == pytest.approx([90.0] * 3)


def test_imu_time_maps_to_video_time_with_the_saved_offset():
    alignment = {"video_start_unix_metadata": 1000.0, "offset_s": -0.85}
    assert A.to_video_time(np.array([0.0, 10.0]), 1019.02, alignment) == pytest.approx(
        [18.17, 28.17]
    )


def test_compare_reports_bias_rmse_and_correlation_on_overlap_only():
    t_video = np.arange(0, 10, 0.1)
    video = 30 + 20 * np.sin(t_video)
    t_imu = np.arange(2, 8, 1 / 30)
    imu = 30 + 20 * np.sin(t_imu) + 5  # 5° offset
    m = A.compare(t_video, video, t_imu, imu)
    assert m["n"] == np.count_nonzero((t_video >= 2) & (t_video <= t_imu[-1]))
    assert m["bias_deg"] == pytest.approx(5, abs=0.05)
    assert m["rmse_deg"] == pytest.approx(5, abs=0.05)
    assert m["r"] == pytest.approx(1, abs=1e-3)


def test_compare_with_no_overlap_is_empty():
    m = A.compare(np.arange(0, 1, 0.1), np.zeros(10), np.arange(5, 6, 0.1), np.zeros(10))
    assert m == {"n": 0}


def test_best_lag_recovers_a_shift():
    t = np.arange(0, 60, 1 / 15)
    video = np.sin(t) + np.sin(2.7 * t)
    t_imu = np.arange(0, 60, 1 / 30)
    imu = np.sin(t_imu - 0.3) + np.sin(2.7 * (t_imu - 0.3))  # IMU lags by 0.3 s
    assert A.best_lag(t, video, t_imu, imu, search_s=1.0) == pytest.approx(-0.3, abs=0.04)
