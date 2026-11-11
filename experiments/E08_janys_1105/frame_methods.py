"""E07's methods that need no 10/28 training, run on the 11/05 test set (Apple devices only; the
commercial chest and upper-arm sensors were not worn on 11/05).

- Geometric: the Watch's orientation in a trunk frame fixed at the Calibrate hold, or the AirPods
  as the trunk (`geometric.direct`).
- Constraint: Watch only, joint limits + effort, plain and swing-aware (`constraint.py`).
- OpenSense IK with the Watch and phone (`opensense_ik.py`, OpenSim env; see `opensense_run.py`).
- Published: WearMoCap (Watch; Watch + phone), MobilePoser (Watch + phone (+ AirPods)), IMUCoCo
  (Watch + phone + AirPods), same calls as E07.

Each method is called exactly as in E07; only the dataset (11/05) and the output folder change.

    .venv/bin/python -m experiments.E08_janys_1105.frame_methods [geometric constraint wearmocap published opensense opensense_save]
"""

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np

from experiments.E07_pose_methods.common import (
    elbow_from_dirs,
    in_trunk,
    segment_rot,
    set_forward,
    static_trunk,
)

from .data import OUT, SESSION, load

KEY = "janys_1105"  # player key for E07's per-segment body-forward cache
OPENSIM_PY = Path.home() / "micromamba-envs/opensim/bin/python"


def save(name, hum, fore, elbow=None, valid=None):
    elbow = elbow_from_dirs(hum, fore) if elbow is None else elbow
    valid = np.isfinite(fore).all(1) if valid is None else valid
    np.savez_compressed(
        OUT / "janys" / f"method_{name}.npz", hum=hum, fore=fore, elbow=elbow, valid=valid
    )
    print(name, f"valid {valid.mean():.0%}", flush=True)


def dataset():
    d = load()
    d["player"] = KEY
    set_forward(d, KEY)  # thigh-lean forward per segment, as in E07's geometric and constraint runs
    return d


def geometric(d):
    from experiments.E07_pose_methods.geometric import direct

    for name, trunk in (("watch_static_trunk", None), ("watch_airpods_trunk", "airpods")):
        h, f, _, _ = direct(d, trunk, None, "watch")
        save(name, h, f, elbow=np.full(len(f), np.nan))


def constraint(d):
    from scipy.ndimage import uniform_filter1d

    from experiments.E07_pose_methods import constraint as C

    Rw = segment_rot(d, "watch")
    cand = C.candidate_axes()
    spin = uniform_filter1d(np.linalg.norm(d["watch_gyro"], axis=1), 15)
    fade = 1 / (1 + (spin / 4.0) ** 2)
    Rt = static_trunk(d)
    for name, eff in (("constraint_watch_static_trunk", None), ("constraint_watch_swing", fade)):
        F = np.einsum("nji,njk->nik", Rt, Rw)
        hum = np.full((len(F), 3), np.nan)
        elbow = np.full(len(F), np.nan)
        for k in np.unique(d["seg"]):
            m = np.nonzero(d["seg"] == k)[0]
            cost, H = C.frame_costs(F[m], cand, None if eff is None else eff[m])
            path = C.viterbi(cost)
            hum[m] = H[np.arange(len(m)), path[:, 0], path[:, 1]]
            elbow[m] = np.degrees(C.THETA[path[:, 0]])
        save(name, hum / np.linalg.norm(hum, axis=1, keepdims=True), in_trunk(Rt, Rw), elbow=elbow)


def wearmocap(d):
    from experiments.E07_pose_methods import wearmocap as W

    for name, cfg in W.VARIANTS.items():
        hum, fore, valid = W.run(d, name, cfg)
        save(name, hum, fore, valid=valid)


def published(d):
    from experiments.common import mobileposer_runner as mp
    from experiments.common.session import load_session
    from experiments.E02_imucoco_comparison import imucoco_runner as ic
    from experiments.E07_pose_methods.learned_published import (
        EXTRA_VERTEX,
        _right_wrist_alias,
        arm_vectors,
        mesh_vertices,
        on_grid,
    )

    _right_wrist_alias()
    cwd = os.getcwd()
    s30 = load_session(str(SESSION), rate=30)
    rest = np.asarray(mp.body_model().get_zero_pose_joint_and_vertex()[0])
    for locs in (["right_wrist", "right_pocket", "head"], ["right_wrist", "right_pocket"]):
        o = mp.run(s30, locs)
        hum, fore = arm_vectors(o.glb, rest)
        (hum_g, fore_g), ok = on_grid(d, o.t, [hum, fore])
        save(
            "mobileposer_" + mp.combo_name(locs),
            hum_g,
            fore_g,
            valid=ok & np.isfinite(fore_g).all(1),
        )
    os.chdir(cwd)
    rest_ic = mesh_vertices()
    ic.SENSOR_VERTEX.update(EXTRA_VERTEX)
    os.chdir(cwd)
    s60 = deepcopy(load_session(str(SESSION), rate=60))
    t_s = d["t"] - d["start_unix"]
    s60.segments = [g for g in s60.segments if (t_s >= g.t[0]).any() and (t_s <= g.t[-1]).any()]
    locs = ["right_wrist", "right_pocket", "head"]
    s60.segments = [g for g in s60.segments if all(lc in g.devices for lc in locs)]
    o = ic.run(s60, locs)
    hum, fore = arm_vectors(o.glb, rest_ic)
    (hum_g, fore_g), ok = on_grid(d, o.t, [hum, fore])
    save("imucoco_rw_rp_h", hum_g, fore_g, valid=ok & np.isfinite(fore_g).all(1))
    os.chdir(cwd)


def opensense(d):
    """Watch + phone OpenSense IK in the OpenSim env, on E07's IK script (Watch on the forearm,
    phone on the thigh, both as segment rotations from the hold)."""
    a = {"watch_R": segment_rot(d, "watch"), "phone_R": segment_rot(d, "phone")}
    np.savez_compressed(OUT / "janys" / "aligned.npz", **a)
    runner = Path(__file__).resolve().parent / "opensense_run.py"
    subprocess.run([str(OPENSIM_PY), str(runner)], check=True)
    subprocess.run([str(OPENSIM_PY), str(runner), "--arm-only"], check=True)
    opensense_save(d)


def opensense_save(d):
    """Save the OpenSense IK results already in results/janys/opensense as methods."""
    unit = lambda v: v / np.linalg.norm(v, axis=1, keepdims=True)  # noqa: E731
    for name in ("opensense_watch_phone", "opensense_arm_watch"):  # whole body; right arm only
        path = OUT / "janys" / "opensense" / f"ik_{name}.npz"
        if not path.exists():
            continue
        z = np.load(path, allow_pickle=True)
        names = list(z["coord_names"])
        hum = unit(np.einsum("nji,nj->ni", z["R_torso"], -z["R_humerus"][:, :, 1]))
        fore = unit(np.einsum("nji,nj->ni", z["R_torso"], -z["R_radius"][:, :, 1]))
        valid = z["ok"] & np.isfinite(hum).all(1) & np.isfinite(fore).all(1)
        save(name, hum, fore, elbow=z["coords"][:, names.index("elbow_flex_r")], valid=valid)


def main():
    steps = {"geometric": geometric, "constraint": constraint, "wearmocap": wearmocap,
             "published": published, "opensense": opensense, "opensense_save": opensense_save}  # fmt: skip
    pick = [a for a in sys.argv[1:] if a in steps] or list(steps)
    d = dataset()
    for s in pick:
        steps[s](d)


if __name__ == "__main__":
    main()
