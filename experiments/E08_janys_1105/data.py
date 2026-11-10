"""11/05 test set in E07's dataset layout: Janys's iPhone, Watch and AirPods on a 30 Hz grid over
every OpenCap segment, with OpenCap's arm targets and the Watch-detected swings.

Inputs: session 20261105-124805-P01 (phone + Watch + AirPods, 67 min), OpenCap rebuilt by
`opencap_gt.py`, clip -> unix offsets from `align.py`. Each OpenCap segment (~25 s) is one `seg`.
The E07 helpers (grid sampling, arm targets, swing detection) are reused unchanged, so the
features and targets are computed exactly as for 10/28.

    .venv/bin/python -m experiments.E08_janys_1105.data     # writes results/janys/dataset.npz
"""

import json
import sys
from pathlib import Path

import numpy as np

from experiments.E07_pose_methods.data import (
    FS,
    SWING_HALF_S,
    arm_targets,
    elevation_plane,
    on_grid,
    swings,
)

ROOT = Path(__file__).resolve().parents[2]
ALIGNED = ROOT / "data" / "external" / "20261105" / "aligned"
SESSION = ROOT / "data" / "recordings" / "field" / "20261105-124805-P01"
OUT = Path(__file__).resolve().parent / "results"


def build():
    sys.path.insert(0, str(ROOT))
    from pipeline.ingest.high_rate import read_file
    from pipeline.preprocessing.motion_io import load_recording

    rec = load_recording(SESSION)
    st = {s.device: s for s in rec.streams.values()}
    w = st["watch"]
    w_t0, w_t1 = (w.t + w.boot_to_unix)[[0, -1]]
    cols, k = {}, 0
    gt_parts = []
    for rec_dir in sorted(ALIGNED.iterdir()):
        z = np.load(rec_dir / "opencap_gt.npz")
        unix0 = json.loads((rec_dir / "alignment.json").read_text())["unix0"]
        tv, segs = z["t"], z["seg"]
        bn, ikn = list(z["body_names"]), list(z["ik_names"])
        for s in np.unique(segs):
            m = segs == s
            a, b = tv[m][0] + unix0, tv[m][-1] + unix0
            if a < w_t0 or b > w_t1:
                continue
            g = np.arange(a, b, 1 / FS)
            part = {
                "t": g,
                "seg": np.full(len(g), k),
                "seg_name": np.full(len(g), f"{rec_dir.name}/{s}"),
            }
            for name in ("phone", "watch", "airpods"):
                sd = st[name]
                for f, v in on_grid(
                    sd.t + sd.boot_to_unix, sd.quat, sd.rot_rate, sd.user_acc, sd.gravity, g
                ).items():
                    part[f"{name}_{f}"] = v
            tq = g - unix0
            ts = tv[m]
            i = np.clip(np.searchsorted(ts, tq), 1, len(ts) - 1)
            i = np.where(np.abs(ts[i - 1] - tq) < np.abs(ts[i] - tq), i - 1, i)
            part["gt_valid"] = np.abs(ts[i] - tq) < 0.04
            R = z["R"][m][i]
            part["gt_R"] = R
            part["gt_mk"] = z["mk"][m][i]
            part["gt_ik"] = z["ik"][m][i]
            gt_parts.append((bn, ikn))
            for key, v in part.items():
                cols.setdefault(key, []).append(v)
            k += 1
    d = {key: np.concatenate(v) for key, v in cols.items()}
    bn, ikn = gt_parts[0]
    d["gt_hum"], d["gt_fore"] = arm_targets(d["gt_R"], bn)
    d["gt_elev"], d["gt_plane"] = elevation_plane(d["gt_hum"])
    d["gt_elbow"] = d["gt_ik"][:, ikn.index("elbow_flex_r")]
    d["gt_prosup"] = d["gt_ik"][:, ikn.index("pro_sup_r")]
    d["body_names"], d["ik_names"] = np.array(bn), np.array(ikn)
    g = d["t"]

    # Calibrate holds (3 s from each "calibrate" event, as on 10/28): each segment uses the latest
    # hold before it, so the frame-based and published methods get the same calibration as on 10/28
    from scipy.spatial.transform import Rotation

    ev = [e for e in rec.events if e.get("name") in ("start", "calibrate")]
    start = next(e for e in ev if e["name"] == "start")
    # hold start = its phone time after Start (the event's own unix stamp is the hold's end)
    holds = sorted(
        start["unix"] + e["t_phone"] - start["t_phone"] for e in ev if e["name"] == "calibrate"
    )
    d["start_unix"] = start["unix"]
    d["calibrations_s"] = np.array(holds) - start["unix"]
    seg_hold = []
    for kk in range(int(d["seg"].max()) + 1):
        t0 = g[d["seg"] == kk][0]
        before = [h for h in holds if h + 3.0 <= t0]
        seg_hold.append(before[-1] if before else holds[0])  # segments before the first hold
    d["hold"] = np.stack([np.array(seg_hold)[d["seg"]], np.array(seg_hold)[d["seg"]] + 3.0], 1)
    for name in ("phone", "watch", "airpods"):
        sd = st[name]
        qs = []
        for h0 in seg_hold:
            v = on_grid(sd.t + sd.boot_to_unix, sd.quat, sd.rot_rate, sd.user_acc, sd.gravity,
                        np.arange(h0, h0 + 3.0, 1 / FS))  # fmt: skip
            qs.append(Rotation.from_quat(v["quat"]).mean().as_quat())
        d[f"{name}_hold_quat"] = np.array(qs)

    hf = [read_file(p) for p in sorted((SESSION / "watch_hf").glob("*.bin"))]
    mot = np.concatenate([c.motion for c in hf])
    mot = mot[np.argsort(mot[:, 0])]
    b2u = hf[0].header.get("boot_to_unix", w.boot_to_unix)
    tw, ww = mot[:, 0] + b2u, np.linalg.norm(mot[:, 11:14], axis=1)
    sw = swings(tw, ww)
    j = np.clip(np.searchsorted(g, sw), 1, len(g) - 1)
    inside = np.minimum(np.abs(g[j] - sw), np.abs(g[j - 1] - sw)) < 1 / FS  # on a covered segment
    d["swing_t"] = sw[inside]
    near = np.zeros(len(g), bool)
    for s in d["swing_t"]:
        near |= np.abs(g - s) <= SWING_HALF_S
    d["in_swing"] = near
    (OUT / "janys").mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "janys" / "dataset.npz", **d)
    print(
        f"11/05 janys: {len(g)} frames ({len(g) / FS / 60:.1f} min) in {k} segments, OpenCap on "
        f"{d['gt_valid'].mean():.0%}, {len(d['swing_t'])} swings, "
        f"{(d['in_swing'] & d['gt_valid']).sum() / FS / 60:.1f} min of swing with OpenCap"
    )


def load(player="janys"):
    z = np.load(OUT / player / "dataset.npz", allow_pickle=True)
    return {k: z[k] for k in z.files}


if __name__ == "__main__":
    build()
