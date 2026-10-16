"""E02: MobilePoser vs IMUCoCo on the same calibrated inputs, for every device subset.

Run from project/code:
    .venv/bin/python experiments/E02_imucoco_comparison/run.py [SESSION] [--no-video] [--configs rw_rp_h,rw_h]

SESSION defaults to the reference recording 20261008-153213-P01. Both models get the same
calibration (common/session.py); MobilePoser runs at 30 Hz, IMUCoCo at 60 Hz (downsampled to 30
for scoring). Writes results/<SESSION>/: metrics.json, summary.md, signals_<combo>.png,
outputs/<model>_<combo>.npz and videos/<combo>.mp4 (MobilePoser | IMUCoCo).
IMUCoCo takes about 4-5 minutes per configuration on a laptop CPU.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import imucoco_runner as ic  # noqa: E402

from common import metrics, paths, render  # noqa: E402
from common import mobileposer_runner as mp  # noqa: E402
from common.session import load_session  # noqa: E402

REFERENCE_SESSION = "20261008-153213-P01"
VIDEO_CONFIGS = [
    "rw_rp_h",
    "rw_h",
]  # full set, and the AirPods + Watch case from the research notes
MODELS = ["MobilePoser", "IMUCoCo"]


def plot(name, sigs, annotation, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [
        ("right wrist height (m)", "wrist_height_right"),
        ("left wrist height (m, no sensor)", "wrist_height_left"),
        ("knee flexion, mean (deg)", None),
        ("head yaw (deg, + = left)", "head_yaw_model"),
    ]
    fig, axes = plt.subplots(len(rows), 1, figsize=(13, 10), sharex=True)
    for ax, (title, key) in zip(axes, rows):
        for model, s in sigs.items():
            y = (s["knee_flexion_right"] + s["knee_flexion_left"]) / 2 if key is None else s[key]
            ax.plot(s["t"], y, lw=1, label=model)
        if key == "head_yaw_model" and "head_yaw_airpods" in sigs["MobilePoser"]:
            s = sigs["MobilePoser"]
            ax.plot(s["t"], s["head_yaw_airpods"], color="black", lw=1.3, label="AirPods (sensor)")
        ax.set_ylabel(title, fontsize=8)
        ax.grid(alpha=0.3)
        if annotation:
            for a in annotation["activities"]:
                ax.axvspan(a["start"], a["end"], color="gray", alpha=0.07)
    axes[0].legend(fontsize=8)
    axes[0].set_title(f"devices: {name}", fontsize=10)
    axes[-1].set_xlabel("s after Start")
    fig.tight_layout()
    fig.savefig(out / f"signals_{name}.png", dpi=90)
    plt.close(fig)


def summary_md(session, results):
    locs = sorted({l for r in results.values() for l in r["MobilePoser"]["orientation_error_deg"]})
    lines = [
        f"# E02 results: {session.name}",
        "",
        "Same calibrated inputs for both models. Bone error: model bone vs the sensor on it (deg, mean).",
        "MobilePoser 'trained' = the device combination is one MobilePoser was trained on.",
        "",
        "## Bone orientation vs sensors",
        "",
        "| Devices | MP trained | " + " | ".join(f"{l}: MP / CoCo" for l in locs) + " |",
        "|---|---|" + "---|" * len(locs),
    ]
    for name, r in results.items():
        cells = [
            f"{r['MobilePoser']['orientation_error_deg'][l]['mean']} / {r['IMUCoCo']['orientation_error_deg'][l]['mean']}"
            for l in locs
        ]
        lines.append(
            f"| `{name}` | {'yes' if r['trained_combo'] else 'no'} | " + " | ".join(cells) + " |"
        )
    lines += [
        "",
        "## Activities (MobilePoser / IMUCoCo)",
        "",
        "| Devices | Rest right wrist (m, hanging = -0.05) | Rest left wrist (m) | JJ reps (of 3) | JJ right wrist peak (m) | JJ left wrist at peak (m) | Squat reps (of 3) | Squat knee peak (deg) | Look L (AirPods 49) | Look R (AirPods -72) | Head yaw RMSE (deg) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    def pair(r, act, key):
        return " / ".join(str(r[m].get("activities", {}).get(act, {}).get(key)) for m in MODELS)

    for name, r in results.items():
        lines.append(
            f"| `{name}` | {pair(r, 'standing_still', 'wrist_height_right_m')} | {pair(r, 'standing_still', 'wrist_height_left_m')} | "
            f"{pair(r, 'jumping_jacks', 'detected_reps')} | {pair(r, 'jumping_jacks', 'peak_wrist_height_m')} | "
            f"{pair(r, 'jumping_jacks', 'peak_other_wrist_height_m')} | {pair(r, 'squats', 'detected_reps')} | "
            f"{pair(r, 'squats', 'peak_knee_flexion_deg')} | {pair(r, 'head_turns', 'model_left_deg')} | "
            f"{pair(r, 'head_turns', 'model_right_deg')} | {pair(r, 'head_turns', 'yaw_rmse_deg')} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default=REFERENCE_SESSION)
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument(
        "--configs", default=None, help="comma-separated combo names (default: every subset)"
    )
    args = parser.parse_args()

    s30, s60 = load_session(args.session), load_session(args.session, rate=ic.RATE)
    annotation = metrics.load_annotation(s30.name)
    out = paths.results_dir(__file__, s30.name)
    (out / "outputs").mkdir(exist_ok=True)
    from itertools import combinations

    configs = [list(c) for r in range(len(s30.locs), 0, -1) for c in combinations(s30.locs, r)]
    if args.configs:
        configs = [c for c in configs if mp.combo_name(c) in args.configs.split(",")]

    results, outputs = {}, {}
    for locs in configs:
        name = mp.combo_name(locs)
        runs = {"MobilePoser": mp.run(s30, locs), "IMUCoCo": ic.run(s60, locs)}
        results[name] = {"devices": locs, "trained_combo": mp.is_trained_combo(locs)}
        sigs = {}
        for model, o in runs.items():
            results[name][model], sigs[model] = metrics.score(o, s30, annotation)
            np.savez_compressed(
                out / "outputs" / f"{model}_{name}.npz",
                t=o.t,
                pose=o.pose,
                joints=o.joints,
                tran=o.tran,
            )
        outputs[name] = runs
        plot(name, sigs, annotation, out)
        print(
            name,
            {
                m: {k: v["mean"] for k, v in results[name][m]["orientation_error_deg"].items()}
                for m in MODELS
            },
            flush=True,
        )
        # Write as we go: IMUCoCo is slow, and partial results are still useful.
        (out / "metrics.json").write_text(
            json.dumps({"session": s30.name, "configurations": results}, indent=2)
        )
        (out / "summary.md").write_text(summary_md(s30, results))

    if not args.no_video:
        videos = out / "videos"
        videos.mkdir(exist_ok=True)
        body = mp.body_model()
        for name in [n for n in VIDEO_CONFIGS if n in outputs]:
            files = [
                render.render_mesh(body, outputs[name][m].pose, videos / f"{name}_{m}.mp4")
                for m in MODELS
            ]
            render.tile(
                files,
                [f"MobilePoser ({name})", f"IMUCoCo ({name})"],
                videos / f"{name}.mp4",
                tile_size=480,
            )
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
