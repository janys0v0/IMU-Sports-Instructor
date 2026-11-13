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


def test_imu_arm_and_arm_scores():
    from experiments.E09_roboflow_pose.compare_imu import arm_scores, imu_arm

    Rt = np.eye(3)
    sh, el, wr = imu_arm(
        np.zeros(3), Rt, np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.0, 0.0]), 0.3, 0.25
    )
    assert np.allclose(el, [0, -0.3, 0]) and np.allclose(wr, [0.25, -0.3, 0])
    g = (np.array([0.0, 0.0]), np.array([0.0, 10.0]), np.array([10.0, 10.0]))
    same = arm_scores(*g, *g)
    assert all(np.isclose(v, 0.0) for v in same.values())
    # forearm pointing straight on instead of turned 90°: wrist 10*sqrt(2) px off, 90° direction error
    s = arm_scores(g[0], g[1], np.array([0.0, 20.0]), *g)
    assert np.isclose(s["wrist_px"], np.hypot(10, 10)) and np.isclose(s["fore_dir_deg"], 90.0)
    assert np.isclose(s["elbow_angle_deg"], 90.0) and np.isclose(s["upper_dir_deg"], 0.0)


def test_ray_sphere_and_camera_rays():
    from experiments.E09_roboflow_pose.lift3d import camera_center_and_rays, ray_sphere

    P = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 5.0]])  # camera at z = -5 looking +z
    C, d = camera_center_and_rays(P, np.array([[0.0, 0.0]]))
    assert np.allclose(C, [0, 0, -5]) and np.allclose(d[0], [0, 0, 1])
    two = ray_sphere(C, d[0], np.zeros(3), 1.0)  # through the centre: front and back of the sphere
    assert np.allclose(two[0], [0, 0, -1]) and np.allclose(two[1], [0, 0, 1])
    one = ray_sphere(C, np.array([0.0, 0.6, 0.8]), np.array([0.0, 0.0, 0.0]), 0.1)  # misses
    assert len(one) == 1 and np.isclose(np.linalg.norm(one[0] - C), 4.0)  # nearest point on the ray


def test_viterbi_follows_the_smooth_branch():
    from experiments.E09_roboflow_pose.lift3d import viterbi

    a, b = np.zeros(3), np.array([0.0, 0.0, 1.0])
    # two branches per frame, swapped in order at frame 2; the smooth path stays near `a`
    cands = [[(a, a), (b, b)], [(a, a), (b, b)], [(b, b), (a, a)], []]
    unary = [[0.0, 0.1], [0.0, 0.0], [0.0, 0.0], []]
    assert viterbi(cands, unary) == [0, 0, 1, None]
