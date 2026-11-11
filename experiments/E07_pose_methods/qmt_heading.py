"""Geometric method with qmt's published heading correction (Laidig et al. 2017/2019, `qmt`
headingCorrection, 2-DoF elbow: pronation about the forearm's long axis, flexion about the
upper arm's medio-lateral axis). It puts the upper-arm sensor (VQF, no magnetometer) into the
Watch's frame; compare with align.py's own grid-search version.

    .venv/bin/python -m experiments.E07_pose_methods.qmt_heading
"""

import numpy as np
from scipy.spatial.transform import Rotation

from .align import load_aligned, rz
from .common import body_basis, in_trunk, load, save, set_forward
from .data import PLAYERS

REST_ELBOW_DEG = 18.0


def run(player):
    import qmt

    d = load(player)
    d["player"] = player
    set_forward(d, player)
    a = load_aligned(player)
    hum = np.full((len(d["t"]), 3), np.nan)
    for k in np.unique(d["seg"]):
        m = d["seg"] == k
        t = np.arange(m.sum()) / 30.0  # equidistant, as qmt requires
        qw = Rotation.from_quat(d["watch_quat"][m])
        qu = Rotation.from_quat(d["upper_arm_quat"][m])
        Rwh = Rotation.from_quat(d["watch_hold_quat"][k]).as_matrix()
        Ruh = Rotation.from_quat(d["upper_arm_hold_quat"][k]).as_matrix()
        long_w = Rwh.T @ np.array(
            [0, 0, -1.0]
        )  # forearm axis in the Watch frame (arm hangs at the hold)
        B = body_basis(d["phone_hold_quat"][k], key=(player, int(k)))
        y0 = np.radians(a["upper_y0"][m][0])
        flex_u = (rz(np.array([y0]))[0] @ Ruh).T @ B[
            :, 2
        ]  # body right in the upper-arm sensor frame
        joint = np.array([long_w, flex_u])
        out = qmt.headingCorrection(
            d["watch_gyro"][m],
            d["upper_arm_gyro"][m],
            qw.as_quat()[:, [3, 0, 1, 2]],
            qu.as_quat()[:, [3, 0, 1, 2]],
            t,
            joint,
            None,
            estSettings=dict(
                windowTime=8.0,
                estimationRate=1.0,
                dataRate=5.0,
                alignment="center",
                enableStillness=False,
                constraint="euler",
            ),
        )
        qc = np.asarray(out[0])[:, [1, 2, 3, 0]]  # upper arm in the Watch's (Apple) reference
        Rc = Rotation.from_quat(qc).as_matrix()
        s2b = Rc[0].T @ B  # segment = body frame: use the first frame after the hold
        hum[m] = in_trunk(a["trunk_R"][m], Rc @ s2b)
    fore = in_trunk(a["trunk_R"], a["watch_R"])
    save(player, "qmt_trunk_upper_watch", hum, fore)
    # the joint zero assumes a straight elbow at the hold; a relaxed hanging arm is bent ~18 deg
    # (OpenCap, both players): one fixed rest angle, not fitted per person
    from .common import elbow_from_dirs

    save(
        player,
        "qmt_trunk_upper_watch_rest18",
        hum,
        fore,
        elbow=elbow_from_dirs(hum, fore) + REST_ELBOW_DEG,
    )
    print(player, "done")


if __name__ == "__main__":
    for p in PLAYERS:
        run(p)
