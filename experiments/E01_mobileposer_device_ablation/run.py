"""E01: how much does each device add? MobilePoser on every subset of a session's devices.

Run from project/code:
    .venv/bin/python -m experiments.E01_mobileposer_device_ablation.run [SESSION] [--no-video]

SESSION defaults to the reference recording 20261008-153213-P01. Calibration is done once with
all devices; only the model input changes between configurations. Writes
results/<SESSION>/: metrics.json, summary.md, signals.png, orientation_error.png and
videos/comparison.mp4 (trained configurations side by side).
"""

import argparse
import itertools
import json

import numpy as np

from experiments.common import metrics, paths, render
from experiments.common import mobileposer_runner as mp
from experiments.common.session import load_session

REFERENCE_SESSION = "20261008-153213-P01"


def configurations(locs):
    """Every non-empty device subset, largest first."""
    return [list(c) for r in range(len(locs), 0, -1) for c in itertools.combinations(locs, r)]


def plot(results, signals, annotation, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(results)
    rows = [
        ("right wrist height above pelvis (m)", "wrist_height_right"),
        ("knee flexion, mean of both (deg)", None),
        ("head yaw (deg, + = left)", "head_yaw_model"),
    ]
    fig, axes = plt.subplots(len(rows), 1, figsize=(13, 9), sharex=True)
    for ax, (title, key) in zip(axes, rows):
        for name in names:
            s = signals[name]
            y = (s["knee_flexion_right"] + s["knee_flexion_left"]) / 2 if key is None else s[key]
            style = "-" if results[name]["trained_combo"] else ":"
            ax.plot(s["t"], y, style, lw=1, label=name)
        if key == "head_yaw_model":
            ref = next((s for s in signals.values() if "head_yaw_airpods" in s), None)
            if ref is not None:
                ax.plot(
                    ref["t"],
                    ref["head_yaw_airpods"],
                    color="black",
                    lw=1.5,
                    label="AirPods (sensor)",
                )
        ax.set_ylabel(title, fontsize=8)
        ax.grid(alpha=0.3)
        if annotation:
            for a in annotation["activities"]:
                ax.axvspan(a["start"], a["end"], color="gray", alpha=0.07)
                if ax is axes[0]:
                    ax.text(a["start"] + 0.3, ax.get_ylim()[1], a["name"], fontsize=7, va="top")
    axes[0].legend(fontsize=7, ncol=4, loc="lower right")
    axes[-1].set_xlabel("s after Start  (solid: trained combination, dotted: untrained)")
    fig.tight_layout()
    fig.savefig(out / "signals.png", dpi=90)
    plt.close(fig)

    locs = sorted({loc for r in results.values() for loc in r["metrics"]["orientation_error_deg"]})
    fig, ax = plt.subplots(figsize=(11, 4))
    width = 0.8 / len(names)
    for i, name in enumerate(names):
        vals = [results[name]["metrics"]["orientation_error_deg"][loc]["mean"] for loc in locs]
        ax.bar(
            np.arange(len(locs)) + i * width,
            vals,
            width,
            label=name,
            hatch=None if results[name]["trained_combo"] else "//",
        )
    ax.set_xticks(np.arange(len(locs)) + 0.4 - width / 2)
    ax.set_xticklabels([f"{loc} bone" for loc in locs])
    ax.set_ylabel("model vs sensor orientation (deg, mean)")
    ax.legend(fontsize=7, ncol=4)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "orientation_error.png", dpi=90)
    plt.close(fig)


def summary_md(session, results, annotation):
    locs = sorted({loc for r in results.values() for loc in r["metrics"]["orientation_error_deg"]})
    lines = [
        f"# E01 results: {session.name}",
        "",
        "Model: MobilePoser (pretrained weights, offline). Calibration done once with all devices.",
        "Orientation error: angle between the model's bone and the sensor on it, over the whole session.",
        "",
        "| Devices given to the model | Trained combo | "
        + " | ".join(f"{l} bone err (deg)" for l in locs)
        + " |",
        "|---|---|" + "---|" * len(locs),
    ]
    for name, r in results.items():
        errs = [str(r["metrics"]["orientation_error_deg"][l]["mean"]) for l in locs]
        lines.append(
            f"| `{name}` | {'yes' if r['trained_combo'] else '**no**'} | " + " | ".join(errs) + " |"
        )
    if annotation:
        lines += [
            "",
            "## Activities",
            "",
            "| Devices | Rest wrist R / L (m, hanging = -0.05) | JJ reps | JJ wrist peak (m) | Squat reps | Squat knee peak (deg) | Look L model/AirPods | Look R model/AirPods | Head yaw RMSE (deg) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name, r in results.items():
            a = r["metrics"]["activities"]
            jj, sq, ht = a.get("jumping_jacks", {}), a.get("squats", {}), a.get("head_turns", {})
            st = a.get("standing_still", {})
            lines.append(
                f"| `{name}` | {st.get('wrist_height_right_m')} / {st.get('wrist_height_left_m')} | {jj.get('detected_reps')} / {jj.get('reported_reps')} | {jj.get('peak_wrist_height_m')} | "
                f"{sq.get('detected_reps')} / {sq.get('reported_reps')} | {sq.get('peak_knee_flexion_deg')} | "
                f"{ht.get('model_left_deg')} / {ht.get('airpods_left_deg')} | "
                f"{ht.get('model_right_deg')} / {ht.get('airpods_right_deg')} | {ht.get('yaw_rmse_deg')} |"
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default=REFERENCE_SESSION)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()

    session = load_session(args.session)
    annotation = metrics.load_annotation(session.name)
    out = paths.results_dir(__file__, session.name)
    results, signals, outputs = {}, {}, {}
    for locs in configurations(session.locs):
        name = mp.combo_name(locs)
        output = mp.run(session, locs)
        m, sig = metrics.score(output, session, annotation)
        results[name] = {"devices": locs, "trained_combo": mp.is_trained_combo(locs), "metrics": m}
        signals[name], outputs[name] = sig, output
        print(
            f"{name:10s} trained={results[name]['trained_combo']!s:5s} "
            f"err={ {k: v['mean'] for k, v in m['orientation_error_deg'].items()} }"
        )

    calib = {loc: session.segments[0].devices[loc].passed for loc in session.locs}
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "session": session.name,
                "segments": len(session.segments),
                "calibration_passed": calib,
                "frames": int(sum(len(s.t) for s in session.segments)),
                "configurations": results,
            },
            indent=2,
        )
    )
    (out / "summary.md").write_text(summary_md(session, results, annotation))
    plot(results, signals, annotation, out)

    if not args.no_video:
        videos = out / "videos"
        videos.mkdir(exist_ok=True)
        trained = [n for n in results if results[n]["trained_combo"]]
        body = mp.body_model()
        files = [render.render_mesh(body, outputs[n].pose, videos / f"{n}.mp4") for n in trained]
        render.tile(files, trained, videos / "comparison.mp4")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
