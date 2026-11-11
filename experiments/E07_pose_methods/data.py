"""E07 shared dataset: every sensor and OpenCap's ground truth on one 30 Hz timeline per player.

Built from the E06 results (clock offsets, Calibrate segments) for the 10/28 tennis sessions:
- sensors: iPhone (right pocket), Apple Watch (right wrist), AirPods (head), and the commercial
  msense sensors (trunk 2F5A, upper arm 1D03, wrist D0E5) as orientation streams from VQF without
  the magnetometer (offline, from 1 min before each Calibrate hold; `vqf_orient.py` says why);
- the Watch's 200 Hz motion stream and ~800 Hz accelerometer for finding ball contacts (swings);
- OpenCap: segment rotations and positions, markers, joint angles, on our clock.

Arm targets are model-independent: the right upper arm's and forearm's long axes in the trunk
frame (OpenSim frame: x forward, y up, z right), shoulder elevation and plane from them, and
OpenCap's elbow flexion and pronation.

    .venv/bin/python -m experiments.E07_pose_methods.data      # writes results/<player>/dataset.npz
"""

import glob
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

ROOT = Path(__file__).resolve().parents[2]
E06 = ROOT / "experiments" / "E06_side_by_side" / "results"
OUT = Path(__file__).resolve().parent / "results"
DATA = ROOT / "data" / "external" / "20261028"
FS = 30.0
PLAYERS = {"janys": ("janys-IMU1", "IMU1"), "tom": ("tom-IMU4", "IMU4")}
COMMERCIAL = {"trunk": "msense_2F5A", "upper_arm": "msense_1D03", "cwrist": "msense_D0E5"}
SWING_HALF_S = 0.5  # scored swing window: ±0.5 s around each ball contact
# Ball hits from the Watch (11/11, checked against IMG_0021 on 11/05): the impact rings the wrist
# above 60 Hz (hits 3.7-28 g, swings without a ball < 1 g); a fast arm (>= 10 rad/s within
# -0.25..+0.1 s) separates strokes from ball bouncing, pickups and racket taps.
HIT_HP_HZ, HIT_IMPACT_G, HIT_MIN_RAD_S, HIT_GAP_S = 60.0, 3.5, 10.0, 1.0


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def on_grid(t_src, quat, rot_rate, user_acc, gravity, g):
    """Orientation (slerp) and the other fields (linear) at grid times; valid where a sample is near."""
    order = np.argsort(t_src)
    t_src = t_src[order]
    keep = np.r_[True, np.diff(t_src) > 0]
    t_src, quat, rot_rate, user_acc, gravity = (x[order][keep] if x is not t_src else x[keep]
                                                for x in (t_src, quat, rot_rate, user_acc, gravity))  # fmt: skip
    gg = np.clip(g, t_src[0], t_src[-1])
    R = Slerp(t_src, Rotation.from_quat(quat))(gg)
    j = np.clip(np.searchsorted(t_src, g), 1, len(t_src) - 1)
    near = np.minimum(np.abs(t_src[j] - g), np.abs(t_src[j - 1] - g)) < 0.05
    lin = lambda x: np.stack([np.interp(gg, t_src, x[:, k]) for k in range(3)], 1)  # noqa: E731
    return dict(
        quat=R.as_quat(), gyro=lin(rot_rate), acc=lin(user_acc), grav=lin(gravity), valid=near
    )


def hits(ta, acc, tm, w):
    """Ball-contact times (s): Watch accelerometer `acc` (n, 3) in g at `ta` (~800 Hz), rotation
    speed `w` (rad/s) at `tm`. Impacts are peaks of the > 60 Hz acceleration magnitude above
    HIT_IMPACT_G, one per HIT_GAP_S (the largest); kept if the arm turns >= HIT_MIN_RAD_S
    around them. The contact time is the impact sample's."""
    from scipy.signal import butter, sosfiltfilt

    hp = np.zeros(len(ta))
    fs = 1 / np.median(np.diff(ta))
    sos = butter(4, HIT_HP_HZ, "highpass", fs=fs, output="sos")
    cuts = np.r_[0, np.nonzero(np.diff(ta) > 0.05)[0] + 1, len(ta)]  # filter each gap-free run
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a > 100:
            hp[a:b] = np.linalg.norm(sosfiltfilt(sos, acc[a:b], axis=0), axis=1)
    ev = []
    for i in np.nonzero(hp > HIT_IMPACT_G)[0]:
        if ev and ta[i] - ta[ev[-1]] < HIT_GAP_S:
            if hp[i] > hp[ev[-1]]:
                ev[-1] = i
        else:
            ev.append(i)
    out = []
    for i in ev:
        j0, j1 = np.searchsorted(tm, [ta[i] - 0.25, ta[i] + 0.1])
        if j1 > j0 and w[j0:j1].max() >= HIT_MIN_RAD_S:
            out.append(ta[i])
    return np.array(out)


def arm_targets(R, bn):
    """Upper-arm and forearm long axes (pointing distally) in the trunk frame, from OpenCap."""
    Rt = R[:, bn.index("torso")]
    hum = np.einsum("nji,nj->ni", Rt, -R[:, bn.index("humerus_r"), :, 1])
    fore = np.einsum("nji,nj->ni", Rt, -R[:, bn.index("radius_r"), :, 1])
    return unit(hum), unit(fore)


def elevation_plane(hum):
    """Shoulder elevation (angle from hanging) and plane (0 = forward, 90 = sideways), degrees."""
    elev = np.degrees(np.arccos(np.clip(-hum[:, 1], -1, 1)))
    plane = np.degrees(np.arctan2(hum[:, 2], hum[:, 0]))
    return elev, plane


def build(player, full=False):
    """full=False: the commercial blocks (E06 segments, every sensor). full=True: every Calibrate
    segment that OpenCap covers, Apple devices only (more data for the learned models)."""
    import sys

    sys.path.insert(0, str(ROOT))
    from experiments.E06_side_by_side import commercial as C
    from experiments.E06_side_by_side.make_video import opencap_series
    from pipeline.ingest.high_rate import read_file
    from pipeline.preprocessing.motion_io import load_recording

    from .vqf_orient import vqf_device_stream

    label, log = PLAYERS[player]
    meta = json.loads((E06 / label / "meta.json").read_text())
    rec = load_recording(Path(meta["session_dir"]))
    st = {s.device: s for s in rec.streams.values()}
    w = st["watch"]
    _, unix0, _ = opencap_series(
        DATA / "aligned_hrnet3" / player, w.t + w.boot_to_unix, w.rot_rate, np.zeros(1)
    )
    z = np.load(DATA / "aligned_hrnet3" / player / "opencap_gt.npz", allow_pickle=True)
    tv, bn, ikn = z["t"], list(z["body_names"]), list(z["ik_names"])
    ik = z["ik"] if np.abs(z["ik"][:, ikn.index("elbow_flex_r")]).max() > 4 else np.degrees(z["ik"])

    imu = glob.glob(str(DATA / log / "*_imu.csv"))[0]
    raws = C.load(imu, imu.replace("_imu.csv", "_magnetometer.csv"))
    for r in raws.values():
        r.t, r.mag_t = r.t - meta["clock_lag_s"], r.mag_t - meta["clock_lag_s"]

    segs = meta["segments"]
    if full:
        cal = sorted(meta["calibrations_s"])
        tv0, tv1 = (tv[0] + unix0 - meta["start_unix"], tv[-1] + unix0 - meta["start_unix"])
        segs = []
        for i, c in enumerate(cal):
            a, b = c + 3.0, (cal[i + 1] if i + 1 < len(cal) else tv1)
            a2, b2 = max(a, tv0), min(b, tv1)
            if b2 - a2 > 30:
                segs.append({"hold_s": c, "from_s": a2, "to_s": b2})
    cols = {}
    for k, seg in enumerate(segs):
        h0 = seg["hold_s"] + meta["start_unix"]
        g = np.arange(seg["from_s"], seg["to_s"], 1 / FS) + meta["start_unix"]
        part = {"t": g, "seg": np.full(len(g), k), "hold": np.tile([h0, h0 + 3.0], (len(g), 1))}
        for name, dev in (("phone", "phone"), ("watch", "watch"), ("airpods", "airpods")):
            s = st[dev]
            for f, v in on_grid(
                s.t + s.boot_to_unix, s.quat, s.rot_rate, s.user_acc, s.gravity, g
            ).items():
                part[f"{name}_{f}"] = v
        for name, sid in ({} if full else COMMERCIAL).items():
            s = vqf_device_stream(raws[sid], (h0, h0 + 3.0), g[-1] + 1)
            for f, v in on_grid(s.t, s.quat, s.rot_rate, s.user_acc, s.gravity, g).items():
                part[f"{name}_{f}"] = v
        for key, v in part.items():
            cols.setdefault(key, []).append(v)
    d = {k: np.concatenate(v) for k, v in cols.items()}
    g = d["t"]

    # hold orientations per segment and device (mean over the 3 s hold)
    holds = {}
    for seg in segs:
        h0 = seg["hold_s"] + meta["start_unix"]
        hg = np.arange(h0, h0 + 3.0, 1 / FS)
        for name, dev in (("phone", "phone"), ("watch", "watch"), ("airpods", "airpods")):
            s = st[dev]
            v = on_grid(s.t + s.boot_to_unix, s.quat, s.rot_rate, s.user_acc, s.gravity, hg)
            holds.setdefault(f"{name}_hold_quat", []).append(
                Rotation.from_quat(v["quat"]).mean().as_quat()
            )
        for name, sid in ({} if full else COMMERCIAL).items():
            s = vqf_device_stream(raws[sid], (h0, h0 + 3.0), h0 + 4)
            v = on_grid(s.t, s.quat, s.rot_rate, s.user_acc, s.gravity, hg)
            holds.setdefault(f"{name}_hold_quat", []).append(
                Rotation.from_quat(v["quat"]).mean().as_quat()
            )
    d.update({k: np.array(v) for k, v in holds.items()})

    # OpenCap on the grid
    tq = g - unix0
    i = np.clip(np.searchsorted(tv, tq), 1, len(tv) - 1)
    i = np.where(np.abs(tv[i - 1] - tq) < np.abs(tv[i] - tq), i - 1, i)
    gap_ok = np.r_[np.diff(tv) < 0.2, False] | np.r_[False, np.diff(tv) < 0.2]
    d["gt_valid"] = (np.abs(tv[i] - tq) < 0.02) & gap_ok[i]
    d["gt_R"], d["gt_P"], d["gt_mk"], d["gt_ik"] = z["R"][i], z["P"][i], z["mk"][i], ik[i]
    d["gt_hum"], d["gt_fore"] = arm_targets(d["gt_R"], bn)
    d["gt_elev"], d["gt_plane"] = elevation_plane(d["gt_hum"])
    d["gt_elbow"] = ik[i, ikn.index("elbow_flex_r")]
    d["gt_prosup"] = ik[i, ikn.index("pro_sup_r")]
    d["body_names"], d["ik_names"], d["mk_names"] = np.array(bn), np.array(ikn), z["mk_names"]
    d["unix0"], d["start_unix"] = unix0, meta["start_unix"]

    # swings = ball contacts from the Watch's accelerometer and rotation speed
    hf = [read_file(p) for p in sorted(Path(meta["session_dir"], "watch_hf").glob("*.bin"))]
    mot = np.concatenate([c.motion for c in hf])
    mot = mot[np.argsort(mot[:, 0])]
    b2u = hf[0].header.get("boot_to_unix", w.boot_to_unix)
    tw, ww = mot[:, 0] + b2u, np.linalg.norm(mot[:, 11:14], axis=1)
    acc = np.concatenate([c.accel for c in hf])
    acc = acc[np.argsort(acc[:, 0])]
    sw = hits(acc[:, 0] + b2u, acc[:, 1:4], tw, ww)  # ball contacts (data.py `hits`)
    d["swing_t"] = sw[(sw > g[0]) & (sw < g[-1])]
    near = np.zeros(len(g), bool)
    for s in d["swing_t"]:
        near |= np.abs(g - s) <= SWING_HALF_S
    d["in_swing"] = near
    d["hf_t"], d["hf_w"] = tw[(tw > g[0]) & (tw < g[-1])], ww[(tw > g[0]) & (tw < g[-1])]
    OUT.joinpath(player).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / player / ("dataset_full.npz" if full else "dataset.npz"), **d)
    print(
        f"{player}: {len(g)} frames ({len(g) / FS / 60:.1f} min), OpenCap on {d['gt_valid'].mean():.0%}, "
        f"{len(d['swing_t'])} swings, {(d['in_swing'] & d['gt_valid']).sum() / FS / 60:.1f} min of swing with OpenCap"
    )


def load(player, full=False) -> dict:
    z = np.load(OUT / player / ("dataset_full.npz" if full else "dataset.npz"), allow_pickle=True)
    return {k: z[k] for k in z.files}


if __name__ == "__main__":
    import sys

    for p in PLAYERS:
        build(p, full="--full" in sys.argv)
