"""Roboflow's right arm lifted to 3D and scored with E07/E08's metrics, next to the IMU methods.

Lifting, one camera: a keypoint pixel and phone1's fitted camera give a ray. The elbow is where
the elbow's ray meets a sphere of upper-arm length around the shoulder; the wrist, where its ray
meets a forearm-length sphere around that elbow. Like the IMU methods in `compare_imu.py`, the
arm gets OpenCap's shoulder (3D), torso rotation and the player's segment lengths; Roboflow's
pixels are shifted so its shoulder sits on OpenCap's (shoulder-anchored).

A ray meets a sphere twice (the segment points toward or away from the camera): 4 candidate arms
per frame. Two ways to choose:
- `roboflow_3d`: a Viterbi path, smooth in 3D, with a weak prior for the wrist in front of the
  trunk; uses no OpenCap arm information.
- `roboflow_3d_best_pick`: the candidate nearest OpenCap each frame, an upper bound that shows
  what a perfect front/back decision would give.
When a ray misses its sphere (pixel error), the point on the ray nearest the sphere is used.

`opencap_markers_3d` is OpenCap's own 3D video keypoints through the same scoring: the floor any
keypoint-based arm has against OpenCap's model-axis targets. `opencap_px_lifted*` lifts OpenCap's
own projected keypoints (perfect pixels) the same way: the ceiling of this lifting.

Scores: E07's `score` (as in E08) on the window's frames: elbow flexion, shoulder elevation,
forearm inclination, upper-arm / forearm direction, elbow and wrist position (cm).
Writes results/<player>/lift3d.json and lift3d.md:
    .venv/bin/python -m experiments.E09_roboflow_pose.lift3d janys
"""

import argparse
import json

import numpy as np

from .common import OUT, clip_info, read_predictions
from .compare_imu import METHODS
from .evaluate import keypoints, match_person, project_gt

FRONT_PRIOR = 0.05  # m of path cost per m the wrist sits behind the shoulder (trunk x < 0)


def camera_center_and_rays(P: np.ndarray, uv: np.ndarray) -> tuple:
    """Camera centre (3,) and unit ray directions (n, 3) through pixels uv (n, 2)."""
    M, p4 = P[:, :3], P[:, 3]
    C = -np.linalg.solve(M, p4)
    d = np.linalg.solve(M, np.c_[uv, np.ones(len(uv))].T).T
    return C, d / np.linalg.norm(d, axis=1, keepdims=True)


def ray_sphere(C: np.ndarray, d: np.ndarray, S: np.ndarray, L: float) -> list:
    """Points on the ray C + t d at distance L from S: two, or the nearest one if it misses."""
    b = d @ (C - S)
    disc = b * b - (np.sum((C - S) ** 2) - L * L)
    if disc <= 0:
        return [C - b * d]
    r = np.sqrt(disc)
    return [C + (-b - r) * d, C + (-b + r) * d]


def candidates(C, d_el, d_wr, S, lu, lf) -> list:
    """Every (elbow, wrist) pair the two rays allow."""
    return [(e, w) for e in ray_sphere(C, d_el, S, lu) for w in ray_sphere(C, d_wr, e, lf)]


def viterbi(cands: list, cost_unary: list) -> list:
    """Index of the chosen candidate per frame: minimum of unary cost + 3D jump between frames.
    Frames without candidates (empty list) break the path."""
    out, k = [None] * len(cands), 0
    while k < len(cands):
        if not cands[k]:
            k += 1
            continue
        j = k
        while j < len(cands) and cands[j]:
            j += 1
        acc, back = [np.array(cost_unary[k])], []
        for t in range(k + 1, j):
            prev, cur = cands[t - 1], cands[t]
            jump = np.array(
                [
                    [np.linalg.norm(ce - pe) + np.linalg.norm(cw - pw) for pe, pw in prev]
                    for ce, cw in cur
                ]
            )
            tot = jump + acc[-1][None, :]
            back.append(tot.argmin(1))
            acc.append(tot.min(1) + np.array(cost_unary[t]))
        s = int(acc[-1].argmin())
        for t in range(j - 1, k - 1, -1):
            out[t] = s
            if t > k:
                s = int(back[t - k - 1][s])
        k = j
    return out


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def main():
    from experiments.E07_pose_methods.common import elbow_from_dirs, load, load_method
    from experiments.E07_pose_methods.evaluate import arm_lengths, score

    p = argparse.ArgumentParser()
    p.add_argument("player", choices=["janys", "tom"])
    a = p.parse_args()
    d = load(a.player)
    _, _, P = clip_info(a.player)
    preds = read_predictions(OUT / a.player / "predictions.jsonl")
    n = len(d["t"])
    win = np.zeros(n, bool)
    win[sorted(preds)] = True
    mk, bn = list(d["mk_names"]), list(d["body_names"])
    S_i, E_i, W_i = (mk.index(k) for k in ("RShoulder", "RElbow", "RWrist"))
    lu, lf = arm_lengths(d["gt_mk"], d["gt_valid"])  # the lengths E07's cm metric uses

    rows = sorted(i for i in preds if d["gt_valid"][i])
    Rts = {i: d["gt_R"][i, bn.index("torso")] for i in rows}

    def lift(pixels: dict) -> tuple:
        """Candidates and smooth path from {row: (elbow px, wrist px)} (shoulder-anchored)."""
        cands, unary = [], []
        for i in rows:
            if i not in pixels:
                cands.append([]), unary.append([])
                continue
            C, rays = camera_center_and_rays(P, np.array(pixels[i]))
            S = d["gt_mk"][i, S_i]
            cs = candidates(C, rays[0], rays[1], S, lu, lf)
            cands.append(cs)
            unary.append([FRONT_PRIOR * max(0.0, -(Rts[i].T @ (w - S))[0]) for _, w in cs])
        return cands, viterbi(cands, unary)

    rf_px, oc_px = {}, {}
    for i in rows:
        gt = project_gt(d, P, i)
        oc_px[i] = (gt["RElbow"], gt["RWrist"])
        kp = keypoints(match_person(preds[i].get("pose", []), gt["midHip"]))
        if all(k in kp for k in ("right_shoulder", "right_elbow", "right_wrist")):
            off = gt["RShoulder"] - kp["right_shoulder"]
            rf_px[i] = (kp["right_elbow"] + off, kp["right_wrist"] + off)
    cands, path = lift(rf_px)
    oc_cands, oc_path = lift(oc_px)

    def as_method(cands, choose):
        hum, fore = np.full((n, 3), np.nan), np.full((n, 3), np.nan)
        for k, i in enumerate(rows):
            if not cands[k]:
                continue
            e, w = cands[k][choose(k, i)]
            S = d["gt_mk"][i, S_i]
            hum[i], fore[i] = unit(Rts[i].T @ (e - S)), unit(Rts[i].T @ (w - e))
        valid = win & np.isfinite(fore).all(1)
        return {"hum": hum, "fore": fore, "elbow": elbow_from_dirs(hum, fore), "valid": valid}

    def best(cands):
        def pick(k, i):
            g = d["gt_mk"][i]
            return int(
                np.argmin(
                    [np.linalg.norm(e - g[E_i]) + np.linalg.norm(w - g[W_i]) for e, w in cands[k]]
                )
            )

        return pick

    two_way = np.mean([len(c) > 1 for c in cands if c])
    # OpenCap's own video keypoints, scored against its model-axis targets
    Rall = d["gt_R"][:, bn.index("torso")]
    mh = unit(np.einsum("nji,nj->ni", Rall, d["gt_mk"][:, E_i] - d["gt_mk"][:, S_i]))
    mf = unit(np.einsum("nji,nj->ni", Rall, d["gt_mk"][:, W_i] - d["gt_mk"][:, E_i]))
    methods = {
        "opencap_markers_3d": {
            "hum": mh,
            "fore": mf,
            "elbow": elbow_from_dirs(mh, mf),
            "valid": win.copy(),
        },
        "opencap_px_lifted": as_method(oc_cands, lambda k, i: oc_path[k]),
        "opencap_px_lifted_best_pick": as_method(oc_cands, best(oc_cands)),
        "roboflow_3d": as_method(cands, lambda k, i: path[k]),
        "roboflow_3d_best_pick": as_method(cands, best(cands)),
    }
    for name in METHODS:
        m = load_method(a.player, name)
        methods[name] = {k: m[k] for k in ("hum", "fore", "elbow")} | {"valid": m["valid"] & win}

    scores = {name: score(d, m) for name, m in methods.items()}
    scores["_info"] = {"frames": int(win.sum()), "two_way_frames": round(float(two_way), 3)}
    (OUT / a.player / "lift3d.json").write_text(json.dumps(scores, indent=1) + "\n")

    names = {
        "opencap_markers_3d": "OpenCap's own 3D keypoints (floor)",
        "opencap_px_lifted": "OpenCap's pixels lifted, smooth path (lifting ceiling)",
        "opencap_px_lifted_best_pick": "OpenCap's pixels lifted, best pick",
        "roboflow_3d": "Roboflow lifted to 3D (smooth path)",
        "roboflow_3d_best_pick": "Roboflow lifted, best front/back pick (upper bound)",
        **METHODS,
    }
    cols = [
        ("elbow_mae", "Elbow °"),
        ("elevation_mae", "Shoulder elev. °"),
        ("forearm_incl_mae", "Forearm incl. °"),
        ("upper_arm_dir_deg", "Upper-arm dir. °"),
        ("forearm_dir_deg", "Forearm dir. °"),
        ("elbow_pos_cm", "Elbow cm"),
        ("wrist_pos_cm", "Wrist cm"),
    ]
    lines = [
        f"# E09 {a.player}: right arm in 3D, E07/E08 metrics, Roboflow vs IMU methods",
        "",
        f"{int(win.sum())} frames (20 s window); medians against OpenCap (E07's `score`). Front/back "
        f"ambiguous (ray meets the sphere twice) for the elbow or wrist in {two_way:.0%} of frames.",
    ]
    for part, title in (("swing", "Swings"), ("all", "Whole window")):
        lines += ["", f"## {title}", "", "| Method | " + " | ".join(c for _, c in cols) + " |"]
        lines.append("|---" * (len(cols) + 1) + "|")
        for k, label in names.items():
            s = scores[k].get(part, {})
            vals = " | ".join("–" if c not in s else f"{s[c]:.0f}" for c, _ in cols)
            lines.append(f"| {label} | {vals} |")
    lines.append("")
    (OUT / a.player / "lift3d.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
