"""Cross-session tests: does a second Janys day help on the 10/28 sessions?

Each split trains E07's own models (ridge, bidirectional GRU) on some sessions and tests on one
10/28 session it never saw. Test sets are E07's `dataset_full` (every OpenCap-covered 10/28
Calibrate segment): Tom 10/28 (8.9 min) and Janys 10/28 (17.0 min).

- `j1028+j1105>tom`: Janys 10/28 + Janys 11/05, tested on Tom 10/28;
  baseline `j1028>tom` (Janys 10/28 only, E07's cross-player case).
- `j1105+tom>j1028`: Janys 11/05 + Tom 10/28, tested on Janys 10/28;
  baseline `tom>j1028` (Tom only) and `j1105>j1028` (Janys 11/05 only).

    .venv/bin/python -m experiments.E08_janys_1105.cross [ridge] [gru]   # writes results/cross.json
    .venv/bin/python -m experiments.E08_janys_1105.cross figures   # figures/cross_*.png, results/cross.md
    .venv/bin/python -m experiments.E08_janys_1105.cross rescore   # rescore saved predictions

Colors follow the training set: Janys 10/28 and Tom 10/28 as in `figures.TRAIN`.
"""

import json
import sys

import numpy as np

from experiments.E07_pose_methods import learned_own as L
from experiments.E07_pose_methods.colors import anonymize
from experiments.E07_pose_methods.common import elbow_from_dirs
from experiments.E07_pose_methods.data import load as load07
from experiments.E07_pose_methods.evaluate import score

from .data import OUT, load
from .figures import FIG, GRID, INK, INK2, METRICS, MODELS, TRAIN, VLABEL, style
from .run import VARIANTS, fit_predict

SPLITS = {  # name: (training sessions, test session)
    "j1028>tom": (["j1028"], "tom"),
    "j1028+j1105>tom": (["j1028", "j1105"], "tom"),
    "tom>j1028": (["tom"], "j1028"),
    "j1105>j1028": (["j1105"], "j1028"),
    "j1105+tom>j1028": (["j1105", "tom"], "j1028"),
}
TRAINED_ON = {  # training sessions -> (label, color)
    "j1028": (TRAIN["janys"][0], TRAIN["janys"][1]),
    "j1028+j1105": ("Janys 10/28 + Janys 11/05", "#eda100"),
    "tom": (TRAIN["tom"][0], TRAIN["tom"][1]),
    "j1105": ("Janys 11/05", "#eb6834"),
    "j1105+tom": ("Janys 11/05 + Tom 10/28", "#7a2e8f"),
}
TESTS = {"tom": "Tom 10/28", "j1028": "Janys 10/28"}
PRED = OUT / "cross"  # saved predictions, so a scoring change needs no retraining (not committed)


def run(model, variant, train, test, sessions):
    devs = VARIANTS[variant]
    sets = [sessions[s] for s in train]
    te = sessions[test]
    P = fit_predict(
        model,
        [L.features(s, devs) for s in sets],
        [L.targets(s) for s in sets],
        [s["gt_valid"] for s in sets],
        [s["seg"] + 1000 * i for i, s in enumerate(sets)],
        L.features(te, devs),
        te["seg"],
    )
    hum, fore = L.unit_pair(P)
    m = {"hum": hum, "fore": fore, "elbow": elbow_from_dirs(hum, fore)}
    m["valid"] = np.isfinite(fore).all(1)
    PRED.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(PRED / f"{model}_{variant}_{'_'.join(train)}_to_{test}.npz", **m)
    return score(te, m)


def figure(scores, part):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style(plt)
    fig, axes = plt.subplots(2, 3, figsize=(16, 10.5), sharey=True, constrained_layout=True)
    y = np.arange(len(MODELS))[::-1]
    for row, (test, tlabel) in enumerate(TESTS.items()):
        splits = [sp for sp, (_, t) in SPLITS.items() if t == test]
        h = 0.8 / len(splits)
        for ax, (key, title) in zip(axes[row], METRICS):
            for yi, (m, v) in zip(y, MODELS):
                for j, sp in enumerate(splits):
                    val = scores.get(f"{m}_{v}_{sp}", {}).get(part, {}).get(key)
                    if val is None:
                        continue
                    yy = yi + 0.4 - h * (j + 0.5)
                    ax.barh(yy, val, height=h * 0.9, color=TRAINED_ON[sp.split(">")[0]][1])
                    ax.text(val + 0.6, yy, f"{val:.0f}", va="center", fontsize=7.5, color=INK2)
            ax.set_title(f"Tested on {tlabel}: {title}", loc="left", fontsize=10.5, color=INK)
            ax.grid(axis="x", color=GRID)
        axes[row, 0].set_yticks(y)
        axes[row, 0].set_yticklabels(
            [f"{'GRU' if m == 'gru' else 'Ridge'}, {VLABEL[v]}" for m, v in MODELS]
        )
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c in TRAINED_ON.values()]
    labels = [f"trained on {lab}" for lab, _ in TRAINED_ON.values()]
    fig.legend(
        handles, labels, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, -0.04)
    )
    what = (
        "during swings (±0.5 s around each Watch-detected swing)"
        if part == "swing"
        else "over all OpenCap minutes"
    )
    fig.suptitle(f"Cross-session tests on 10/28, median error vs OpenCap {what}", x=0.01, ha="left",
                 color=INK, fontsize=11.5)  # fmt: skip
    FIG.mkdir(exist_ok=True)
    anonymize(fig)
    fig.savefig(FIG / f"cross_{part}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def table(scores):
    rows = ["| Model | Tested on | Trained on | Elbow | Shoulder elev. | Forearm dir. | Elbow (all) | Elev. (all) |",
            "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    f = lambda s, k: f"{s[k]:.0f}" if k in s else "–"  # noqa: E731
    for m, v in MODELS:
        name = f"{'GRU' if m == 'gru' else 'Ridge'}, {VLABEL[v]}"
        for sp, (_, test) in SPLITS.items():
            s = scores.get(f"{m}_{v}_{sp}", {})
            sw, al = s.get("swing", {}), s.get("all", {})
            rows.append(f"| {name} | {TESTS[test]} | {TRAINED_ON[sp.split('>')[0]][0]} | {f(sw, 'elbow_mae')} | "
                        f"{f(sw, 'elevation_mae')} | {f(sw, 'forearm_dir_deg')} | {f(al, 'elbow_mae')} | "
                        f"{f(al, 'elevation_mae')} |")  # fmt: skip
    (OUT / "cross.md").write_text(
        "Cross-session tests on 10/28, median error vs OpenCap in degrees: swings (±0.5 s) and all "
        "OpenCap minutes.\n\n" + "\n".join(rows) + "\n"
    )


def main():
    if "figures" in sys.argv:
        scores = json.loads((OUT / "cross.json").read_text())
        for part in ("swing", "all"):
            figure(scores, part)
        table(scores)
        return
    models = [x for x in ("ridge", "gru") if x in sys.argv] or ["ridge", "gru"]
    if "rescore" in sys.argv:  # from the saved predictions
        sessions = {"j1028": load07("janys", full=True), "tom": load07("tom", full=True)}
        path = OUT / "cross.json"
        scores = json.loads(path.read_text())
        for name in scores:
            model, rest = name.split("_", 1)
            split = rest.rsplit("_", 1)[1]
            variant = rest.rsplit("_", 1)[0]
            train, test = SPLITS[split]
            z = np.load(PRED / f"{model}_{variant}_{'_'.join(train)}_to_{test}.npz")
            scores[name] = score(
                sessions[test], {k: z[k] for k in ("hum", "fore", "elbow", "valid")}
            )
        path.write_text(json.dumps(scores, indent=1) + "\n")
        return
    sessions = {
        "j1028": load07("janys", full=True),
        "tom": load07("tom", full=True),
        "j1105": load(),
    }
    path = OUT / "cross.json"
    scores = json.loads(path.read_text()) if path.exists() else {}
    for model in models:
        for variant in VARIANTS:
            for split, (train, test) in SPLITS.items():
                s = run(model, variant, train, test, sessions)
                name = f"{model}_{variant}_{split}"
                scores[name] = s
                path.write_text(json.dumps(scores, indent=1) + "\n")
                sw = s.get("swing", {})
                print(
                    f"{name:40s} swing: elbow {sw.get('elbow_mae', np.nan):5.1f}  elev "
                    f"{sw.get('elevation_mae', np.nan):5.1f}  fore dir {sw.get('forearm_dir_deg', np.nan):5.1f}"
                    f" | all: elbow {s['all'].get('elbow_mae', np.nan):5.1f}  elev {s['all'].get('elevation_mae', np.nan):5.1f}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
