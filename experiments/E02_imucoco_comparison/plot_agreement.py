"""One figure per device combination: model-sensor agreement and motion trajectories for both models.

Run from project/code after run.py:
    .venv/bin/python -m experiments.E02_imucoco_comparison.plot_agreement [SESSION] [--combo rw_rp_h]

Uses the saved outputs (results/<SESSION>/outputs/) and metrics.json; no model is re-run.
Writes results/<SESSION>/agreement_trajectories_<combo>.png with:
- left: trajectories over time (wrist heights, knee flexion, head yaw vs AirPods) and the
  model-vs-sensor angle for every sensor-bearing bone (agreement over time);
- right: the right wrist's path in the frontal plane per activity, and mean model-vs-sensor angle
  per bone when the sensor was a model input vs held out (from the other combinations).
Agreement with the sensors is not error against ground truth; for stream quality (rates, missing
samples) see E03 (see experiments/README.md).
"""

import argparse
import json
from pathlib import Path

import numpy as np

from experiments.common import metrics, paths
from experiments.common import mobileposer_runner as mp
from experiments.common.session import load_session

HERE = Path(__file__).resolve().parent

MODELS = {"MobilePoser": "#1f77b4", "IMUCoCo": "#d62728"}
BONE = {
    "right_wrist": "right forearm (Watch)",
    "right_pocket": "right thigh (phone)",
    "head": "head (AirPods)",
}
ACT_COLORS = {
    "standing_still": "#7f7f7f",
    "jumping_jacks": "#2ca02c",
    "tennis_swings": "#9467bd",
    "squats": "#ff7f0e",
    "head_turns": "#8c564b",
}


def load_output(res, model, combo, body):
    import torch

    d = np.load(res / "outputs" / f"{model}_{combo}.npz")
    glb = body.forward_kinematics(torch.from_numpy(d["pose"]).float())[0].numpy()
    return mp.Output(d["t"], d["pose"], glb, d["joints"], d["tran"])


def held_out_table(all_metrics, locs):
    """bone -> model -> (mean error when the sensor was an input, when held out)."""
    table = {}
    for loc in locs:
        table[loc] = {}
        for model in MODELS:
            inp, out = [], []
            for c in all_metrics["configurations"].values():
                e = c[model]["orientation_error_deg"][loc]["mean"]
                (inp if loc in c["devices"] else out).append(e)
            table[loc][model] = (np.mean(inp), np.mean(out))
    return table


def shade(ax, annotation, label=False):
    for a in annotation["activities"]:
        ax.axvspan(a["start"], a["end"], color=ACT_COLORS.get(a["name"], "gray"), alpha=0.08, lw=0)
        if label:
            ax.text(
                (a["start"] + a["end"]) / 2,
                1.02,
                a["name"].replace("_", " "),
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=8,
                color=ACT_COLORS.get(a["name"], "gray"),
            )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default="20261008-153213-P01")
    parser.add_argument("--combo", default="rw_rp_h")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    res = paths.results_dir(HERE / "run.py", args.session)
    session = load_session(args.session)
    annotation = metrics.load_annotation(session.name)
    all_metrics = json.loads((res / "metrics.json").read_text())
    body = mp.body_model()
    outs = {m: load_output(res, m, args.combo, body) for m in MODELS}
    sigs = {m: metrics.signals(o, metrics.reference(session, len(o.t))) for m, o in outs.items()}
    given = all_metrics["configurations"][args.combo]["devices"]
    t = sigs["MobilePoser"]["t"]

    fig = plt.figure(figsize=(18, 12.5))
    gs = GridSpec(
        4,
        2,
        figure=fig,
        width_ratios=[2.1, 1],
        height_ratios=[1, 1, 1, 1.05],
        hspace=0.42,
        wspace=0.16,
    )
    devices = " + ".join(BONE[l].split("(")[1].rstrip(")") for l in given)
    fig.suptitle(
        f"{session.name}: model-sensor agreement and motion trajectories (devices given to both models: {devices})",
        fontsize=13,
        y=0.93,
    )

    # Motion trajectories over time
    ax0 = ax = fig.add_subplot(gs[0, 0])
    for m, c in MODELS.items():
        ax.plot(t, sigs[m]["wrist_height_right"], color=c, lw=1.2, label=f"{m} right wrist")
        ax.plot(
            t,
            sigs[m]["wrist_height_left"],
            color=c,
            lw=1,
            ls="--",
            label=f"{m} left wrist (no sensor)",
        )
    ax.axhline(-0.05, color="black", lw=0.8, ls=":", label="hanging arm ≈ −0.05 m")
    ax.set_ylabel("wrist height above\npelvis (m)")
    ax.set_title("Motion trajectories", fontsize=11, loc="left", pad=16)
    ax.legend(fontsize=7, ncol=3, loc="upper right")
    shade(ax, annotation, label=True)

    ax = fig.add_subplot(gs[1, 0], sharex=ax0)
    for m, c in MODELS.items():
        ax.plot(
            t,
            (sigs[m]["knee_flexion_right"] + sigs[m]["knee_flexion_left"]) / 2,
            color=c,
            lw=1.2,
            label=m,
        )
    ax.set_ylabel("knee flexion,\nmean of both (deg)")
    ax.legend(fontsize=7, loc="upper left")
    shade(ax, annotation)

    ax = fig.add_subplot(gs[2, 0], sharex=ax0)
    if "head_yaw_airpods" in sigs["MobilePoser"]:
        ax.plot(
            t,
            sigs["MobilePoser"]["head_yaw_airpods"],
            color="black",
            lw=1.6,
            label="AirPods (sensor)",
        )
    for m, c in MODELS.items():
        ax.plot(t, sigs[m]["head_yaw_model"], color=c, lw=1.2, label=m)
    ax.set_ylabel("head yaw\n(deg, + = left)")
    ax.legend(fontsize=7, ncol=3, loc="lower left")
    shade(ax, annotation)

    # Model-sensor agreement over time: model bone vs the sensor on it, one panel per sensor
    row = gs[3, 0].subgridspec(1, len(session.locs), wspace=0.25)
    for i, loc in enumerate(session.locs):
        ax = fig.add_subplot(row[0, i], sharex=ax0)
        for m, c in MODELS.items():
            e = sigs[m][f"orientation_error_{loc}"]
            ax.plot(t, e, color=c, lw=0.6, alpha=0.3)
            ax.plot(
                t,
                np.convolve(e, np.ones(15) / 15, mode="same"),
                color=c,
                lw=1.4,
                label=f"{m}: mean {np.nanmean(e):.0f}°",
            )
        ax.set_ylim(0, min(120, ax.get_ylim()[1]))
        ax.set_title(f"{BONE[loc]} ({'input' if loc in given else 'held out'})", fontsize=9)
        ax.set_xlabel("s after Start")
        if i == 0:
            ax.set_ylabel("model vs sensor\nangle (deg)")
            ax.text(
                0, 1.22, "Model-sensor agreement over time", transform=ax.transAxes, fontsize=11
            )
        ax.legend(fontsize=7, loc="upper left")
        shade(ax, annotation)

    # Right wrist path in the frontal plane, relative to the pelvis, coloured by activity
    paths_row = gs[0:2, 1].subgridspec(1, 2, wspace=0.3)
    for r, (m, c) in enumerate(MODELS.items()):
        ax = fig.add_subplot(paths_row[0, r])
        j = outs[m].joints
        x, y = (
            j[:, metrics.WRIST["right"], 0] - j[:, 0, 0],
            j[:, metrics.WRIST["right"], 1] - j[:, 0, 1],
        )
        for a in annotation["activities"]:
            w = (t >= a["start"]) & (t <= a["end"])
            ax.plot(
                x[w],
                y[w],
                color=ACT_COLORS.get(a["name"], "gray"),
                lw=1,
                label=a["name"].replace("_", " "),
            )
        ax.scatter([0], [0], color="black", s=14, zorder=3)
        ax.annotate("pelvis", (0, 0), textcoords="offset points", xytext=(4, -10), fontsize=7)
        ax.set_xlim(0.35, -0.75)  # viewer faces the subject: subject's right on the viewer's left
        ax.set_ylim(-0.4, 1.0)
        ax.set_aspect("equal")
        ax.set_title(f"{m}", fontsize=10, color=c)
        ax.set_xlabel("subject's left ←  x (m)  → right", fontsize=7)
        ax.grid(alpha=0.3)
        if r == 0:
            ax.set_ylabel("up (m)")
            ax.text(0, 1.12, "Right wrist path, front view", transform=ax.transAxes, fontsize=11)
        else:
            ax.legend(fontsize=6.5, loc="lower right")

    # Consistency summary over all combinations: sensor as input vs held out
    ax = fig.add_subplot(gs[2:4, 1])
    table = held_out_table(all_metrics, session.locs)
    xs, w = np.arange(len(session.locs)), 0.2
    for k, (m, c) in enumerate(MODELS.items()):
        ax.bar(
            xs + (2 * k - 1.5) * w,
            [table[l][m][0] for l in session.locs],
            w,
            color=c,
            label=f"{m}, sensor was an input",
        )
        ax.bar(
            xs + (2 * k - 0.5) * w,
            [table[l][m][1] for l in session.locs],
            w,
            color=c,
            alpha=0.4,
            hatch="//",
            label=f"{m}, sensor held out",
        )
    ax.set_xticks(xs)
    ax.set_xticklabels([BONE[l].replace(" (", "\n(") for l in session.locs], fontsize=8)
    ax.set_ylabel("mean model-vs-sensor angle (deg)")
    ax.set_title("Model-sensor agreement, mean over all 7 combinations", fontsize=11, loc="left")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(axis="y", alpha=0.3)

    fig.text(
        0.125,
        0.045,
        "Agreement = angle between a model bone and the sensor strapped to it: agreement with the sensors, not error "
        "against ground truth. 'Input' rewards copying the sensor, right or wrong; 'held out' tests\n"
        "whether a model predicts a bone it was not given. The current Watch calibration treats a hanging arm as horizontal, "
        "so a low forearm angle can mean a wrongly raised arm: compare the wrist heights\n"
        "with the hanging-arm line (top left). Activity bands: grey standing, green jumping jacks, purple tennis swings, "
        "orange squats, brown head turns.",
        fontsize=8.5,
        va="top",
    )

    out = res / f"agreement_trajectories_{args.combo}.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print("Saved", out)


if __name__ == "__main__":
    main()
