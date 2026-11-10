"""11/05 OpenCap ground truth in the same layout as 10/28's `aligned_hrnet3/<trial>/opencap_gt.npz`.

Input: jtchen's 3-camera HRNet reconstruction (copy in data/external/20261105/opencap_jtchen; its
README says what each folder holds). 100 segments of ~25 s in three recordings (r1245, r1309,
r1334), each segment's times on its recording's Cam0 clock (`segments/<seg>.json`, `t_first`).
For every segment with filtered IK, the scaled model is posed frame by frame to get each body's
rotation and position in ground; rotation rates come from consecutive rotations. Markers are the
20 filtered keypoints. Output: one file per recording, segments concatenated on its clock
(`data/external/20261105/aligned/<rec>/opencap_gt.npz`); the clip -> unix offset is found later,
against the Watch, as on 10/28.

Runs in the OpenSim env (see E07's opensense.py for how it was made):

    ~/micromamba-envs/opensim/bin/python experiments/E08_new_day/opencap_gt.py
"""

import json
from pathlib import Path

import numpy as np
import opensim as osim

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "external" / "20261105" / "opencap_jtchen"
OUT = ROOT / "data" / "external" / "20261105" / "aligned"
BODIES = ["pelvis", "torso", "humerus_r", "radius_r", "hand_r", "humerus_l", "radius_l", "hand_l",
          "femur_r", "tibia_r", "calcn_r", "femur_l", "tibia_l", "calcn_l"]  # fmt: skip


def read_mot(path):
    lines = path.read_text().splitlines()
    k = next(i for i, s in enumerate(lines) if s.strip() == "endheader")
    names = lines[k + 1].split("\t")
    data = np.loadtxt(lines[k + 2 :])
    return names, data


def read_trc(path):
    lines = path.read_text().splitlines()
    names = [s for s in lines[3].split("\t")[2:] if s]
    data = np.loadtxt(lines[5:], ndmin=2)
    return names, data[:, 1], data[:, 2:].reshape(len(data), len(names), 3)


def pose_bodies(model, state, names, data):
    """Bodies' rotation and position in ground for every row of an IK .mot (degrees)."""
    coords = model.getCoordinateSet()
    cols = [(coords.get(n), n) for n in names[1:] if coords.contains(n)]
    bodies = [model.getBodySet().get(b) for b in BODIES]
    R = np.empty((len(data), len(BODIES), 3, 3))
    P = np.empty((len(data), len(BODIES), 3))
    idx = {n: i for i, n in enumerate(names)}
    for f, row in enumerate(data):
        for c, n in cols:
            v = row[idx[n]]
            rot = c.getMotionType() == osim.Coordinate.Rotational
            c.setValue(state, np.radians(v) if rot else v, False)
        model.realizePosition(state)
        for b, body in enumerate(bodies):
            tf = body.getTransformInGround(state)
            m = tf.R().asMat33()
            R[f, b] = [[m.get(i, j) for j in range(3)] for i in range(3)]
            p = tf.p()
            P[f, b] = [p.get(0), p.get(1), p.get(2)]
    return R, P


def rates(R, t):
    """Body-frame rotation rate (rad/s) from consecutive rotations, central where possible."""
    W = np.zeros(R.shape[:2] + (3,))
    for k in range(1, len(R) - 1):
        D = np.einsum("bji,bjk->bik", R[k - 1], R[k + 1])  # R_{k-1}^T R_{k+1}
        ang = np.arccos(np.clip((np.trace(D, axis1=1, axis2=2) - 1) / 2, -1, 1))
        ax = np.stack(
            [D[:, 2, 1] - D[:, 1, 2], D[:, 0, 2] - D[:, 2, 0], D[:, 1, 0] - D[:, 0, 1]], 1
        )
        s = np.sin(ang)
        ax = np.where(s[:, None] > 1e-9, ax / (2 * np.maximum(s, 1e-9))[:, None], 0)
        W[k] = ax * (ang / (t[k + 1] - t[k - 1]))[:, None]
    if len(R) > 2:
        W[0], W[-1] = W[1], W[-2]
    return W


def main():
    model = osim.Model(str(SRC / "OpenSimData" / "Model" / "LaiUhlrich2022_scaled.osim"))
    state = model.initSystem()
    per_rec = {}
    for js in sorted((SRC / "segments").glob("*.json")):
        meta = json.loads(js.read_text())
        mot = SRC / "OpenSimData" / "Kinematics_filtered" / f"{meta['seg']}.mot"
        trc = SRC / "MarkerData" / "PreAugmentation_filtered" / f"{meta['seg']}.trc"
        if meta.get("status") != "ok" or not mot.exists() or not trc.exists():
            continue
        names, data = read_mot(mot)
        mk_names, mk_t, mk = read_trc(trc)
        t = meta["t_first"] + data[:, 0]
        R, P = pose_bodies(model, state, names, data)
        ik = data[:, 1:]
        mk_i = np.stack(
            [np.stack([np.interp(data[:, 0], mk_t - mk_t[0], mk[:, m, j]) for j in range(3)], 1)
             for m in range(mk.shape[1])], 1)  # fmt: skip
        part = dict(t=t, seg=np.full(len(t), meta["seg"]), ik=ik, mk=mk_i, R=R, W=rates(R, t), P=P)
        per_rec.setdefault(meta["trial"], []).append(part)
        print(meta["seg"], meta["trial"], f"{t[0]:.1f}-{t[-1]:.1f} s", len(t), "frames", flush=True)
    for rec, parts in per_rec.items():
        parts.sort(key=lambda p: p["t"][0])
        z = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        order = np.argsort(z["t"], kind="stable")
        z = {k: v[order] for k, v in z.items()}
        keep = np.r_[True, np.diff(z["t"]) > 1e-6]  # overlapping segment edges: first wins
        z = {k: v[keep] for k, v in z.items()}
        (OUT / rec).mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            OUT / rec / "opencap_gt.npz", **z, ik_names=np.array(names[1:]),
            mk_names=np.array(mk_names), body_names=np.array(BODIES), fps=30000 / 1001,
        )  # fmt: skip
        print(rec, len(z["t"]), "frames", f"{len(z['t']) / 30 / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
