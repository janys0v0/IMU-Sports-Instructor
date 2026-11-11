"""Four methods side by side on Janys 11/05: MobilePoser, OpenSense IK, ridge, GRU.

All use the Watch + pocket phone. Top row: angles (deg); bottom row: elbow and wrist position
(cm, shoulder-anchored in the trunk frame). Ridge and GRU are trained on Janys 10/28 + Tom 10/28 (`both`);
MobilePoser and OpenSense need no training. All are scored on Janys 11/05 against OpenCap.

    .venv/bin/python -m experiments.E08_janys_1105.four_methods   # figures/four_methods.png
"""

import json

import numpy as np

from experiments.E07_pose_methods.colors import anonymize

from .data import OUT
from .figures import FIG, GRID, INK, INK2, METRICS, style

METHODS = [  # scores_all.json key, label, color (E07 colors.py hues)
    ("mobileposer_rw_rp", "MobilePoser (pretrained)", "#008300"),
    ("opensense_watch_phone", "OpenSense IK (no training)", "#eb6834"),
    ("ridge_watch_phone_both", "Ridge (trained on Janys + Tom 10/28)", "#2a78d6"),
    ("gru_watch_phone_both", "GRU (trained on Janys + Tom 10/28)", "#6250d6"),
]
CM = [  # shoulder-anchored in the trunk frame, OpenCap arm lengths (E07 evaluate.py)
    ("elbow_pos_cm", "Elbow position"),
    ("wrist_pos_cm", "Wrist position"),
]
PARTS = [("swing", "During swings (±0.5 s)"), ("all", "All OpenCap minutes")]


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scores = json.loads((OUT / "scores_all.json").read_text())
    style(plt)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9.5), sharey="row", constrained_layout=True)
    rows = [(METRICS, "Median error vs OpenCap (deg)"), (CM, "Median error vs OpenCap (cm)")]
    w = 0.8 / len(METHODS)
    for r, (metrics, ylabel) in enumerate(rows):
        x = np.arange(len(metrics))
        for ax, (part, title) in zip(axes[r], PARTS):
            for j, (key, label, color) in enumerate(METHODS):
                vals = [scores[key][part].get(k, np.nan) for k, _ in metrics]
                xx = x - 0.4 + w * (j + 0.5)
                ax.bar(xx, vals, width=w * 0.9, color=color, label=label)
                for xi, v in zip(xx, vals):
                    ax.text(xi, v + 0.8, f"{v:.0f}", ha="center", fontsize=8.5, color=INK2)
            ax.set_xticks(x)
            ax.set_xticklabels([t.replace(" (deg)", "") for _, t in metrics])
            ax.set_title(title, loc="left", fontsize=10.5, color=INK)
            ax.grid(axis="y", color=GRID)
            ax.set_axisbelow(True)
        axes[r, 0].set_ylabel(ylabel)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.04)
    )
    fig.suptitle("Janys 11/05, Watch + phone: four methods vs OpenCap", x=0.01, ha="left",
                 color=INK, fontsize=11.5)  # fmt: skip
    FIG.mkdir(exist_ok=True)
    anonymize(fig)
    fig.savefig(FIG / "four_methods.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
