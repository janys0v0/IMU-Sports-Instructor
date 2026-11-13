"""E09: matching a Roboflow detection to OpenCap and scoring its keypoints."""

import numpy as np


def _det(x, y, kps):
    return {
        "x": x,
        "y": y,
        "keypoints": [{"class": c, "confidence": s, "x": u, "y": v} for c, s, u, v in kps],
    }


def test_match_person_picks_the_detection_nearest_the_hip():
    from experiments.E09_roboflow_pose.evaluate import match_person

    far, near = _det(1500, 500, []), _det(610, 520, [])
    assert match_person([far, near], np.array([600.0, 530.0])) is near
    assert match_person([far], np.array([600.0, 530.0])) is None  # someone else on court
    assert match_person([], np.array([600.0, 530.0])) is None


def test_low_confidence_keypoints_count_as_missing():
    from experiments.E09_roboflow_pose.evaluate import keypoints

    kp = keypoints(_det(0, 0, [("right_elbow", 0.9, 10, 20), ("right_wrist", 0.1, 30, 40)]))
    assert set(kp) == {"right_elbow"}
    assert keypoints(None) == {}


def test_frame_errors_pixel_distance_and_elbow_angle():
    from experiments.E09_roboflow_pose.common import JOINTS
    from experiments.E09_roboflow_pose.evaluate import frame_errors

    gt = {o: np.zeros(2) for o in JOINTS}
    gt.update(
        RShoulder=np.array([0.0, 0.0]), RElbow=np.array([0.0, 10.0]), RWrist=np.array([10.0, 10.0])
    )
    # prediction: elbow 3-4-5 px off, wrist straight down instead of 90° out
    kp = {"right_shoulder": np.array([0.0, 0.0]), "right_elbow": np.array([3.0, 14.0]),
          "right_wrist": np.array([3.0, 24.0])}  # fmt: skip
    e = frame_errors(kp, gt)
    assert np.isclose(e["RElbow"], 5.0)
    assert np.isnan(e["LKnee"])
    straight = 180 - np.degrees(np.arctan2(3, 14))  # angle at the predicted elbow
    assert np.isclose(e["elbow_err"], abs(straight - 90.0))
