"""E04: IMU joint angles (MobilePoser) against single-camera video (Apple Vision 3D pose).

Run from the repo root (macOS 14+, the video in <session>/video/):
    .venv/bin/python -m experiments.E04_video_validation.run [SESSION] [--realign]

Steps (each saved next to the video, redone only when missing or with --realign):
1. alignment.json: video vs IMU offset from on-screen motion (align.py);
2. vision_pose.json: 3D pose per video frame (vision_pose.swift, about 1 s per frame);
3. MobilePoser on all devices, joint angles from both, agreement per activity.

Writes results/<SESSION>/: metrics.json, summary.md, angles.png.
"""

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from experiments.common import metrics, paths
from experiments.common import mobileposer_runner as mp
from experiments.common.session import load_session

from . import align as video_align
from . import angles as A

DEFAULT_SESSION = "field/20261019-000116-P01"
WRIST_POSES = ("standing", "arms_out")
HERE = Path(__file__).resolve().parent
LABEL = {
    "r_elbow": "Right elbow flexion (Watch arm)",
    "l_elbow": "Left elbow flexion (no sensor)",
    "r_knee": "Right knee flexion (phone leg)",
    "l_knee": "Left knee flexion (no sensor)",
    "r_shoulder": "Right shoulder elevation (Watch arm)",
    "l_shoulder": "Left shoulder elevation (no sensor)",
}


def find_video(folder: Path) -> Path:
    videos = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".mov", ".mp4", ".m4v"))
    if not videos:
        raise FileNotFoundError(f"no video in {folder}")
    return videos[0]


def vision_frames(video: Path, redo=False) -> list:
    out = video.parent / "vision_pose.json"
    if redo or not out.exists():
        subprocess.run(["swift", str(HERE / "vision_pose.swift"), str(video), str(out)], check=True)
    return json.loads(out.read_text())["frames"]


def windows(annotation, t_lo, t_hi):
    """Activity windows (seconds after Start) inside the IMU pose span."""
    acts = annotation["activities"] if annotation else []
    return [a for a in acts if a["end"] > t_lo and a["start"] < t_hi]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("session", nargs="?", default=DEFAULT_SESSION)
    parser.add_argument(
        "--realign", action="store_true", help="redo the alignment and the Vision pose"
    )
    args = parser.parse_args(argv)

    folder = paths.session_dir(args.session)
    name = folder.name
    annotation = metrics.load_annotation(name)
    video_info = (annotation or {}).get("video", {})
    video = find_video(folder / "video")

    alignment_path = video.parent / "alignment.json"
    if args.realign or not alignment_path.exists():
        video_align.align(
            folder, video, video_info.get("mask_left", 0.0), video_info.get("mirrored", False)
        )
    alignment = json.loads(alignment_path.read_text())
    mirrored = video_info.get("mirrored", alignment.get("mirrored", False))

    t_v, vj = A.vision_joints(vision_frames(video, args.realign), mirrored=mirrored)
    va = A.angles(vj)

    with open(folder / "stream.jsonl") as f:
        stream_start = next(
            json.loads(line) for line in f if '"name": "start"' in line or '"name":"start"' in line
        )
    results = {"session": name, "video": video.name, "mirrored": mirrored, "alignment": alignment}
    results["vision_frames"] = int(len(t_v))
    results["variants"] = {}
    curves = {}
    for wrist_pose in WRIST_POSES:
        session = load_session(folder, wrist_pose=wrist_pose)
        out = mp.run(session, session.locs)
        t_i = A.to_video_time(out.t, stream_start["unix"], alignment)
        ia = A.angles(A.smpl_joints(out.joints))
        shift = t_i[0] - out.t[0]  # video time - seconds after Start
        t_rel = t_v - shift
        excluded = np.zeros(len(t_v), bool)
        for a in windows(annotation, out.t[0], out.t[-1]):
            if a.get("type") == "excluded":
                excluded |= (t_rel >= a["start"]) & (t_rel <= a["end"])
        keep = ~excluded
        r = {
            "overall": {k: A.compare(t_v[keep], va[k][keep], t_i, ia[k]) for k in A.ANGLES},
            "lag_check_s": {
                k: A.best_lag(t_v[keep], va[k][keep], t_i, ia[k]) for k in ("r_shoulder", "r_elbow")
            },
        }
        # Mirroring check: the Watch arm's elevation should match its own side best.
        r["mirror_check_r"] = {
            "same_side": r["overall"]["r_shoulder"].get("r"),
            "other_side": A.compare(t_v[keep], va["l_shoulder"][keep], t_i, ia["r_shoulder"]).get(
                "r"
            ),
        }
        r["per_activity"] = {}
        for a in windows(annotation, out.t[0], out.t[-1]):
            if a.get("type") == "excluded":
                continue
            sel = (t_rel >= a["start"]) & (t_rel <= a["end"])
            r["per_activity"][a["name"]] = {
                k: A.compare(t_v[sel], va[k][sel], t_i, ia[k]) for k in A.ANGLES
            }
        results["variants"][wrist_pose] = r
        curves[wrist_pose] = (t_i - shift, ia)

    res_dir = paths.results_dir(__file__, name)
    (res_dir / "metrics.json").write_text(json.dumps(results, indent=2) + "\n")
    (res_dir / "summary.md").write_text(summary(results))
    plot(res_dir / "angles.png", t_rel, va, curves, annotation, excluded)
    print(summary(results))


def summary(r) -> str:
    lines = [
        f"# E04 on {r['session']}",
        "",
        f"Video `{r['video']}` (mirrored: {r['mirrored']}), {r['vision_frames']} frames with a body;"
        f" alignment offset {r['alignment']['offset_s']:+.2f} s"
        f" (Watch/phone agree: {r['alignment'].get('agree')}).",
        "IMU minus video, degrees. Left-side angles have no sensor on that limb.",
    ]
    for wrist_pose, v in r["variants"].items():
        lines += [
            "",
            f"## Watch calibrated in the {wrist_pose.replace('_', '-')} pose",
            "",
            f"Lag left after alignment (best angle correlation, ±1 s search): {v['lag_check_s']}."
            f" Mirror check (right-shoulder r, same vs other side): {v['mirror_check_r']}.",
            "",
            "| Angle | Frames | Bias | RMSE | MAE | r |",
            "|---|---|---|---|---|---|",
        ]
        for k, m in v["overall"].items():
            if m.get("n"):
                lines.append(
                    f"| {LABEL[k]} | {m['n']} | {m['bias_deg']:+.1f} | {m['rmse_deg']:.1f} | {m['mae_deg']:.1f} | {m['r']} |"
                )
        lines += ["", "RMSE per activity (degrees):", ""]
        lines.append("| Activity | " + " | ".join(A.ANGLES) + " |")
        lines.append("|---|" + "---|" * len(A.ANGLES))
        for act, ms in v["per_activity"].items():
            cells = [f"{ms[k]['rmse_deg']:.0f}" if ms[k].get("n") else "–" for k in A.ANGLES]
            lines.append(f"| {act} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def plot(path, t_rel, va, curves, annotation, excluded):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"standing": "#1f77b4", "arms_out": "#2ca02c"}
    t_lo = min(c[0][0] for c in curves.values())
    t_hi = max(c[0][-1] for c in curves.values())
    fig, axes = plt.subplots(len(A.ANGLES), 1, figsize=(12, 13), sharex=True)
    for ax, k in zip(axes, A.ANGLES):
        for a in windows(annotation, t_lo, t_hi):
            ax.axvspan(
                a["start"],
                a["end"],
                color="#ffdddd" if a.get("type") == "excluded" else "#f0f0f0",
                lw=0,
            )
        ax.plot(
            t_rel[~excluded], va[k][~excluded], ".", ms=2, color="#d62728", label="video (Vision)"
        )
        for wrist_pose, (t, ia) in curves.items():
            ax.plot(
                t, ia[k], "-", lw=1, color=colors[wrist_pose], label=f"IMU, Watch cal. {wrist_pose}"
            )
        ax.set_ylabel("deg")
        ax.set_title(LABEL[k], fontsize=9, loc="left")
    for a in windows(annotation, t_lo, t_hi):
        axes[0].text(
            a["start"], axes[0].get_ylim()[1], a["name"].replace("_", " "), fontsize=7, va="bottom"
        )
    axes[0].legend(loc="upper right", fontsize=7)
    axes[-1].set_xlabel("seconds after Start")
    axes[-1].set_xlim(t_lo, t_hi)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


if __name__ == "__main__":
    main()
