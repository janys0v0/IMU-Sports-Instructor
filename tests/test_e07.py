"""E07: arm-pose method comparison — the shared geometry and the model-free methods."""

import numpy as np
import pytest
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
    pytest.importorskip("torch")  # CI installs numpy and scipy only
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


def test_position_errors_use_opencap_arm_lengths():
    from experiments.E07_pose_methods.evaluate import arm_lengths, position_errors

    n = 60
    mk = np.zeros((n, 20, 3))
    mk[:, 2] = [0, -0.25, 0]  # RElbow 25 cm below RShoulder (index 1, at origin)
    mk[:, 3] = [0, -0.47, 0]  # RWrist 22 cm below the elbow
    valid = np.ones(n, bool)
    assert np.allclose(arm_lengths(mk, valid), [0.25, 0.22])
    down = np.tile([0, -1.0, 0], (n, 1))
    fwd = np.tile([1.0, 0, 0], (n, 1))
    elbow, wrist = position_errors(down, fwd, down, down, (0.25, 0.22))
    assert np.allclose(elbow, 0) and np.allclose(wrist, 22 * np.sqrt(2))  # forearm 90 deg off


def test_hits_need_an_impact_and_a_fast_arm():
    from experiments.E07_pose_methods.data import hits

    fs_a, fs_m = 800.0, 200.0
    ta = np.arange(0, 20, 1 / fs_a)
    tm = np.arange(0, 20, 1 / fs_m)
    acc = np.zeros((len(ta), 3))
    acc[:, 1] = -1.0  # gravity, in g
    w = np.full(len(tm), 1.0)
    for t0, impact, spin in ((5.0, 8.0, 20.0), (10.0, 8.0, 2.0), (15.0, 0.0, 20.0)):
        k = np.searchsorted(ta, t0)
        acc[k : k + 8, 0] += impact * np.sin(np.arange(8) * np.pi / 2)  # 200 Hz ring
        w[np.abs(tm - t0) < 0.1] = spin
    out = hits(ta, acc, tm, w)
    # only the stroke: impact + fast arm; not a tap (slow arm) nor a shadow swing (no impact)
    assert len(out) == 1 and abs(out[0] - 5.0) < 0.01


def test_figures_show_players_anonymously():
    matplotlib = pytest.importorskip("matplotlib")  # CI installs no plotting

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from experiments.E07_pose_methods.colors import anonymize

    fig, ax = plt.subplots()
    ax.set_title("Janys 10/28 vs Tom; tom and janys's; bottom")
    ax.bar([0], [1], label="trained on Janys + Tom")
    ax.legend()
    ax.set_xticks([0])
    ax.set_xticklabels(["Tom 10/28"])
    fig.suptitle("Janys")
    anonymize(fig)
    texts = [t.get_text() for t in fig.findobj(matplotlib.text.Text)]
    assert ax.get_title() == "Player A 10/28 vs Player B; Player B and Player A's; bottom"
    assert "trained on Player A + Player B" in texts and "Player B 10/28" in texts
    assert not any("Janys" in t or "Tom" in t for t in texts)
    plt.close(fig)
