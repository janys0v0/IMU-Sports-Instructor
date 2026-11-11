"""Train E07's own models on Janys + Tom 10/28 and test them on Janys 11/05.

Training sets (all Apple-only, every 10/28 Calibrate segment OpenCap covers, E07 `dataset_full`):
- `janys`: Janys 10/28;
- `both`: Janys + Tom on 10/28;
- `tom`: Tom 10/28 only (another player, for reference);
- `both+half`: both players on 10/28 plus the other half of 11/05 (two folds in time, 10 s gap),
  i.e. how much a few Janys 11/05 minutes add.
Inputs per variant: Watch; Watch + phone; Watch + phone + AirPods. Models: ridge and the
bidirectional GRU, unchanged from `experiments/E07_pose_methods/learned_own.py`.

    .venv/bin/python -m experiments.E08_janys_1105.run [ridge] [gru]    # writes results/scores.json
    .venv/bin/python -m experiments.E08_janys_1105.run rescore          # rescore saved predictions
"""

import json
import sys

import numpy as np

from experiments.E07_pose_methods import learned_own as L
from experiments.E07_pose_methods.common import elbow_from_dirs
from experiments.E07_pose_methods.data import load as load07
from experiments.E07_pose_methods.evaluate import score

from .data import OUT, load

TRAIN_SETS = ("janys", "both", "tom", "both+half")
VARIANTS = L.VARIANTS  # watch, watch_phone, watch_phone_airpods


def fit_predict(model, Xtr, Ytr, Mtr, Str, Xte, seg_te):
    mu = np.concatenate(Xtr).mean(0)
    sd = np.concatenate(Xtr).std(0) + 1e-6
    if model == "ridge":
        Xc = [L.context(x, s) for x, s in zip(Xtr, Str)]
        M = np.concatenate(Mtr)
        return L.ridge_fit_predict(
            np.concatenate(Xc)[M], np.concatenate(Ytr)[M], L.context(Xte, seg_te)
        )
    X = np.concatenate([(x - mu) / sd for x in Xtr]).astype(np.float32)
    net = L.GRU(X.shape[1]).fit(X, np.concatenate(Ytr), np.concatenate(Mtr), np.concatenate(Str))
    return net.predict(((Xte - mu) / sd).astype(np.float32), seg_te)


def run(model, train, variant, te, old):
    devs = VARIANTS[variant]
    Xte = L.features(te, devs)
    sets = {"janys": [old["janys"]], "tom": [old["tom"]]}.get(train, [old["janys"], old["tom"]])
    base = (
        [L.features(s, devs) for s in sets],
        [L.targets(s) for s in sets],
        [s["gt_valid"] for s in sets],
        [s["seg"] + 1000 * i for i, s in enumerate(sets)],
    )
    P = np.full((len(Xte), 6), np.nan)
    if train != "both+half":
        P = fit_predict(model, *base, Xte, te["seg"])
    else:
        half = np.median(te["t"])
        far = np.abs(te["t"] - half) > 10
        for test_mask in (te["t"] < half, te["t"] >= half):
            tr = ~test_mask & far
            X, Y, M, S = (list(x) for x in base)
            X.append(Xte[tr])
            Y.append(L.targets(te)[tr])
            M.append(te["gt_valid"][tr])
            S.append(te["seg"][tr] + 5000)
            pred = fit_predict(model, X, Y, M, S, Xte, te["seg"])
            P[test_mask] = pred[test_mask]
    hum, fore = L.unit_pair(P)
    m = {"hum": hum, "fore": fore, "elbow": elbow_from_dirs(hum, fore)}
    m["valid"] = np.isfinite(fore).all(1)
    name = f"{model}_{variant}_{train}"
    np.savez_compressed(OUT / "janys" / f"method_{name}.npz", **m)
    return name, score(te, m)


def rescore():
    """Recompute results/scores.json from the saved predictions (no retraining)."""
    te = load()
    path = OUT / "scores.json"
    scores = json.loads(path.read_text())
    for name in scores:
        z = np.load(OUT / "janys" / f"method_{name}.npz")
        scores[name] = score(te, {k: z[k] for k in z.files})
    path.write_text(json.dumps(scores, indent=1) + "\n")


def main():
    if "rescore" in sys.argv:
        return rescore()
    models = [x for x in ("ridge", "gru") if x in sys.argv] or ["ridge", "gru"]
    te = load()
    old = {p: load07(p, full=True) for p in ("janys", "tom")}
    path = OUT / "scores.json"
    scores = json.loads(path.read_text()) if path.exists() else {}
    for model in models:
        for variant in VARIANTS:
            for train in TRAIN_SETS:
                name, s = run(model, train, variant, te, old)
                scores[name] = s
                path.write_text(json.dumps(scores, indent=1) + "\n")
                sw = s.get("swing", {})
                print(
                    f"{name:38s} swing: elbow {sw.get('elbow_mae', np.nan):5.1f}  elev "
                    f"{sw.get('elevation_mae', np.nan):5.1f}  fore dir {sw.get('forearm_dir_deg', np.nan):5.1f}"
                    f" | all: elbow {s['all'].get('elbow_mae', np.nan):5.1f}  elev {s['all'].get('elevation_mae', np.nan):5.1f}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
