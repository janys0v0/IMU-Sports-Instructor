"""Roboflow's right arm vs E07's IMU methods, scored the same way against OpenCap in phone1.

IMU methods give arm directions in the trunk frame, not positions. Each is turned into an arm in
OpenCap's world: OpenCap's shoulder marker and torso rotation, the player's own segment lengths
(median marker distances over the window), the method's upper-arm and forearm directions. That arm
is projected into phone1 with E06's camera, like OpenCap's markers. Roboflow is scored as detected
and shoulder-anchored (moved so its shoulder sits on OpenCap's), the fair match for the IMU arms.
`opencap_model` is OpenCap's own model axes through the same construction: the floor this
construction leaves (model bone axes vs video markers).

Metrics (right arm, image plane): elbow and wrist pixel error; upper-arm and forearm direction
error (angle of the 2D segment); elbow angle error. For the IMU methods E07's 3D scores on the
same frames are added (elbow flexion, forearm direction).
Writes results/<player>/compare_imu.json and compare_imu.md:
    .venv/bin/python -m experiments.E09_roboflow_pose.compare_imu janys
"""

import argparse
import json

import numpy as np

from .common import OUT, clip_info, read_predictions
from .evaluate import angle, keypoints, match_person, project_gt

METHODS = {
    "qmt_trunk_upper_watch_rest18": "Geometric, qmt heading, rest 18° (chest+upper arm+Watch)",
    "opensense_trunk_upper_watch_phone": "OpenSense IK, 4 sensors",
    "constraint_watch_swing": "Constraints, Watch only",
    "wearmocap_watch": "WearMoCap, Watch",
    "mobileposer_rw_rp_h": "MobilePoser, Watch+phone+AirPods",
    "imucoco_rw_rp_h": "IMUCoCo, Watch+phone+AirPods",
    "own_gru_watch_xplayer": "Ours GRU, Watch, other player only",
    "own_gru_allsensors_personal": "Ours GRU, all sensors, + own half of the block",
}


def dir_err(a: np.ndarray, b: np.ndarray) -> float:
    """Angle between two 2D segment directions, degrees."""
    return float(
        np.degrees(np.arccos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))
    )


def arm_scores(sh, el, wr, gsh, gel, gwr) -> dict:
    """Image-plane errors of one arm (shoulder, elbow, wrist px) against OpenCap's."""
    return {
        "elbow_px": float(np.linalg.norm(el - gel)),
        "wrist_px": float(np.linalg.norm(wr - gwr)),
        "upper_dir_deg": dir_err(el - sh, gel - gsh),
        "fore_dir_deg": dir_err(wr - el, gwr - gel),
        "elbow_angle_deg": abs(angle(sh, el, wr) - angle(gsh, gel, gwr)),
    }


def imu_arm(sh3, Rt, hum, fore, l_up, l_fore) -> tuple:
    """Shoulder, elbow, wrist in OpenCap's world from trunk-frame unit directions."""
    el = sh3 + l_up * (Rt @ hum)
    return sh3, el, el + l_fore * (Rt @ fore)


def main():
    import pandas as pd

    from experiments.E06_side_by_side import camera
    from experiments.E07_pose_methods.common import angle_between, load, load_method

    p = argparse.ArgumentParser()
    p.add_argument("player", choices=["janys", "tom"])
    a = p.parse_args()
    d = load(a.player)
    _, _, P = clip_info(a.player)
    preds = read_predictions(OUT / a.player / "predictions.jsonl")
    rows_i = [i for i in sorted(preds) if d["gt_valid"][i]]
    mk, bn = list(d["mk_names"]), list(d["body_names"])
    M = d["gt_mk"][rows_i]
    seg = {
        n: float(np.median(np.linalg.norm(M[:, mk.index(b)] - M[:, mk.index(a_)], axis=1)))
        for n, a_, b in (("up", "RShoulder", "RElbow"), ("fore", "RElbow", "RWrist"))
    }
    methods = {"opencap_model": {"hum": d["gt_hum"], "fore": d["gt_fore"], "elbow": d["gt_elbow"]}}
    methods.update({n: load_method(a.player, n) for n in METHODS})

    recs = []
    for i in rows_i:
        gt = project_gt(d, P, i)
        g = (gt["RShoulder"], gt["RElbow"], gt["RWrist"])
        base = {"i": i, "swing": bool(d["in_swing"][i])}
        kp = keypoints(match_person(preds[i].get("pose", []), gt["midHip"]))
        arm = ("right_shoulder", "right_elbow", "right_wrist")
        if all(k in kp for k in arm):
            s, e, w = (kp[k] for k in arm)
            recs.append({**base, "method": "roboflow", **arm_scores(s, e, w, *g)})
            off = g[0] - s
            recs.append(
                {**base, "method": "roboflow_anchored", **arm_scores(s + off, e + off, w + off, *g)}
            )
        Rt = d["gt_R"][i, bn.index("torso")]
        sh3 = d["gt_mk"][i, mk.index("RShoulder")]
        for n, m in methods.items():
            if not (np.all(np.isfinite(m["hum"][i])) and np.all(np.isfinite(m["fore"][i]))):
                continue
            pts = camera.project(
                P, np.array(imu_arm(sh3, Rt, m["hum"][i], m["fore"][i], seg["up"], seg["fore"]))
            )
            r = {**base, "method": n, **arm_scores(*pts, *g)}
            r["elbow3d_deg"] = abs(float(m["elbow"][i]) - float(d["gt_elbow"][i]))
            r["fore3d_deg"] = float(angle_between(m["fore"][i : i + 1], d["gt_fore"][i : i + 1])[0])
            recs.append(r)
    df = pd.DataFrame(recs)
    cols = [
        "elbow_px",
        "wrist_px",
        "upper_dir_deg",
        "fore_dir_deg",
        "elbow_angle_deg",
        "elbow3d_deg",
        "fore3d_deg",
    ]
    out = {}
    for scope, sub in (("all", df), ("swings", df[df.swing])):
        g = sub.groupby("method")[cols].median().round(1)
        g["frames"] = sub.groupby("method").size()
        out[scope] = json.loads(g.to_json(orient="index"))
    out["segment_m"] = {k: round(v, 3) for k, v in seg.items()}
    (OUT / a.player / "compare_imu.json").write_text(json.dumps(out, indent=2) + "\n")

    names = {
        "roboflow": "Roboflow YOLO pose (as detected)",
        "roboflow_anchored": "Roboflow YOLO pose (shoulder-anchored)",
        "opencap_model": "OpenCap model axes (floor of the construction)",
        **METHODS,
    }
    lines = [
        f"# E09 {a.player}: right arm, Roboflow vs IMU methods, against OpenCap in phone1",
        "",
        "Medians over the window's frames. px: image error of the elbow and wrist; dir: angle of "
        "the 2D upper-arm / forearm segment; angle: image-plane elbow angle; 3D: E07's elbow "
        "flexion and forearm direction (IMU only).",
    ]
    for scope in ("swings", "all"):
        lines += [
            "",
            f"## {scope.capitalize()}",
            "",
            "| Method | Elbow px | Wrist px | Upper-arm dir ° | Forearm dir ° | Elbow angle ° | 3D elbow ° | 3D forearm ° |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for n in names:
            if n not in out[scope]:
                continue
            r = out[scope][n]

            def f(k, r=r):
                return "–" if r.get(k) is None else f"{r[k]:.0f}"

            lines.append(
                f"| {names[n]} | {f('elbow_px')} | {f('wrist_px')} | {f('upper_dir_deg')} | "
                f"{f('fore_dir_deg')} | {f('elbow_angle_deg')} | {f('elbow3d_deg')} | {f('fore3d_deg')} |"
            )
    lines.append("")
    (OUT / a.player / "compare_imu.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
