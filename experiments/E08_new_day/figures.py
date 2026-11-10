"""E08 figures: 10/28-trained models on 11/05, next to the same models' same-day 10/28 numbers.

One color per training set in every figure; grey = the same model's E07 result for Janys on
10/28 (trained on Tom + Janys's other 10/28 minutes, tested the same day).

    .venv/bin/python -m experiments.E08_new_day.figures     # writes figures/*.png, results/summary.md
"""

import json
from pathlib import Path

import numpy as np

from experiments.E07_pose_methods.data import elevation_plane

from .data import OUT, load

FIG = Path(__file__).resolve().parent / "figures"
E07_SCORES = Path(__file__).resolve().parents[1] / "E07_pose_methods" / "results" / "scores.json"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
TRAIN = {  # training set -> (label, color); fixed order, validated palette slots 1-4
    "janys": ("Janys 10/28", "#2a78d6"),
    "both": ("Janys + Tom 10/28", "#eb6834"),
    "tom": ("Tom 10/28 (new player)", "#1baf7a"),
    "both+half": ("Janys + Tom 10/28 + half of 11/05", "#eda100"),
}
SAME_DAY = ("10/28 same day (E07, + own minutes)", "#b5b4ae")
MODELS = [(m, v) for m in ("gru", "ridge") for v in ("watch", "watch_phone", "watch_phone_airpods")]
VLABEL = {
    "watch": "Watch",
    "watch_phone": "Watch+phone",
    "watch_phone_airpods": "Watch+phone+AirPods",
}
METRICS = [("elbow_mae", "Elbow error (deg)"), ("elevation_mae", "Shoulder elevation error (deg)"),
           ("forearm_dir_deg", "Forearm direction error (deg)")]  # fmt: skip


def style(plt):
    plt.rcParams.update({
        "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#c8c7c2", "axes.labelcolor": INK2, "xtick.color": INK2,
        "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF,
    })  # fmt: skip


def bars(scores, ref, part):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style(plt)
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.2), sharey=True, constrained_layout=True)
    n = len(TRAIN) + 1
    h = 0.8 / n
    y = np.arange(len(MODELS))[::-1]
    for ax, (key, title) in zip(axes, METRICS):
        for yi, (m, v) in zip(y, MODELS):
            vals = [ref.get(f"own_{m}_{v}_personal", {}).get("janys", {}).get(part, {}).get(key)]
            vals += [scores.get(f"{m}_{v}_{t}", {}).get(part, {}).get(key) for t in TRAIN]
            cols = [SAME_DAY[1]] + [c for _, c in TRAIN.values()]
            for j, (val, c) in enumerate(zip(vals, cols)):
                yy = yi + 0.4 - h * (j + 0.5)
                if val is None:
                    continue
                ax.barh(yy, val, height=h * 0.9, color=c)
                ax.text(val + 0.6, yy, f"{val:.0f}", va="center", fontsize=7.5, color=INK2)
        ax.set_title(title, loc="left", fontsize=10.5, color=INK)
        ax.grid(axis="x", color=GRID)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(
        [f"{m.upper() if m == 'gru' else 'Ridge'}, {VLABEL[v]}" for m, v in MODELS]
    )
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c in [SAME_DAY, *TRAIN.values()]]
    labels = [SAME_DAY[0]] + [f"tested on 11/05, trained on {lab}" for lab, _ in TRAIN.values()]
    fig.legend(
        handles, labels, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.09)
    )
    what = (
        "during swings (±0.5 s around each Watch-detected swing)"
        if part == "swing"
        else "over all OpenCap minutes"
    )
    fig.suptitle(
        f"Janys, median error vs OpenCap {what}", x=0.01, ha="left", color=INK, fontsize=11.5
    )
    fig.savefig(FIG / f"errors_{part}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def traces(d, model="gru", variant="watch_phone", n=4, width=3.0):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style(plt)
    sw = [s for s in d["swing_t"] if d["gt_valid"][np.abs(d["t"] - s) < 1.0].mean() > 0.9]
    pick = [sw[int(i)] for i in np.linspace(0, len(sw) - 1, n + 2)[1:-1]]
    ms = {t: np.load(OUT / "janys" / f"method_{model}_{variant}_{t}.npz") for t in TRAIN}
    fig, ax = plt.subplots(2, n, figsize=(4.0 * n, 6), sharey="row", constrained_layout=True)
    for c, s in enumerate(pick):
        m = np.abs(d["t"] - s) < width
        x = d["t"][m] - s
        ax[0, c].plot(x, d["gt_elbow"][m], color=INK, lw=2.6, label="OpenCap")
        ax[1, c].plot(x, d["gt_elev"][m], color=INK, lw=2.6)
        for t, (lab, col) in TRAIN.items():
            ax[0, c].plot(x, ms[t]["elbow"][m], color=col, lw=1.5, label=f"trained on {lab}")
            ev, _ = elevation_plane(ms[t]["hum"][m])
            ax[1, c].plot(x, ev, color=col, lw=1.5)
        for r in range(2):
            ax[r, c].axvline(0, color=GRID, lw=1)
            ax[r, c].grid(axis="y", color=GRID)
        ax[1, c].set_xlabel("s from swing peak")
        ax[0, c].set_title(f"11/05 swing {c + 1}", loc="left", color=INK, fontsize=10)
    ax[0, 0].set_ylabel("elbow flexion (deg)")
    ax[1, 0].set_ylabel("shoulder elevation (deg)")
    h, lab = ax[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.1))
    fig.suptitle(
        f"{model.upper()}, {VLABEL[variant]}: four 11/05 swings", x=0.01, ha="left", color=INK
    )
    fig.savefig(FIG / f"traces_{model}_{variant}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def over_the_day(d, model="gru", variant="watch_phone"):
    """Median elbow error per OpenCap segment against time of day: does the error grow?"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style(plt)
    fig, ax = plt.subplots(figsize=(11, 3.6), constrained_layout=True)
    t0 = d["t"][0]
    for t, (lab, col) in TRAIN.items():
        mm = np.load(OUT / "janys" / f"method_{model}_{variant}_{t}.npz")
        xs, ys = [], []
        for k in np.unique(d["seg"]):
            sel = (d["seg"] == k) & d["gt_valid"] & np.isfinite(mm["elbow"])
            if sel.sum() > 60:
                xs.append((d["t"][sel].mean() - t0) / 60)
                ys.append(np.median(np.abs(mm["elbow"][sel] - d["gt_elbow"][sel])))
        xs, ys = np.array(xs), np.array(ys, float)
        gap = np.r_[False, np.diff(xs) > 3]  # no line across breaks between recordings
        xs, ys = (
            np.insert(xs, np.nonzero(gap)[0], np.nan),
            np.insert(ys, np.nonzero(gap)[0], np.nan),
        )
        ax.plot(xs, ys, "o-", color=col, ms=3.5, lw=1, label=f"trained on {lab}")
    ax.set_xlabel("minutes since the first OpenCap segment (11/05)")
    ax.set_ylabel("elbow error per segment (deg)")
    ax.grid(axis="y", color=GRID)
    ax.legend(frameon=False, fontsize=8.5, ncol=2)
    ax.set_title(
        f"{model.upper()}, {VLABEL[variant]}: error per ~25 s segment across the session",
        loc="left",
        color=INK,
    )
    fig.savefig(FIG / "error_over_session.png", dpi=130)
    plt.close(fig)


def summary(scores, ref):
    rows = ["| Model | Trained on | Elbow | Shoulder elev. | Forearm dir. | Elbow (all) | Elev. (all) |",
            "|---|---|---|---|---|---|---|"]  # fmt: skip
    for m, v in MODELS:
        r = ref.get(f"own_{m}_{v}_personal", {}).get("janys", {})
        name = f"{'GRU' if m == 'gru' else 'Ridge'}, {VLABEL[v]}"
        f = lambda s, k: f"{s[k]:.0f}" if k in s else "–"  # noqa: E731
        sw, al = r.get("swing", {}), r.get("all", {})
        rows.append(f"| {name} | *10/28 same day (E07)* | {f(sw, 'elbow_mae')} | {f(sw, 'elevation_mae')} | "
                    f"{f(sw, 'forearm_dir_deg')} | {f(al, 'elbow_mae')} | {f(al, 'elevation_mae')} |")  # fmt: skip
        for t, (lab, _) in TRAIN.items():
            s = scores.get(f"{m}_{v}_{t}", {})
            sw, al = s.get("swing", {}), s.get("all", {})
            rows.append(f"| {name} | {lab} | {f(sw, 'elbow_mae')} | {f(sw, 'elevation_mae')} | "
                        f"{f(sw, 'forearm_dir_deg')} | {f(al, 'elbow_mae')} | {f(al, 'elevation_mae')} |")  # fmt: skip
    (OUT / "summary.md").write_text(
        "Janys on 11/05, median error vs OpenCap in degrees: swings (±0.5 s) and all OpenCap minutes.\n\n"
        + "\n".join(rows)
        + "\n"
    )


def main():
    FIG.mkdir(exist_ok=True)
    scores = json.loads((OUT / "scores.json").read_text())
    ref = json.loads(E07_SCORES.read_text())
    for part in ("swing", "all"):
        bars(scores, ref, part)
    d = load()
    traces(d)
    over_the_day(d)
    summary(scores, ref)
    print("figures in", FIG)


if __name__ == "__main__":
    main()
