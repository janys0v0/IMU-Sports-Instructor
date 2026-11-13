"""Score Roboflow keypoints against OpenCap projected into phone1 (E06's fitted camera).

Writes results/<player>/metrics.json, summary.md and per_frame.csv (csv not committed):
    .venv/bin/python -m experiments.E09_roboflow_pose.evaluate janys
"""

import argparse
import json
from typing import Optional

import numpy as np

from .common import JOINTS, MAX_MATCH_PX, MIN_CONF, OUT, read_predictions


def match_person(preds: list, hip_px: np.ndarray) -> Optional[dict]:
    """The detection whose box centre is nearest OpenCap's projected mid-hip, if near enough."""
    if not preds:
        return None
    best = min(preds, key=lambda p: np.hypot(p["x"] - hip_px[0], p["y"] - hip_px[1]))
    return best if np.hypot(best["x"] - hip_px[0], best["y"] - hip_px[1]) <= MAX_MATCH_PX else None


def keypoints(det: Optional[dict]) -> dict:
    """{COCO name: (x, y)} for keypoints at or above MIN_CONF."""
    if det is None:
        return {}
    return {
        k["class"]: np.array([k["x"], k["y"]])
        for k in det["keypoints"]
        if k["confidence"] >= MIN_CONF
    }


def angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle at b, degrees (2D image-plane joint angle)."""
    u, v = a - b, c - b
    return float(
        np.degrees(np.arccos(np.clip(u @ v / np.linalg.norm(u) / np.linalg.norm(v), -1, 1)))
    )


def frame_errors(kp: dict, gt: dict) -> dict:
    """Per-joint pixel error and right-elbow angle error; NaN where a keypoint is missing."""
    r = {o: float(np.linalg.norm(kp[c] - gt[o])) if c in kp else np.nan for o, c in JOINTS.items()}
    arm = ("right_shoulder", "right_elbow", "right_wrist")
    r["elbow_err"] = (
        abs(angle(*(kp[k] for k in arm)) - angle(gt["RShoulder"], gt["RElbow"], gt["RWrist"]))
        if all(k in kp for k in arm)
        else np.nan
    )
    return r


def project_gt(d: dict, P: np.ndarray, i: int) -> dict:
    from experiments.E06_side_by_side import camera

    uv = camera.project(P, d["gt_mk"][i])
    return dict(zip(list(d["mk_names"]), uv))


def main():
    import pandas as pd

    from experiments.E07_pose_methods.common import load

    from .common import clip_info

    p = argparse.ArgumentParser()
    p.add_argument("player", choices=["janys", "tom"])
    a = p.parse_args()
    d = load(a.player)
    _, _, P = clip_info(a.player)
    preds = read_predictions(OUT / a.player / "predictions.jsonl")
    rows = []
    for i, pr in sorted(preds.items()):
        if not d["gt_valid"][i] or "error" in pr:
            continue
        gt = project_gt(d, P, i)
        det = match_person(pr["pose"], gt["midHip"])
        torso = float(np.linalg.norm((gt["RShoulder"] + gt["LShoulder"]) / 2 - gt["midHip"]))
        r = {"i": i, "found": det is not None, "torso_px": torso, "swing": bool(d["in_swing"][i])}
        r.update(frame_errors(keypoints(det), gt))
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / a.player / "per_frame.csv", index=False)

    E, tor, sw = df[list(JOINTS)].to_numpy(), df.torso_px.to_numpy()[:, None], df.swing.to_numpy()
    pck = 0.2 * tor > E
    fin = np.isfinite(E)
    per_joint = {}
    for k, o in enumerate(JOINTS):
        e, f = E[:, k], fin[:, k]
        per_joint[o] = {
            "median_px": round(float(np.nanmedian(e)), 1),
            "p90_px": round(float(np.nanpercentile(e, 90)), 1),
            "pck_0.2_torso": round(float(pck[f, k].mean()), 3),
            "swing_median_px": round(float(np.nanmedian(e[sw])), 1),
            "missing": round(float(1 - f.mean()), 3),
        }
    m = {
        "player": a.player,
        "frames": len(df),
        "swing_frames": int(sw.sum()),
        "player_found": round(float(df.found.mean()), 3),
        "median_torso_px": round(float(np.median(tor)), 1),
        "all_joints_median_px": round(float(np.median(E[fin])), 1),
        "all_joints_pck_0.2_torso": round(float(pck[fin].mean()), 3),
        "r_elbow_angle_err_deg": round(float(df.elbow_err.median()), 1),
        "r_elbow_angle_err_swing_deg": round(float(df.elbow_err[sw].median()), 1),
        "joints": per_joint,
    }
    (OUT / a.player / "metrics.json").write_text(json.dumps(m, indent=2) + "\n")
    lines = [
        f"# E09 {a.player}: Roboflow YOLO pose vs OpenCap projected into phone1",
        "",
        f"{m['frames']} frames ({m['swing_frames']} in swings); player found in "
        f"{m['player_found']:.1%}; median torso {m['median_torso_px']:.0f} px.",
        "",
        "| Joint | Median px | p90 px | PCK@0.2 torso | Swing median px |",
        "|---|---|---|---|---|",
    ]
    for o, j in per_joint.items():
        lines.append(
            f"| {o} | {j['median_px']} | {j['p90_px']} | {j['pck_0.2_torso']:.0%} | {j['swing_median_px']} |"
        )
    lines += [
        "",
        f"All joints: median {m['all_joints_median_px']} px, PCK@0.2 torso "
        f"{m['all_joints_pck_0.2_torso']:.0%}. Right elbow angle (image plane): median error "
        f"{m['r_elbow_angle_err_deg']}° ({m['r_elbow_angle_err_swing_deg']}° in swings).",
        "",
    ]
    (OUT / a.player / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
