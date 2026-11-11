"""Model-free methods: segment orientations straight from the sensors (OpenSense's idea without the
body model), with and without a magnetometer-free heading fix.

- direct_<trunk>_<upper>_<fore>: each segment's sensor gives its orientation; upper arm and forearm
  long axes in the trunk frame. Elbow = angle between them.
- watch_static_trunk: Watch only, trunk assumed fixed in its calibration pose; forearm only.
- hinge_<...>: as direct, but the forearm sensor's heading is re-estimated every 10 s from the
  elbow's constraint (it only flexes and twists, never bends sideways), as in Laidig et al.

    .venv/bin/python -m experiments.E07_pose_methods.geometric
"""

import numpy as np
from scipy.spatial.transform import Rotation

from .common import in_trunk, load, save, segment_rot, static_trunk
from .data import PLAYERS

WINDOW_S, STEP_S = 10.0, 2.0


def direct(d, trunk, upper, fore):
    Rt = static_trunk(d) if trunk is None else segment_rot(d, trunk)
    Rf = segment_rot(d, fore)
    f = in_trunk(Rt, Rf)
    h = in_trunk(Rt, segment_rot(d, upper)) if upper else np.full_like(f, np.nan)
    return h, f, Rt, Rf


def side_bend(Ru, Rf):
    """Elbow rotation about the body's forward axis (the varus/valgus the joint cannot do), deg.
    Joint rotation J = Ru^T Rf in the upper-arm frame; with the arm hanging at the hold, flexion is
    about z (right) and twist about y; the x-component of the swing of y is the forbidden part."""
    J = np.einsum("nji,njk->nik", Ru, Rf)
    y = J[:, :, 1]  # forearm long axis (up) in the upper-arm frame
    return np.degrees(np.arcsin(np.clip(y[:, 2], -1, 1)))  # out of the flexion plane


def hinge_heading(d, Ru, Rf):
    """Per-window heading correction of the upper-arm sensor (about world vertical) minimising the
    sideways elbow bend against the forearm (the Watch, whose heading Apple keeps), smoothed and
    interpolated to every frame. The correction is applied to the sensor's motion since the hold."""
    t = d["t"]
    yaws = np.radians(np.arange(-90, 91, 3))
    centres, best = [], []
    for c in np.arange(t[0] + WINDOW_S / 2, t[-1] - WINDOW_S / 2, STEP_S):
        m = (np.abs(t - c) < WINDOW_S / 2) & np.isfinite(Rf[:, 0, 0])
        # only frames with the elbow bent: a straight arm says nothing about heading
        bent = (
            np.degrees(np.arccos(np.clip(np.einsum("nji,nj->ni", Ru[m], Rf[m, :, 1])[:, 1], -1, 1)))
            > 30
        )
        if m.sum() < 60 or bent.sum() < 30:
            continue
        cost = []
        for y in yaws:
            Rc = Rotation.from_euler("z", y).as_matrix() @ Ru[m][bent]
            cost.append(np.median(np.abs(side_bend(Rc, Rf[m][bent]))))
        centres.append(c)
        best.append(yaws[int(np.argmin(cost))])
    best = np.unwrap(np.array(best))
    # median filter over 5 windows to reject jumps
    sm = np.array([np.median(best[max(0, i - 2) : i + 3]) for i in range(len(best))])
    yaw = np.interp(t, centres, sm)
    return np.einsum("nij,njk->nik", Rotation.from_euler("z", yaw).as_matrix(), Ru), np.degrees(yaw)


DOWN = np.array([0.0, -1.0, 0.0])


def oracle_yaw(d, R, Rt, gt_vec, axis=DOWN, fit_s=60.0):
    """Upper bound: one heading offset per segment for this sensor (about world vertical), fitted to
    OpenCap over the first `fit_s` of the segment; scored on the rest. Stands in for a better
    mounting calibration (e.g. an arm-raise move at Calibrate)."""
    from .common import in_trunk

    out = R.copy()
    yaws = np.radians(np.arange(-180, 180, 2))
    for k in np.unique(d["seg"]):
        m = d["seg"] == k
        fit = m & d["gt_valid"] & (d["t"] < d["t"][m][0] + fit_s)
        best = min(
            yaws,
            key=lambda y: np.median(
                np.degrees(
                    np.arccos(
                        np.clip(
                            np.sum(
                                in_trunk(
                                    Rt[fit], Rotation.from_euler("z", y).as_matrix() @ R[fit], axis
                                )
                                * gt_vec[fit],
                                1,
                            ),
                            -1,
                            1,
                        )
                    )
                )
            ),
        )
        out[m] = Rotation.from_euler("z", best).as_matrix() @ R[m]
    return out


def run(player):
    from .common import set_forward

    d = load(player)
    d["player"] = player
    set_forward(d, player)
    variants = {
        "direct_trunk_upper_watch": ("trunk", "upper_arm", "watch"),
        "direct_trunk_upper_cwrist": ("trunk", "upper_arm", "cwrist"),
        "direct_static_upper_watch": (None, "upper_arm", "watch"),
        "watch_static_trunk": (None, None, "watch"),
        "watch_airpods_trunk": ("airpods", None, "watch"),
    }
    for name, (tr, up, fo) in variants.items():
        h, f, _, _ = direct(d, tr, up, fo)
        el = None if up else np.full(len(f), np.nan)
        save(player, name, h, f, elbow=el)
    Rt, Ru, Rw = segment_rot(d, "trunk"), segment_rot(d, "upper_arm"), segment_rot(d, "watch")
    Rc, yaw = hinge_heading(d, Ru, Rw)
    save(player, "hinge_trunk_upper_watch", in_trunk(Rt, Rc), in_trunk(Rt, Rw), yaw=yaw)
    print(
        f"{player} hinge: upper-arm heading correction median {np.median(yaw):+.0f} deg, IQR "
        f"{np.percentile(yaw, 25):+.0f}..{np.percentile(yaw, 75):+.0f}"
    )
    # upper bound: trunk and upper-arm headings fitted to OpenCap in each segment's first minute
    Rto = oracle_yaw(
        d, Rt, Rt, d["gt_hum"] * 0 + np.array([0, -1.0, 0])
    )  # trunk: keep (needs a ref)
    Ruo = oracle_yaw(d, Ru, Rt, d["gt_hum"])
    Rwo = oracle_yaw(d, Rw, Rt, d["gt_fore"])
    fit = np.zeros(len(d["t"]), bool)
    for k in np.unique(d["seg"]):
        m = d["seg"] == k
        fit |= m & (d["t"] < d["t"][m][0] + 60)
    save(player, "upper_bound_mounting_fit", in_trunk(Rto, Ruo), in_trunk(Rto, Rwo), valid=~fit)
    # magnetometer-free, constraint-aligned (align.py): trunk heading pulled to the phone, upper-arm
    # heading from the elbow hinge against the Watch
    from .align import load_aligned

    a = load_aligned(player)
    combos = {
        "aligned_trunk_upper_watch": (a["trunk_R"], a["upper_R"], a["watch_R"]),
        "aligned_phone_as_trunk_upper_watch": (a["phone_R"], a["upper_R"], a["watch_R"]),
        "aligned_trunk_watch": (a["trunk_R"], None, a["watch_R"]),
    }
    for name, (Rt_, Ru_, Rf_) in combos.items():
        f = in_trunk(Rt_, Rf_)
        h = in_trunk(Rt_, Ru_) if Ru_ is not None else np.full_like(f, np.nan)
        save(player, name, h, f, elbow=None if Ru_ is not None else np.full(len(f), np.nan))
    # oracle check: OpenCap's own directions must score zero
    save(
        player,
        "zz_oracle_opencap",
        d["gt_hum"],
        d["gt_fore"],
        elbow=d["gt_elbow"],
        valid=d["gt_valid"],
    )


if __name__ == "__main__":
    for p in PLAYERS:
        run(p)
