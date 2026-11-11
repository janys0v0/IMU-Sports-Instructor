"""E07: arm-pose method comparison — the shared geometry and the model-free methods."""

import numpy as np
from scipy.spatial.transform import Rotation


def test_elevation_and_plane_of_simple_arm_directions():
    from experiments.E07_pose_methods.data import elevation_plane

    hum = np.array(
        [[0, -1.0, 0], [1.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]]
    )  # hanging, forward, sideways, up
    el, pl = elevation_plane(hum)
    assert np.allclose(el, [0, 90, 90, 180])
    assert np.allclose(pl[1:3], [0, 90])


def test_segment_axes_in_the_trunk_frame():
    from experiments.E07_pose_methods.common import in_trunk

    Rt = Rotation.from_euler("z", [30.0], degrees=True).as_matrix()  # trunk turned
    Rs = (
        Rt @ Rotation.from_euler("z", [90.0], degrees=True).as_matrix()
    )  # arm raised forward relative to it
    v = in_trunk(Rt, Rs)  # segment -y in trunk frame (x fwd, y up, z right); +90 about z: -y -> +x
    assert np.allclose(v, [[1.0, 0, 0]], atol=1e-9)


def test_constraint_candidates_bend_the_elbow_forward():
    from experiments.E07_pose_methods import constraint as C

    cand = C.candidate_axes()
    th0 = cand[0, len(C.PHI) // 2]  # elbow straight: upper arm along the forearm (down)
    assert np.allclose(th0, [0, -1.0, 0], atol=1e-9)
    i90 = int(np.argmin(np.abs(np.degrees(C.THETA) - 90)))
    up = cand[
        i90, len(C.PHI) // 2
    ]  # 90 deg flexion, neutral twist: upper arm is back along -x in the forearm frame
    assert abs(np.linalg.norm(up) - 1) < 1e-9 and up[0] < -0.99


def test_viterbi_follows_a_moving_minimum():
    from experiments.E07_pose_methods import constraint as C

    n, T, P = 20, len(C.THETA), len(C.PHI)
    cost = np.ones((n, T, P))
    for k in range(n):
        cost[k, min(k // 2, T - 1), P // 2] = 0.0
    path = C.viterbi(cost)
    assert path[-1, 0] == min((n - 1) // 2, T - 1) and (path[:, 1] == P // 2).all()


def test_lowpass_angle_handles_wraparound():
    from experiments.E07_pose_methods.align import lowpass_angle

    a = np.full(600, np.radians(179.0))
    a[::2] = np.radians(-179.0)  # alternating across +-180
    out = np.degrees(lowpass_angle(a))
    assert np.all(np.abs(np.abs(out) - 180) < 2)


def test_gru_predict_is_deterministic():
    from experiments.E07_pose_methods.learned_own import GRU, WIN

    rng = np.random.default_rng(0)
    n = 2 * WIN
    X = rng.normal(size=(n, 4)).astype(np.float32)
    Y = np.tile([0, -1.0, 0, 0, -1.0, 0], (n, 1))
    net = GRU(4, hidden=8).fit(X, Y, np.ones(n, bool), np.zeros(n, int), epochs=1)
    a = net.predict(X, np.zeros(n, int))
    b = net.predict(X, np.zeros(n, int))
    assert np.array_equal(a, b)  # dropout must be off at test time


def test_context_stays_within_segment():
    from experiments.E07_pose_methods.learned_own import context

    X = np.r_[np.zeros((40, 1)), np.full((40, 1), 100.0)]  # two segments, very different values
    seg = np.r_[np.zeros(40, int), np.ones(40, int)]
    c = context(X, seg)
    # columns: value, ±15-frame mean, std; frames next to the boundary must not see the other segment
    assert np.allclose(c[:40, 1:], 0)
    assert np.allclose(c[40:, 1], 100) and np.allclose(c[40:, 2], 0)
