"""MobilePoser vs IMUCoCo: per-frame model-vs-sensor angle plotted against each other.

Run from project/code after run.py:
    .venv/bin/python experiments/E02_imucoco_comparison/plot_error_scatter.py [SESSION]

For every sensor-bearing bone (head, right thigh, right forearm), each point is one 30 Hz frame:
x = MobilePoser's angle from the sensor, y = IMUCoCo's. Below the diagonal, IMUCoCo is closer to
the sensor; above, MobilePoser. Colour = annotated activity. "Input" / "held out" says whether the
models were given that sensor. Axes are scaled to the annotated routine; points beyond them
(mostly sitting down after the routine) are drawn on the edge. Statistics use all frames. These are angles from the sensors (agreement), not errors against
ground truth. Reads saved outputs only. Writes results/<SESSION>/:
- error_scatter_rw_rp_h.png   the full device set, large
- error_scatter_all.png       rows = all 7 device combinations
"""

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import metrics, paths  # noqa: E402
from common import mobileposer_runner as mp  # noqa: E402
from common.session import load_session  # noqa: E402

COMBOS = ["rw_rp_h", "rw_rp", "rp_h", "rp", "rw_h", "rw", "h"]
LABEL = {
    "rw_rp_h": "Watch+phone+AirPods",
    "rw_rp": "Watch+phone",
    "rp_h": "phone+AirPods",
    "rp": "phone",
    "rw_h": "Watch+AirPods",
    "rw": "Watch",
    "h": "AirPods",
}
TRAINED = {"rw_rp_h", "rw_rp", "rp_h", "rp"}
BONES = {
    "head": "head (AirPods)",
    "right_pocket": "right thigh (phone)",
    "right_wrist": "right forearm (Watch)",
}
GIVEN = {"head": "h", "right_pocket": "rp", "right_wrist": "rw"}
ACT_COLORS = {
    "standing_still": "#7f7f7f",
    "jumping_jacks": "#2ca02c",
    "tennis_swings": "#9467bd",
    "squats": "#ff7f0e",
    "head_turns": "#8c564b",
}


def angles(res, combo, session, body):
    """bone -> (MobilePoser angle, IMUCoCo angle) per frame, plus the time axis."""
    import torch

    out = {}
    for model in ("MobilePoser", "IMUCoCo"):
        d = np.load(res / "outputs" / f"{model}_{combo}.npz")
        glb = body.forward_kinematics(torch.from_numpy(d["pose"]).float())[0].numpy()
        o = mp.Output(d["t"], d["pose"], glb, d["joints"], d["tran"])
        out[model] = metrics.signals(o, metrics.reference(session, len(o.t)))
    n = min(len(out["MobilePoser"]["t"]), len(out["IMUCoCo"]["t"]))
    return out["MobilePoser"]["t"][:n], {
        b: (
            out["MobilePoser"][f"orientation_error_{b}"][:n],
            out["IMUCoCo"][f"orientation_error_{b}"][:n],
        )
        for b in BONES
    }


def activity_colors(t, annotation):
    colors = np.array(["#cccccc"] * len(t), dtype=object)
    for a in annotation["activities"]:
        colors[(t >= a["start"]) & (t <= a["end"])] = ACT_COLORS.get(a["name"], "gray")
    return colors


def in_routine(t, annotation):
    return np.any([(t >= a["start"]) & (t <= a["end"]) for a in annotation["activities"]], axis=0)


def panel(ax, x, y, colors, title, lim, small=False):
    below, r = np.mean(y < x) * 100, np.corrcoef(x, y)[0, 1]
    mx, my = np.median(x), np.median(y)
    ax.scatter(
        np.minimum(x, lim), np.minimum(y, lim), c=list(colors), s=3 if small else 6, alpha=0.5, lw=0
    )
    ax.plot([0, lim], [0, lim], color="black", lw=0.8)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    txt = (
        f"median MP {mx:.0f}° / CoCo {my:.0f}°\nCoCo closer in {below:.0f}% of frames\nr = {r:.2f}"
    )
    ax.text(
        0.97,
        0.03,
        txt,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=6.5 if small else 8,
        bbox=dict(facecolor="white", alpha=0.8, lw=0),
    )
    ax.set_title(title, fontsize=8 if small else 10)


def legend(fig, annotation, y):
    from matplotlib.lines import Line2D

    handles = [
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            color=ACT_COLORS.get(a["name"], "gray"),
            label=a["name"].replace("_", " "),
        )
        for a in annotation["activities"]
    ]
    handles.append(
        Line2D([], [], marker="o", ls="", color="#cccccc", label="other (before / after routine)")
    )
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=len(handles),
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, y),
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default="20261008-153213-P01")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    res = paths.results_dir(HERE / "run.py", args.session)
    session = load_session(args.session)
    annotation = metrics.load_annotation(session.name)
    body = mp.body_model()
    data = {c: angles(res, c, session, body) for c in COMBOS}

    # Full device set, large
    t, a = data["rw_rp_h"]
    colors = activity_colors(t, annotation)
    routine = in_routine(t, annotation)
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.2))
    for ax, (b, name) in zip(axes, BONES.items()):
        x, y = a[b]
        panel(
            ax,
            x,
            y,
            colors,
            f"{name}: sensor was an input",
            lim=max(60, np.percentile(np.r_[x[routine], y[routine]], 99.5)),
        )
        ax.set_xlabel("MobilePoser: angle from sensor (deg)")
    axes[0].set_ylabel("IMUCoCo: angle from sensor (deg)")
    fig.suptitle(
        f"{session.name}: model-vs-sensor angle per frame, MobilePoser vs IMUCoCo "
        f"(devices: {LABEL['rw_rp_h']}). Below the diagonal = IMUCoCo closer to the sensor.",
        fontsize=11,
    )
    legend(fig, annotation, -0.01)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(res / "error_scatter_rw_rp_h.png", dpi=110, bbox_inches="tight")
    plt.close(fig)

    # All combinations: rows = combos, columns = bones; shared axis limits per column
    lims = {
        b: max(
            60,
            np.percentile(
                np.concatenate(
                    [
                        np.r_[
                            data[c][1][b][0][in_routine(data[c][0], annotation)],
                            data[c][1][b][1][in_routine(data[c][0], annotation)],
                        ]
                        for c in COMBOS
                    ]
                ),
                99.5,
            ),
        )
        for b in BONES
    }
    fig, axes = plt.subplots(len(COMBOS), 3, figsize=(11, 3.3 * len(COMBOS)))
    for r, c in enumerate(COMBOS):
        t, a = data[c]
        colors = activity_colors(t, annotation)
        for k, (b, name) in enumerate(BONES.items()):
            role = "input" if GIVEN[b] in c.split("_") else "held out"
            panel(
                axes[r, k],
                *a[b],
                colors,
                f"{name.split(' (')[0]} ({role})",
                lim=lims[b],
                small=True,
            )
            if r == len(COMBOS) - 1:
                axes[r, k].set_xlabel("MobilePoser angle (deg)", fontsize=8)
        mark = "" if c in TRAINED else "  *MobilePoser untrained"
        axes[r, 0].set_ylabel(
            f"{LABEL[c]}{mark}\n\nIMUCoCo angle (deg)",
            fontsize=8,
            color="black" if c in TRAINED else "#b22222",
        )
    fig.suptitle(
        f"{session.name}: MobilePoser vs IMUCoCo angle from each sensor, every device combination\n"
        "below the diagonal = IMUCoCo closer to the sensor",
        fontsize=11,
    )
    legend(fig, annotation, 0.0)
    fig.tight_layout(rect=(0, 0.015, 1, 0.975))
    fig.savefig(res / "error_scatter_all.png", dpi=100, bbox_inches="tight")
    print("Saved", res / "error_scatter_rw_rp_h.png", "and", res / "error_scatter_all.png")


if __name__ == "__main__":
    main()
