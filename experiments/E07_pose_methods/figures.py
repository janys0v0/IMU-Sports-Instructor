"""E07 report figures (PNG, light theme) from results/scores.json and the method files.

.venv/bin/python -m experiments.E07_pose_methods.figures      # writes figures/*.png
"""

import json
from pathlib import Path

import numpy as np

from .common import OUT, load, load_method
from .data import PLAYERS, elevation_plane

FIG = Path(__file__).resolve().parent / "figures"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
FAMILY_COLORS = {
    "Geometric": "#2a78d6",
    "OpenSense": "#1baf7a",
    "Constraint": "#eda100",
    "Published model": "#eb6834",
    "Ours (trained)": "#e87ba4",
    "Truth": "#2b2b2b",
}

# method -> (short label, family); the report's line-up, in display order
LINEUP = {
    "watch_static_trunk": ("Watch orientation, trunk fixed", "Geometric"),
    "direct_trunk_upper_watch": ("Chest+upper arm+Watch, raw headings", "Geometric"),
    "aligned_trunk_upper_watch": ("Chest+upper arm+Watch, constraint-aligned", "Geometric"),
    "qmt_trunk_upper_watch": ("Chest+upper arm+Watch, qmt heading correction", "Geometric"),
    "qmt_trunk_upper_watch_rest18": ("  same, hanging elbow = 18 deg (elbow only)", "Geometric"),
    "opensense_trunk_upper_watch_phone": ("OpenSense IK, chest+upper arm+Watch+phone", "OpenSense"),
    "opensense_watch_phone": ("OpenSense IK, Watch+phone", "OpenSense"),
    "constraint_watch_static_trunk": ("Joint limits + effort, Watch only", "Constraint"),
    "constraint_watch_swing": ("Joint limits, swing-aware, Watch only", "Constraint"),
    "wearmocap_watch": ("WearMoCap (pretrained), Watch", "Published model"),
    "mobileposer_rw_rp_h": ("MobilePoser, Watch+phone+AirPods", "Published model"),
    "mobileposer_rw_rp": ("MobilePoser, Watch+phone", "Published model"),
    "imucoco_rw_rp_h": ("IMUCoCo, Watch+phone+AirPods", "Published model"),
    "imucoco_rw_rp_h_upperarm_chest": ("IMUCoCo, + upper arm + chest", "Published model"),
    "own_ridge_watch_xplayer": ("Ridge, Watch (other player)", "Ours (trained)"),
    "own_gru_watch_xplayer": ("GRU, Watch (other player)", "Ours (trained)"),
    "own_gru_watch_phone_xplayer": ("GRU, Watch+phone (other player)", "Ours (trained)"),
    "own_gru_watch_phone_personal": ("GRU, Watch+phone (+own minutes)", "Ours (trained)"),
    "own_ridge_watch_phone_personal": ("Ridge, Watch+phone (+own minutes)", "Ours (trained)"),
    "own_gru_watch_personal": ("GRU, Watch (+own minutes)", "Ours (trained)"),
    "own_ridge_allsensors_xplayer": ("Ridge, all sensors (other player)", "Ours (trained)"),
    "own_ridge_allsensors_personal": ("Ridge, all sensors (+own half)", "Ours (trained)"),
    "own_gru_allsensors_personal": ("GRU, all sensors (+own half)", "Ours (trained)"),
}
METRICS = [
    ("elbow_mae", "Elbow flexion error (deg)"),
    ("elevation_mae", "Shoulder elevation error (deg)"),
    ("forearm_incl_mae", "Forearm inclination error (deg)"),
    ("forearm_dir_deg", "Forearm direction error (deg)"),
]


def style(plt):
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.edgecolor": "#c8c7c2",
            "axes.labelcolor": INK2,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": SURF,
            "axes.facecolor": SURF,
        }
    )


def bars(scores, part):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style(plt)
    names = [n for n in LINEUP if n in scores]
    fig, axes = plt.subplots(
        1, len(METRICS), figsize=(17, 0.42 * len(names) + 1.6), sharey=True, constrained_layout=True
    )
    y = np.arange(len(names))[::-1]
    for ax, (key, title) in zip(axes, METRICS):
        for yi, n in zip(y, names):
            vals = [scores[n].get(p, {}).get(part, {}).get(key) for p in PLAYERS]
            vals = [v for v in vals if v is not None]
            if not vals:
                ax.text(1, yi, "n/a", va="center", color=INK2, fontsize=8)
                continue
            col = FAMILY_COLORS[LINEUP[n][1]]
            ax.barh(yi, np.mean(vals), color=col, height=0.62)
            for v, mk in zip(vals, ("o", "s")):
                ax.plot(v, yi, mk, color="white", ms=4.5, mec=INK, mew=0.8)
            ax.text(
                np.mean(vals) + 1, yi, f"{np.mean(vals):.0f}", va="center", fontsize=8, color=INK
            )
        ax.set_title(title, loc="left", fontsize=10, color=INK)
        ax.grid(axis="x", color=GRID)
        ax.set_xlim(0, max(10, ax.get_xlim()[1]))
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([LINEUP[n][0] for n in names])
    for lab, n in zip(axes[0].get_yticklabels(), names):
        lab.set_color(FAMILY_COLORS[LINEUP[n][1]])
    what = (
        "during swings (±0.5 s around each Watch-detected swing)"
        if part == "swing"
        else "over the whole play blocks"
    )
    fig.suptitle(
        f"Median error vs OpenCap {what}. Bar = mean of the two players; circle = Janys, square = Tom.",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.savefig(FIG / f"errors_{part}.png", dpi=130)
    plt.close(fig)


def traces(player, names, around, width=3.0):
    """Elbow and shoulder elevation around a few swings: OpenCap vs methods."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style(plt)
    d = load(player)
    cols = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
    fig, ax = plt.subplots(
        2, len(around), figsize=(4.2 * len(around), 6), sharey="row", constrained_layout=True
    )
    for c, s in enumerate(around):
        m = np.abs(d["t"] - s) < width
        x = d["t"][m] - s
        gt_ok = d["gt_valid"][m]
        ax[0, c].plot(
            x, np.where(gt_ok, d["gt_elbow"][m], np.nan), color=INK, lw=2.4, label="OpenCap"
        )
        ax[1, c].plot(x, np.where(gt_ok, d["gt_elev"][m], np.nan), color=INK, lw=2.4)
        for k, n in enumerate(names):
            mm = load_method(player, n)
            ax[0, c].plot(
                x, mm["elbow"][m], color=cols[k % len(cols)], lw=1.5, label=LINEUP.get(n, (n,))[0]
            )
            if np.isfinite(mm["hum"][m]).any():
                ev, _ = elevation_plane(mm["hum"][m])
                ax[1, c].plot(x, ev, color=cols[k % len(cols)], lw=1.5)
        for r in range(2):
            ax[r, c].axvline(0, color=GRID, lw=1)
            ax[r, c].grid(axis="y", color=GRID)
        ax[1, c].set_xlabel("s from swing peak")
        ax[0, c].set_title(
            f"{player.capitalize()}, swing {c + 1}", loc="left", color=INK, fontsize=10
        )
    ax[0, 0].set_ylabel("elbow flexion (deg)")
    ax[1, 0].set_ylabel("shoulder elevation (deg)")
    h, lab = ax[0, 0].get_legend_handles_labels()
    fig.legend(
        h,
        lab,
        loc="lower center",
        ncol=min(4, len(lab)),
        frameon=False,
        fontsize=9,
        bbox_to_anchor=(0.5, -0.07),
    )
    fig.savefig(FIG / f"traces_{player}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def per_swing(names):
    """Elbow error at each swing's peak (±0.15 s median), per method, both players."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style(plt)
    data, labels = [], []
    for n in names:
        errs = []
        for p in PLAYERS:
            d = load(p)
            try:
                mm = load_method(p, n)
            except FileNotFoundError:
                continue
            for s in d["swing_t"]:
                w = (np.abs(d["t"] - s) < 0.15) & d["gt_valid"] & np.isfinite(mm["elbow"])
                if w.sum() >= 3:
                    errs.append(np.median(np.abs(mm["elbow"][w] - d["gt_elbow"][w])))
        if errs:
            data.append(errs)
            labels.append(LINEUP.get(n, (n,))[0])
    fig, ax = plt.subplots(figsize=(11, 0.45 * len(data) + 1.4), constrained_layout=True)
    bp = ax.boxplot(data[::-1], vert=False, widths=0.55, patch_artist=True, showfliers=False)
    for patch, n in zip(bp["boxes"], [n for n in names][::-1][: len(data)]):
        patch.set_facecolor(FAMILY_COLORS[LINEUP.get(n, ("", "Geometric"))[1]])
        patch.set_alpha(0.75)
    ax.set_yticklabels(labels[::-1])
    ax.set_xlabel("elbow error at the swing peak (deg, one value per swing)")
    ax.grid(axis="x", color=GRID)
    ax.set_title(
        "Per-swing elbow error (both players; whiskers 5-95 % range)", loc="left", color=INK
    )
    fig.savefig(FIG / "per_swing_elbow.png", dpi=130)
    plt.close(fig)


def main():
    FIG.mkdir(exist_ok=True)
    scores = json.loads((OUT / "scores.json").read_text())
    for part in ("swing", "all"):
        bars(scores, part)
    best = [
        n
        for n in (
            "aligned_trunk_upper_watch",
            "opensense_trunk_upper_watch_phone",
            "constraint_watch_static_trunk",
            "wearmocap_watch",
            "mobileposer_rw_rp_h",
            "imucoco_rw_rp_h_upperarm_chest",
            "own_gru_watch_phone_xplayer",
        )
        if all((OUT / p / f"method_{n}.npz").exists() for p in PLAYERS)
    ]
    for p in PLAYERS:
        d = load(p)
        sw = [s for s in d["swing_t"] if d["gt_valid"][np.abs(d["t"] - s) < 1.0].mean() > 0.9]
        pick = [sw[int(i)] for i in np.linspace(0, len(sw) - 1, min(3, len(sw)))]
        traces(p, best[:6], pick)
    per_swing([n for n in LINEUP if all((OUT / p / f"method_{n}.npz").exists() for p in PLAYERS)])
    write_summary()
    print("figures in", FIG)


def summary_table(scores, part="swing"):
    """Markdown table: mean of the two players (Janys / Tom in brackets) for the line-up."""
    keys = [
        ("elbow_mae", "Elbow"),
        ("elevation_mae", "Shoulder elev."),
        ("forearm_incl_mae", "Forearm incl."),
        ("forearm_dir_deg", "Forearm dir."),
        ("upper_arm_dir_deg", "Upper-arm dir."),
    ]
    rows = [
        "| Family | Method | " + " | ".join(k[1] for k in keys) + " |",
        "|---|---|" + "---|" * len(keys),
    ]
    for n, (lab, fam) in LINEUP.items():
        if n not in scores:
            continue
        cells = []
        for k, _ in keys:
            v = [scores[n].get(p, {}).get(part, {}).get(k) for p in PLAYERS]
            if all(x is None for x in v):
                cells.append("–")
            else:
                vv = [x for x in v if x is not None]
                cells.append(
                    f"**{np.mean(vv):.0f}** ({' / '.join('–' if x is None else f'{x:.0f}' for x in v)})"
                )
        rows.append(f"| {fam} | {lab} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def write_summary():
    scores = json.loads((OUT / "scores.json").read_text())
    md = [
        "# E07 scores (generated by figures.py)",
        "",
        "Median absolute error vs OpenCap in degrees: mean of the two players, (Janys / Tom).",
        "",
        "## During swings (±0.5 s around each swing)",
        "",
        summary_table(scores, "swing"),
        "",
        "## Whole play blocks",
        "",
        summary_table(scores, "all"),
        "",
    ]
    (OUT / "summary.md").write_text("\n".join(md))


if __name__ == "__main__":
    main()
