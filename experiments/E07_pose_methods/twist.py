"""Forearm twist (pronation/supination) for every method that has an upper-arm and a forearm
rotation, scored against OpenCap's `pro_sup_r` (`gt_prosup`, degrees; 90 = palms facing the thighs).

A method's twist is the rotation of the forearm relative to the upper arm about the forearm's own
long axis (swing-twist decomposition), taken relative to the segment's Calibrate hold and set to
90 deg there, the same "standing, palms in" assumption every method uses for its mounting.
Methods with no upper-arm rotation (Watch-only geometric and constraint methods) get none.

    .venv/bin/python -m experiments.E07_pose_methods.twist   # adds `prosup` to method_*.npz (10/28)
"""

import numpy as np
from scipy.spatial.transform import Rotation

HOLD_PROSUP = 90.0  # deg at the Calibrate hold (palms facing the thighs)


def swing_twist(R, axis):
    """Twist angle (deg) of rotations R (n, 3, 3) about the unit `axis` (in R's local frame),
    from R = swing @ twist."""
    q = Rotation.from_matrix(R).as_quat()  # x, y, z, w
    return np.degrees(2 * np.arctan2(q[:, :3] @ np.asarray(axis, float), q[:, 3]))


def wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def from_hold(tw, t, hold):
    """Twist relative to each frame's hold window (`hold` (n, 2) unix start/end), set to
    HOLD_PROSUP there. Frames whose hold has no finite twist come out NaN."""
    out = np.full(len(tw), np.nan)
    for h in np.unique(hold, axis=0):
        rows = (hold == h).all(1)
        ref = np.isfinite(tw) & (t >= h[0]) & (t <= h[1])
        if not ref.any():  # hold outside this grid: nearest finite frames before the segment
            ref = np.isfinite(tw) & rows
            ref &= t <= t[ref].min() + 1.0 if ref.any() else ref
        if ref.any():
            r = np.radians(tw[ref])
            ref_deg = np.degrees(np.arctan2(np.sin(r).mean(), np.cos(r).mean()))
            out[rows] = HOLD_PROSUP + wrap(tw[rows] - ref_deg)
    return out


def relative_twist(R_upper, R_fore, fore_axis):
    """Twist of the forearm relative to the upper arm, both world <- segment rotations (n, 3, 3);
    `fore_axis` is the forearm's long axis in the forearm segment frame."""
    return swing_twist(np.einsum("nji,njk->nik", R_upper, R_fore), fore_axis)


def smpl_twist(glb, rest_joints):
    """Right-forearm twist from global SMPL rotations (n, 24, 3, 3), about the forearm's proximal
    axis (wrist -> elbow, like OpenSim's radius y) in the zero pose."""
    from .learned_published import R_ELBOW, R_SHOULDER, R_WRIST

    axis = rest_joints[R_ELBOW] - rest_joints[R_WRIST]
    return relative_twist(glb[:, R_SHOULDER], glb[:, R_ELBOW], axis / np.linalg.norm(axis))


def add(player_dir, name, d, prosup):
    """Add `prosup` (on the dataset grid) to method_<name>.npz."""
    path = player_dir / f"method_{name}.npz"
    z = dict(np.load(path, allow_pickle=True))
    z["prosup"] = prosup
    np.savez_compressed(path, **z)
    ok = np.isfinite(prosup) & d["gt_valid"]
    r = np.corrcoef(prosup[ok], d["gt_prosup"][ok])[0, 1] if ok.sum() > 30 else np.nan
    print(f"  {name:40s} twist on {ok.mean():.0%} of frames, r with OpenCap {r:+.2f}")


def main():
    from experiments.common import mobileposer_runner as mp

    from .common import OUT, load
    from .data import PLAYERS
    from .learned_published import on_grid

    rest = np.asarray(mp.body_model().get_zero_pose_joint_and_vertex()[0])
    for p in PLAYERS:
        d, pdir = load(p), OUT / p
        print(p)
        for ik in sorted(
            (pdir / "opensense").glob("ik_opensense_*.npz")
        ):  # OpenSense: its own angle
            z = np.load(ik, allow_pickle=True)
            ps = z["coords"][:, [str(c) for c in z["coord_names"]].index("pro_sup_r")]
            add(pdir, ik.stem[3:], d, np.where(z["ok"], ps, np.nan))
        for pose in sorted(pdir.glob("pose_*.npz")):  # MobilePoser, IMUCoCo: predicted skeleton
            z = np.load(pose)
            (tw,), _ = on_grid(d, z["t"], [smpl_twist(z["glb"], rest)])
            add(pdir, pose.stem[5:], d, from_hold(tw, d["t"], d["hold"]))
        a = np.load(pdir / "aligned.npz")  # geometric, constraint-aligned upper arm + Watch
        tw = relative_twist(a["upper_R"], a["watch_R"], [0, 1.0, 0])
        add(pdir, "aligned_trunk_upper_watch", d, from_hold(tw, d["t"], d["hold"]))


if __name__ == "__main__":
    main()
