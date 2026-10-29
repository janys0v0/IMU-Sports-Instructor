"""E06: full-body reconstruction from the Apple devices and from commercial IMUs, same moments.

Run from the repo root:
    .venv/bin/python -m experiments.E06_side_by_side.run SESSION_DIR COMMERCIAL_IMU_CSV --label NAME

1. Clock: the logger's time is shifted onto ours by cross-correlating rotation speed of the wrist
   sensor (worn with the Watch) against the Watch.
2. Segments: the app's Calibrate holds that fall inside the commercial log, as in the rest of the
   pipeline (each hold starts a segment). Both systems use the same holds and the same body heading
   (the person facing the landmark, from the phone's calibration).
3. Inputs: Apple = phone (pocket), Watch (wrist), AirPods (head, when planned). Commercial = the
   wrist sensor in the wrist slot and the waist sensor in the pocket slot (MobilePoser has no
   pelvis input; the waist stands in for the thigh, a known mismatch).
4. MobilePoser on each set; outputs and per-sensor rotation speed saved for make_video.py.

Writes results/<NAME>/: outputs.npz, series.npz, meta.json.
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.paths import MOBILEPOSER_DIR, ROOT

WRIST_SENSOR = "msense_D0E5"  # worn with the Watch (reported for 10/19 and 10/28)
WAIST_SENSOR = "msense_2F5A"  # matched by motion: slow, weakly like the phone
FS = 50.0  # grid for the clock alignment


def best_lag(a, b, max_lag):
    """Lag (samples) with the highest correlation of a[t] and b[t + lag]."""
    best = (0, -np.inf)
    for lag in range(-max_lag, max_lag + 1):
        x, y = (a[: len(a) - lag], b[lag:]) if lag >= 0 else (a[-lag:], b[: len(b) + lag])
        ok = ~np.isnan(x) & ~np.isnan(y)
        if ok.sum() > FS * 30:
            r = np.corrcoef(x[ok], y[ok])[0, 1]
            if r > best[1]:
                best = (lag, r)
    return best


def speed_on(grid, t, w, max_gap=0.25):
    """Rotation speed on `grid`; NaN outside the stream and inside gaps (the commercial links
    drop out for seconds at a time, and a straight line across a gap would look like data)."""
    v = np.interp(grid, t, np.linalg.norm(w, axis=1))
    idx = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
    v[(grid < t[0]) | (grid > t[-1]) | (t[idx] - t[idx - 1] > max_gap)] = np.nan
    return v


def frozen(t, w, min_s=0.1):
    """Samples inside runs of identical gyro readings lasting >= min_s: a stuck channel (the
    racket sensor repeats one value for seconds while its accelerometer keeps changing)."""
    same = np.r_[False, (np.diff(w, axis=0) == 0).all(axis=1)]
    out = np.zeros(len(t), bool)
    i = 0
    while i < len(t):
        if same[i]:
            j = i
            while j + 1 < len(t) and same[j + 1]:
                j += 1
            if t[j] - t[i - 1] >= min_s:
                out[i - 1 : j + 1] = True
            i = j + 1
        else:
            i += 1
    return out


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("session", type=Path)
    p.add_argument(
        "commercial", type=Path, help="logger *_imu.csv (the *_magnetometer.csv next to it is used)"
    )
    p.add_argument("--label", required=True)
    p.add_argument(
        "--watch-loc", default="right_wrist", help="slot of the Watch (and the wrist sensor)"
    )
    p.add_argument("--tz", default="America/New_York")
    args = p.parse_args()
    session, imu_csv = args.session.resolve(), args.commercial.resolve()
    mag_csv = Path(str(imu_csv).replace("_imu.csv", "_magnetometer.csv"))
    out_dir = Path(__file__).resolve().parent / "results" / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(MOBILEPOSER_DIR)  # MobilePoser fixes its file paths at import

    from experiments.common import mobileposer_runner as mp
    from experiments.common.session import Device, Segment, Session
    from pipeline.ingest.ingest_field import planned_devices
    from pipeline.live.live_viewer import calibrate_shared
    from pipeline.pose.render_session import segments
    from pipeline.preprocessing.calibration import (
        AIRPODS_FORWARD,
        calibrate,
        to_body,
        with_standing_rest,  # fmt: skip
    )
    from pipeline.preprocessing.motion_io import load_recording
    from pipeline.preprocessing.resample import MODEL_FPS, resample

    from . import commercial as C

    rec = load_recording(session)
    phone_loc = next(l for l, s in rec.streams.items() if s.device == "phone")
    phone = rec.streams[phone_loc]
    watch = next(s for s in rec.streams.values() if s.device == "watch")
    head = rec.streams.get("head")
    plan = planned_devices(rec.events) or {"phone", "watch", "airpods"}
    use_head = head is not None and "airpods" in plan
    screen = rec.setting("pocket_screen", "leg")
    start = rec.last_event("start")["t_phone"]
    unix_to_phone = -phone.boot_to_unix
    raws = C.load(imu_csv, mag_csv, args.tz)

    # 1. Clock: logger time - lag = our time.
    w = raws[WRIST_SENSOR]
    t0, t1 = (
        max(w.t[0], watch.t[0] + watch.boot_to_unix),
        min(w.t[-1], watch.t[-1] + watch.boot_to_unix),
    )
    grid = np.arange(t0, t1, 1 / FS)
    lag_n, r = best_lag(
        speed_on(grid, watch.t + watch.boot_to_unix, watch.rot_rate),
        speed_on(grid, w.t, w.gyro),
        int(5 * FS),
    )
    lag = lag_n / FS
    for raw in raws.values():
        raw.t, raw.mag_t = raw.t - lag, raw.mag_t - lag
    block = (max(r_.t[0] for r_ in raws.values()) + 1, min(r_.t[-1] for r_ in raws.values()) - 1)

    # 2. Segments whose hold lies inside the commercial log.
    segs = []
    for hold, s0, s1 in segments(rec, phone):
        hold_u = (hold[0] - unix_to_phone, hold[1] - unix_to_phone)
        if hold_u[0] >= block[0] and hold_u[1] <= block[1]:
            segs.append((hold, s0, min(s1, block[1] + unix_to_phone)))
    if not segs:
        raise SystemExit("no calibration hold inside the commercial log")

    apple, comm, kept, checks = [], [], [], []
    shift_w = phone.boot_to_unix - watch.boot_to_unix
    for hold, s0, s1 in segs:
        cal_p = calibrate(phone, hold, pocket_screen=screen)
        res_p = resample(phone, rate=MODEL_FPS, t_start=s0, t_end=s1)
        a_dev = {
            phone_loc: Device(
                phone_loc,
                *to_body(cal_p, res_p),
                res_p.valid,
                cal_p.checks["passed"],
                res_p.rot_rate,
            )
        }
        win_w = (hold[0] + shift_w, hold[1] + shift_w)
        cal_w = with_standing_rest(calibrate_shared(watch, win_w, cal_p.R_MI), args.watch_loc)
        res_w = resample(watch, rate=MODEL_FPS, t_start=s0 + shift_w, t_end=s1 + shift_w)
        a_dev[args.watch_loc] = Device(
            args.watch_loc,
            *to_body(cal_w, res_w),
            res_w.valid,
            cal_w.checks["passed"],
            res_w.rot_rate,
        )
        if use_head:
            cal_h = calibrate(head, hold, forward_device=AIRPODS_FORWARD)
            res_h = resample(head, rate=MODEL_FPS, t_start=s0, t_end=s1)
            a_dev["head"] = Device(
                "head", *to_body(cal_h, res_h), res_h.valid, cal_h.checks["passed"], res_h.rot_rate
            )
        c_dev = {}
        hold_u = (hold[0] - unix_to_phone, hold[1] - unix_to_phone)
        for sid, loc in ((WRIST_SENSOR, args.watch_loc), (WAIST_SENSOR, phone_loc)):
            st = C.device_stream(raws[sid], hold_u, s1 - unix_to_phone, unix_to_phone)
            cal = calibrate_shared(st, hold, cal_p.R_MI)
            if loc.endswith("wrist"):
                cal = with_standing_rest(cal, loc)
            res = resample(st, rate=MODEL_FPS, t_start=s0, t_end=s1)
            c_dev[loc] = Device(
                loc, *to_body(cal, res), res.valid, cal.checks["passed"], res.rot_rate
            )
            checks.append({"sensor": sid, "hold": round(hold[0] - start, 1), **cal.checks})
        n = min(len(d.acc) for d in list(a_dev.values()) + list(c_dev.values()))
        for d in list(a_dev.values()) + list(c_dev.values()):
            d.acc, d.ori, d.valid, d.rot_rate = d.acc[:n], d.ori[:n], d.valid[:n], d.rot_rate[:n]
        t_seg = res_p.t[:n] - start
        apple.append(Segment(t_seg, a_dev))
        comm.append(Segment(t_seg, c_dev))
        kept.append(
            {
                "hold_s": round(hold[0] - start, 1),
                "from_s": round(s0 - start, 1),
                "to_s": round(s1 - start, 1),
            }
        )

    a_locs = [phone_loc, args.watch_loc] + (["head"] if use_head else [])
    c_locs = [phone_loc, args.watch_loc]
    out_a = mp.run(Session("apple", phone_loc, apple), a_locs)
    out_c = mp.run(Session("commercial", phone_loc, comm), c_locs)
    np.savez_compressed(out_dir / "outputs.npz", t=out_a.t, apple_pose=out_a.pose, apple_tran=out_a.tran,
                        commercial_pose=out_c.pose, commercial_tran=out_c.tran)  # fmt: skip

    # 4. Rotation speed of every sensor on the output's time grid (seconds after Start).
    t_unix = out_a.t + start - unix_to_phone
    series = {
        "t": out_a.t,
        "apple:phone": speed_on(t_unix, phone.t - unix_to_phone, phone.rot_rate),
        "apple:watch": speed_on(t_unix, watch.t + watch.boot_to_unix, watch.rot_rate),
    }
    if use_head:
        series["apple:airpods"] = speed_on(t_unix, head.t - unix_to_phone, head.rot_rate)
    frozen_share = {}
    for sid, raw in raws.items():
        stuck = frozen(raw.t, raw.gyro)
        frozen_share[sid] = round(float(stuck.mean()), 3)
        series[f"commercial:{sid}"] = speed_on(t_unix, raw.t[~stuck], raw.gyro[~stuck])
    np.savez_compressed(
        out_dir / "series.npz", **{k: np.degrees(v) if k != "t" else v for k, v in series.items()}
    )

    ev = pd.read_csv(str(imu_csv).replace("_imu.csv", "_events.csv"))
    ev_unix = pd.to_datetime(ev["timestamp"]).dt.tz_localize(args.tz).astype("int64") / 1e9 - lag
    swings = [{"t": round(float(u + unix_to_phone - start), 2), "sensor": s} for u, k, s in
              zip(ev_unix, ev["kind"], ev.get("source_id", [""] * len(ev))) if k == "swing"]  # fmt: skip
    meta = {
        "label": args.label,
        "session": session.name,
        "commercial_log": imu_csv.name,
        "start_unix": start - unix_to_phone,
        "clock_lag_s": lag,
        "clock_match_r": round(float(r), 3),
        "segments": kept,
        "apple_inputs": {l: rec.streams[l].device if l in rec.streams else "watch" for l in a_locs},
        "commercial_inputs": {
            args.watch_loc: WRIST_SENSOR,
            phone_loc: f"{WAIST_SENSOR} (waist, in the pocket slot)",
        },
        "combos": {"apple": mp.combo_name(a_locs), "commercial": mp.combo_name(c_locs)},
        "calibration_checks": checks,
        "frozen_gyro_share": frozen_share,
        "pocket_screen": screen,
        "swings": swings,
        "calibrations_s": [
            round(e["t_phone"] - start, 1) for e in rec.events if e.get("name") == "calibrate"
        ],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(
        json.dumps(
            {k: meta[k] for k in ("label", "clock_lag_s", "clock_match_r", "segments", "combos")},
            indent=2,
        )
    )
    print(f"Saved {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
