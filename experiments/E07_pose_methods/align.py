"""Put the commercial trunk and upper-arm sensors into the Apple world frame, without magnetometers.

VQF without the field gives tilt that holds and a heading that drifts 15-20 deg/min with an
arbitrary start. Two physical constraints fix the heading:
- trunk: complementary filter. Short-term heading from the trunk sensor, pulled towards the
  pocket phone's heading (thigh, Apple's filter) with a 10 s time constant; the trunk and thigh
  face the same way on average even though the trunk turns through every stroke.
- upper arm: the elbow cannot bend sideways. Every 2 s the upper-arm heading (relative to the
  Watch, whose heading Apple keeps) is chosen to minimise the sideways bend over the surrounding
  10 s while the elbow is bent (Laidig et al. 2017 idea, grid search).
Each sensor's frame offset at the start (the arbitrary VQF heading) is found the same way, by
grid search over the whole segment.

Writes results/<player>/aligned.npz: trunk_R, upper_R, watch_R, phone_R (world <- segment, Apple
world, segment = body frame during the hold) plus the heading corrections.
"""

import numpy as np
from scipy.spatial.transform import Rotation

from .common import OUT, body_basis, load, segment_rot
from .data import PLAYERS

TAU_S, FS = 10.0, 30.0
WINDOW_S, STEP_S = 10.0, 2.0


def rz(a):
    """(n, 3, 3) rotations about world z by angles a (rad)."""
    c, s = np.cos(a), np.sin(a)
    R = np.zeros((len(a), 3, 3))
    R[:, 0, 0], R[:, 0, 1], R[:, 1, 0], R[:, 1, 1], R[:, 2, 2] = c, -s, s, c, 1
    return R


def seg_rot_offset(d, dev, y0, m):
    """World <- segment for a sensor whose world frame is turned by y0 (rad) from Apple's."""
    R = Rotation.from_quat(d[f"{dev}_quat"][m]).as_matrix()
    k = d["seg"][m][0]
    Rh = Rotation.from_quat(d[f"{dev}_hold_quat"][k]).as_matrix()
    Y = rz(np.array([y0]))[0]
    B = body_basis(d["phone_hold_quat"][k], key=(str(d.get("player", "")), int(k)))
    return Y @ R @ Rh.T @ Y.T @ B


def heading(R, axis=(1.0, 0, 0)):
    v = R @ np.array(axis)
    return np.arctan2(v[:, 1], v[:, 0])


def lowpass_angle(a, tau_s=TAU_S, fs=FS):
    """Forward-backward first-order low-pass of an angle (on the unit circle)."""
    from scipy.signal import filtfilt

    k = 1 / (tau_s * fs)
    z = np.exp(1j * a)
    y = filtfilt([k], [1, -(1 - k)], z.real, padlen=0) + 1j * filtfilt(
        [k], [1, -(1 - k)], z.imag, padlen=0
    )
    return np.angle(y)


def align_trunk(d, m, Rp):
    """Trunk segment rotations with the drift pulled to the phone's heading; picks the frame offset
    that makes the corrected trunk's forward axis closest to the phone's."""
    best = None
    for y0 in np.radians(np.arange(-180, 180, 10)):
        Rt = seg_rot_offset(d, "trunk", y0, m)
        c = lowpass_angle(np.angle(np.exp(1j * (heading(Rp) - heading(Rt)))))
        Rc = rz(c) @ Rt
        cost = np.median(
            np.degrees(np.arccos(np.clip(np.einsum("ni,ni->n", Rc[:, :, 0], Rp[:, :, 0]), -1, 1)))
        )
        if best is None or cost < best[0]:
            best = (cost, y0, Rc, c)
    return best[2], np.degrees(best[3]), np.degrees(best[1])


def side_bend(Ru, Rf):
    y = np.einsum("nji,nj->ni", Ru, Rf[:, :, 1])
    return np.degrees(np.arcsin(np.clip(y[:, 2], -1, 1)))


def bent(Ru, Rf, min_deg=30):
    y = np.einsum("nji,nj->ni", Ru, Rf[:, :, 1])
    return np.degrees(np.arccos(np.clip(y[:, 1], -1, 1))) > min_deg


def align_upper(d, m, Rw):
    """Upper-arm rotations with per-window heading from the elbow constraint against the Watch."""
    t = d["t"][m]
    yaws = np.radians(np.arange(-90, 91, 5))

    def windows(Ru):
        cs, best, total = [], [], 0.0
        for c in np.arange(t[0] + WINDOW_S / 2, t[-1] - WINDOW_S / 2 + 1e-6, STEP_S):
            w = np.abs(t - c) < WINDOW_S / 2
            b = bent(Ru[w], Rw[w])
            if b.sum() < 30:
                continue
            # forearm axis in the world, and the upper arm's axes: side bend for every yaw at once
            fw = Rw[w][b][:, :, 1]  # (k, 3)
            U = Ru[w][b]  # (k, 3, 3); rz(y) U -> component of fw along (rz(y) U)[:, :, 2]
            cy, sy = np.cos(yaws)[:, None], np.sin(yaws)[:, None]
            zx, zy, zz = U[:, 0, 2][None], U[:, 1, 2][None], U[:, 2, 2][None]
            comp = (cy * zx - sy * zy) * fw[:, 0] + (sy * zx + cy * zy) * fw[:, 1] + zz * fw[:, 2]
            costs = np.median(np.abs(np.degrees(np.arcsin(np.clip(comp, -1, 1)))), axis=1)
            i = int(np.argmin(costs))
            cs.append(c)
            best.append(yaws[i])
            total += costs[i]
        return np.array(cs), np.array(best), total

    choice = None
    for y0 in np.radians(np.arange(-180, 180, 15)):
        Ru = seg_rot_offset(d, "upper_arm", y0, m)
        cs, best, total = windows(Ru)
        if len(cs) and (choice is None or total < choice[0]):
            choice = (total, y0, Ru, cs, best)
    _, y0, Ru, cs, best = choice
    best = np.unwrap(best)
    sm = np.array([np.median(best[max(0, i - 2) : i + 3]) for i in range(len(best))])
    corr = np.interp(t, cs, sm)
    return rz(corr) @ Ru, np.degrees(corr), np.degrees(y0)


def run(player):
    from .common import set_forward

    d = load(player)
    d["player"] = player
    set_forward(d, player)
    n = len(d["t"])
    out = {k: np.zeros((n, 3, 3)) for k in ("trunk_R", "upper_R")}
    out["trunk_corr"], out["upper_corr"] = np.zeros(n), np.zeros(n)
    out["trunk_y0"], out["upper_y0"] = np.zeros(n), np.zeros(n)
    out["watch_R"], out["phone_R"] = segment_rot(d, "watch"), segment_rot(d, "phone")
    for k in np.unique(d["seg"]):
        m = d["seg"] == k
        Rt, ct, y0t = align_trunk(d, m, out["phone_R"][m])
        Ru, cu, y0u = align_upper(d, m, out["watch_R"][m])
        out["trunk_R"][m], out["trunk_corr"][m] = Rt, ct
        out["upper_R"][m], out["upper_corr"][m] = Ru, cu
        out["trunk_y0"][m], out["upper_y0"][m] = y0t, y0u
        print(
            f"{player} seg {k}: trunk frame offset {y0t:+.0f} deg, drift fix IQR {np.percentile(ct, 25):+.0f}..{np.percentile(ct, 75):+.0f}; "
            f"upper arm offset {y0u:+.0f} deg, fix IQR {np.percentile(cu, 25):+.0f}..{np.percentile(cu, 75):+.0f}"
        )
    np.savez_compressed(OUT / player / "aligned.npz", **out)


def sensor_world(d, a, dev):
    """Sensor -> Apple world rotations (n, 3, 3) for an aligned commercial sensor (for its
    accelerations): rz(corr) rz(y0) R_vqf."""
    key = {"trunk": "trunk", "upper_arm": "upper"}[dev]
    R = Rotation.from_quat(d[f"{dev}_quat"]).as_matrix()
    return rz(np.radians(a[f"{key}_corr"] + a[f"{key}_y0"])) @ R


def load_aligned(player):
    z = np.load(OUT / player / "aligned.npz")
    return {k: z[k] for k in z.files}


if __name__ == "__main__":
    for p in PLAYERS:
        run(p)
