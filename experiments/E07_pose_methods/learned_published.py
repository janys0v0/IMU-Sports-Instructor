"""Published learned whole-body models on the E07 grid: MobilePoser (MobiSys 2024) and IMUCoCo
(UIST 2025), with the Apple devices and, for IMUCoCo (which accepts sensors anywhere on the body),
the commercial upper-arm and chest sensors too.

Apple devices come calibrated by the pipeline (experiments.common.session.load_session); the
commercial ones from align.py, put in the same body frame. Arm vectors come from each model's own
forward kinematics, in its chest (SMPL spine3) frame, mapped to the trunk frame convention.

    .venv/bin/python -m experiments.E07_pose_methods.learned_published
"""

import json
import os
from copy import deepcopy
from pathlib import Path

import numpy as np

from .common import OUT, load, save
from .data import E06, PLAYERS

ROOT = Path(__file__).resolve().parents[2]
G = 9.81
SMPL_TO_OSIM = np.array(
    [[0, 0, 1.0], [0, 1.0, 0], [-1.0, 0, 0]]
)  # (x left, y up, z fwd) -> (x fwd, y up, z right)
R_SHOULDER, R_ELBOW, R_WRIST, SPINE3 = 17, 19, 21, 9
STANDING_REST_RIGHT = np.array([[0, -1.0, 0], [1.0, 0, 0], [0, 0, 1.0]])  # Rz(90): arm hanging
EXTRA_VERTEX = {}  # filled from the SMPL mesh: right upper arm (lateral), chest (front)


def arm_vectors(glb, rest_joints):
    """hum, fore (trunk frame, OpenSim convention) from global SMPL rotations."""

    def bone(j, child):
        v = rest_joints[child] - rest_joints[j]
        return v / np.linalg.norm(v)

    hum = np.einsum("nij,j->ni", glb[:, R_SHOULDER], bone(R_SHOULDER, R_ELBOW))
    fore = np.einsum("nij,j->ni", glb[:, R_ELBOW], bone(R_ELBOW, R_WRIST))
    to_trunk = lambda v: np.einsum("nji,nj->ni", glb[:, SPINE3], v) @ SMPL_TO_OSIM.T  # noqa: E731
    return to_trunk(hum), to_trunk(fore)


def on_grid(d, t_out, vals):
    """Model outputs (seconds after Start) -> dataset grid (nearest frame within 20 ms)."""
    tq = d["t"] - d["start_unix"]
    j = np.clip(np.searchsorted(t_out, tq), 1, len(t_out) - 1)
    j = np.where(np.abs(t_out[j - 1] - tq) < np.abs(t_out[j] - tq), j - 1, j)
    ok = np.abs(t_out[j] - tq) < 0.02
    return [
        np.where(ok[:, None], v[j], np.nan) if v.ndim == 2 else np.where(ok, v[j], np.nan)
        for v in vals
    ], ok


def add_commercial(session, player, rate):
    """Copy of the session with right_upper_arm and chest devices (aligned commercial sensors) in the
    pipeline's body frame, segments trimmed to where they exist."""

    from experiments.common.session import Device

    from .align import load_aligned, sensor_world
    from .common import body_basis, set_forward

    d = load(player)
    d["player"] = player
    a = load_aligned(player)
    set_forward(d, player)  # aligned rotations were made with the thigh forward
    t_s = d["t"] - d["start_unix"]
    out = deepcopy(session)
    segs = []
    for seg in out.segments:
        m = (t_s >= seg.t[0] - 1e-3) & (t_s <= seg.t[-1] + 1e-3)
        if m.sum() < 300:
            continue
        k = int(np.bincount(d["seg"][m]).argmax())
        B = body_basis(d["phone_hold_quat"][k], key=(player, k))
        Bs = body_basis(d["phone_hold_quat"][k])  # the pipeline's (screen) body frame
        R_MI = np.stack([-Bs[:, 2], Bs[:, 1], Bs[:, 0]])  # rows: left, up, forward
        keep = (seg.t >= t_s[m][0]) & (seg.t <= t_s[m][-1])
        for loc, Rkey, dev, rest in (
            ("right_upper_arm", "upper_R", "upper_arm", STANDING_REST_RIGHT),
            ("chest", "trunk_R", "trunk", np.eye(3)),
        ):
            Rseg, Rsens = a[Rkey], sensor_world(d, a, dev)
            src = np.nonzero(m)[0]
            tt = seg.t[keep]
            idx = np.clip(np.searchsorted(t_s[src], tt), 0, len(src) - 1)
            ii = src[idx]
            delta = Rseg[ii] @ B.T  # world rotation since the hold
            ori = R_MI @ delta @ R_MI.T @ rest
            acc_w = np.einsum("nij,nj->ni", Rsens[ii], -G * d[f"{dev}_acc"][ii])
            acc = acc_w @ R_MI.T
            seg.devices[loc] = Device(
                loc, acc, ori, np.ones(len(tt), bool), True, d[f"{dev}_gyro"][ii]
            )
        for dv in seg.devices.values():
            if len(dv.acc) != keep.sum():
                dv.acc, dv.ori, dv.valid = dv.acc[keep], dv.ori[keep], dv.valid[keep]
                dv.rot_rate = dv.rot_rate[keep] if dv.rot_rate is not None else None
        seg.t = seg.t[keep]
        segs.append(seg)
    out.segments = segs
    return out


def mesh_vertices():
    """Right upper-arm (lateral surface, mid-shaft) and chest (sternum) vertices on the zero-pose
    SMPL mesh, used as IMUCoCo placements for the commercial sensors."""
    from experiments.E02_imucoco_comparison import imucoco_runner as ic

    _, _, body, zero_verts = ic._load()
    joints, verts = body.get_zero_pose_joint_and_vertex()
    joints, verts = np.asarray(joints), np.asarray(verts)
    up_mid = (joints[R_SHOULDER] + joints[R_ELBOW]) / 2
    lateral = up_mid + np.array(
        [0.0, 0.05, 0.0]
    )  # T-pose: arm along -x; top of the arm (deltoid side)
    chest = (joints[SPINE3] + joints[12]) / 2 + np.array([0.0, 0.0, 0.12])
    EXTRA_VERTEX["right_upper_arm"] = int(np.argmin(np.linalg.norm(verts - lateral, axis=1)))
    EXTRA_VERTEX["chest"] = int(np.argmin(np.linalg.norm(verts - chest, axis=1)))
    return joints


def _right_wrist_alias():
    """Janys's merged session stores the Watch as "wrist"; the session loader only takes the model
    slots ("right_wrist"), so it would silently drop the Watch."""
    import experiments.common.session as S

    if getattr(S.load_recording, "_aliased", False):
        return
    orig = S.load_recording

    def patched(folder):
        rec = orig(folder)
        if "wrist" in rec.streams and "right_wrist" not in rec.streams:
            rec.streams["right_wrist"] = rec.streams.pop("wrist")
        return rec

    patched._aliased = True
    S.load_recording = patched


def main():
    from experiments.common import mobileposer_runner as mp
    from experiments.common.session import load_session

    _right_wrist_alias()

    import sys

    cwd = os.getcwd()
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--player=")]
    for player in only or PLAYERS:
        label = PLAYERS[player][0]
        meta = json.loads((E06 / label / "meta.json").read_text())
        d = load(player)
        # MobilePoser (Apple devices; the combos it was trained on that we have)
        import sys

        if "--skip-mobileposer" in sys.argv:
            s30 = None
        else:
            s30 = load_session(meta["session_dir"], rate=30)
        rest = np.asarray(mp.body_model().get_zero_pose_joint_and_vertex()[0])
        for locs in (["right_wrist", "right_pocket", "head"], ["right_wrist", "right_pocket"]):
            if s30 is None or not all(l in s30.locs for l in locs):
                continue
            o = mp.run(s30, locs)
            hum, fore = arm_vectors(o.glb, rest)
            (hum_g, fore_g), ok = on_grid(d, o.t, [hum, fore])
            name = "mobileposer_" + mp.combo_name(locs)
            save(player, name, hum_g, fore_g, valid=ok & np.isfinite(fore_g).all(1))
            np.savez_compressed(
                OUT / player / f"pose_{name}.npz",
                t=o.t,
                pose=o.pose,
                glb=o.glb,
                joints=o.joints,
                tran=o.tran,
            )
            print(player, name, f"{ok.mean():.0%} of grid")
        os.chdir(cwd)
        # IMUCoCo at 60 Hz, Apple devices, then with the commercial upper arm and chest
        from experiments.E02_imucoco_comparison import imucoco_runner as ic

        rest_ic = mesh_vertices()
        ic.SENSOR_VERTEX.update(EXTRA_VERTEX)
        os.chdir(cwd)
        s60 = load_session(meta["session_dir"], rate=60)
        s60x = add_commercial(s60, player, 60)  # trimmed to the scored blocks
        t_s = d["t"] - d["start_unix"]
        s60 = deepcopy(s60)
        s60.segments = [g for g in s60.segments if (t_s >= g.t[0]).any() and (t_s <= g.t[-1]).any()]
        for g in s60.segments:
            keep = (g.t >= t_s[0] - 1) & (g.t <= t_s[-1] + 1)
            for dv in g.devices.values():
                dv.acc, dv.ori, dv.valid = dv.acc[keep], dv.ori[keep], dv.valid[keep]
                dv.rot_rate = dv.rot_rate[keep] if dv.rot_rate is not None else None
            g.t = g.t[keep]
        for name, sess, locs in (
            ("imucoco_rw_rp_h", s60, ["right_wrist", "right_pocket", "head"]),
            (
                "imucoco_rw_rp_h_upperarm_chest",
                s60x,
                ["right_wrist", "right_pocket", "head", "right_upper_arm", "chest"],
            ),
            ("imucoco_rw_upperarm_chest", s60x, ["right_wrist", "right_upper_arm", "chest"]),
        ):
            sub = deepcopy(sess)
            sub.segments = [sg for sg in sess.segments if all(l in sg.devices for l in locs)]
            if not sub.segments:
                print(player, name, "skipped: device missing")
                continue
            o = ic.run(sub, locs)
            hum, fore = arm_vectors(o.glb, rest_ic)
            (hum_g, fore_g), ok = on_grid(d, o.t, [hum, fore])
            save(player, name, hum_g, fore_g, valid=ok & np.isfinite(fore_g).all(1))
            np.savez_compressed(
                OUT / player / f"pose_{name}.npz",
                t=o.t,
                pose=o.pose,
                glb=o.glb,
                joints=o.joints,
                tran=o.tran,
            )
            print(player, name, f"{ok.mean():.0%} of grid")
            os.chdir(cwd)


if __name__ == "__main__":
    main()
