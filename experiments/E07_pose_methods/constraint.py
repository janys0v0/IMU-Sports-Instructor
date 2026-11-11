"""Physical-constraint arm model from the Watch alone (ArmTrak-style, Shen et al. MobiSys 2016,
without its accelerometer HMM): no learning.

The Watch gives the forearm's full orientation. The elbow is a hinge plus forearm twist, so the
upper arm is the forearm's long axis turned back about the hinge axis by the elbow angle theta,
where the hinge axis (in the Watch's frame) depends on the twist phi. For every frame and every
(theta, phi) on a grid the cost is:
- joint limits: the upper arm cannot point into the trunk, far behind the body, or above 170 deg;
  theta in [0, 150], phi in [-90, 90];
- effort: the arm hangs unless something holds it up (cost grows with shoulder elevation);
- twist: neutral forearm twist is preferred;
- smoothness: theta and phi change little from frame to frame (dynamic programming, Viterbi).
Trunk: the static calibration frame (Apple-only) or the aligned commercial chest sensor.

    .venv/bin/python -m experiments.E07_pose_methods.constraint
"""

import numpy as np

from .common import in_trunk, load, save, set_forward, static_trunk
from .data import PLAYERS

THETA = np.radians(np.arange(0, 151, 10))
PHI = np.radians(np.arange(-90, 91, 15))
W_EFFORT, W_TWIST, W_SMOOTH, W_LIMIT = 1.0, 0.5, 0.6, 10.0


def candidate_axes():
    """Upper-arm direction in the forearm (Watch-segment) frame for every (theta, phi): (T, P, 3)."""
    out = np.zeros((len(THETA), len(PHI), 3))
    down = np.array([0.0, -1.0, 0.0])
    for j, ph in enumerate(PHI):
        a = np.array([np.sin(-ph), 0.0, np.cos(-ph)])  # z turned about y by -phi
        for i, th in enumerate(THETA):
            # Rodrigues: rotate `down` about a by -theta
            c, s = np.cos(-th), np.sin(-th)
            out[i, j] = down * c + np.cross(a, down) * s + a * np.dot(a, down) * (1 - c)
    return out


def frame_costs(F, cand, effort=None):
    """F: (n, 3, 3) forearm segment rotations in the trunk frame. Returns (n, T, P) costs, hum.
    effort: per-frame weight of the effort term (default 1)."""
    hum = np.einsum("nij,tpj->ntpi", F, cand)  # (n, T, P, 3) trunk frame (x fwd, y up, z right)
    elev = np.degrees(np.arccos(np.clip(-hum[..., 1], -1, 1)))
    into_trunk = (hum[..., 2] < -0.35) & (hum[..., 0] < 0.4)  # across/through the chest
    behind = hum[..., 0] < -0.7
    limit = into_trunk | behind | (elev > 170)
    w = np.ones(len(F)) if effort is None else effort
    cost = (
        W_EFFORT * w[:, None, None] * elev / 90
        + W_LIMIT * limit
        + W_TWIST * np.abs(np.degrees(PHI))[None, None, :] / 90
    )
    return cost, hum


def viterbi(cost):
    n, T, P = cost.shape
    acc = cost[0].copy()
    back = np.zeros((n, T, P, 2), np.int8)
    offsets = [(dt, dp) for dt in (-2, -1, 0, 1, 2) for dp in (-2, -1, 0, 1, 2)]
    pen = {o: W_SMOOTH * (abs(o[0]) + abs(o[1])) for o in offsets}
    big = 1e9
    for k in range(1, n):
        best = np.full((T, P), big)
        arg = np.zeros((T, P, 2), np.int8)
        for dt, dp in offsets:
            sh = np.full((T, P), big)
            ts, te = max(0, dt), T + min(0, dt)
            ps, pe = max(0, dp), P + min(0, dp)
            sh[ts:te, ps:pe] = acc[ts - dt : te - dt, ps - dp : pe - dp] + pen[(dt, dp)]
            better = sh < best
            best[better] = sh[better]
            arg[better] = (dt, dp)
        acc = best + cost[k]
        back[k] = arg
    path = np.zeros((n, 2), int)
    path[-1] = np.unravel_index(np.argmin(acc), acc.shape)
    for k in range(n - 1, 0, -1):
        dt, dp = back[k, path[k, 0], path[k, 1]]
        path[k - 1] = path[k] - (dt, dp)
    return path


def run(player):
    from .align import load_aligned
    from .common import segment_rot

    d = load(player)
    d["player"] = player
    set_forward(d, player)
    Rw = segment_rot(d, "watch")
    a = load_aligned(player)
    cand = candidate_axes()
    # swing-aware: the effort prior (arm hangs) fades while the Watch turns fast (smoothed over 0.5 s)
    from scipy.ndimage import uniform_filter1d

    spin = uniform_filter1d(np.linalg.norm(d["watch_gyro"], axis=1), 15)
    fade = 1 / (1 + (spin / 4.0) ** 2)
    for name, Rt, eff in (
        ("constraint_watch_static_trunk", static_trunk(d), None),
        ("constraint_watch_aligned_trunk", a["trunk_R"], None),
        ("constraint_watch_swing", static_trunk(d), fade),
    ):
        F = np.einsum("nji,njk->nik", Rt, Rw)
        hum = np.full((len(F), 3), np.nan)
        elbow = np.full(len(F), np.nan)
        for k in np.unique(d["seg"]):
            m = np.nonzero(d["seg"] == k)[0]
            cost, H = frame_costs(F[m], cand, None if eff is None else eff[m])
            path = viterbi(cost)
            hum[m] = H[np.arange(len(m)), path[:, 0], path[:, 1]]
            elbow[m] = np.degrees(THETA[path[:, 0]])
        fore = in_trunk(Rt, Rw)
        save(player, name, hum / np.linalg.norm(hum, axis=1, keepdims=True), fore, elbow=elbow)
        print(player, name, "done", flush=True)


if __name__ == "__main__":
    for p in PLAYERS:
        run(p)
