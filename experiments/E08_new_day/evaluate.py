"""Score every method saved for 11/05 against OpenCap (E07's `score`: all minutes and swings).

.venv/bin/python -m experiments.E08_new_day.evaluate     # writes results/scores_all.json
"""

import json

import numpy as np

from experiments.E07_pose_methods.evaluate import score

from .data import OUT, load


def main():
    d = load()
    out = {}
    for p in sorted((OUT / "janys").glob("method_*.npz")):
        name = p.stem[len("method_") :]
        z = np.load(p, allow_pickle=True)
        out[name] = score(d, {k: z[k] for k in ("hum", "fore", "elbow", "valid")})
    (OUT / "scores_all.json").write_text(json.dumps(out, indent=1) + "\n")
    for name, s in out.items():
        sw = s.get("swing", {})
        print(f"{name:38s} swing elbow {sw.get('elbow_mae', np.nan):5.1f}  elev {sw.get('elevation_mae', np.nan):5.1f}"
              f"  fore incl {sw.get('forearm_incl_mae', np.nan):5.1f}  fore dir {sw.get('forearm_dir_deg', np.nan):5.1f}")  # fmt: skip


if __name__ == "__main__":
    main()
