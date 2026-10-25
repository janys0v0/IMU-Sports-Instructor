"""E05: our phone / Watch / AirPods IMU streams against commercial IMUs worn in the same trials.

Run from the repo root:
    .venv/bin/python -m experiments.E05_commercial_imu.run SESSION_DIR COMMERCIAL_IMU_CSV [--tz America/New_York]

COMMERCIAL_IMU_CSV is a logger export (timestamp, ax..az m/s^2, gx..gz rad/s, source_id; one row per
sample, several sensors interleaved). Steps:
1. Put both on one clock: commercial wall-clock time (local, naive) and ours (device time + boot_to_unix).
2. Fine offset per pair by cross-correlating gyro magnitude (rotation speed is independent of how a
   sensor is mounted), searched over +-MAX_LAG_S.
3. Placement: each commercial sensor is matched to the device of ours it moves most like.
4. Agreement per matched pair after the fixed rotation between the two sensors' axes (Kabsch on gyro
   vectors): per-axis gyro RMSE and correlation, and acceleration magnitude agreement.

Writes results/<SESSION>/: metrics.json, summary.md, gyro_overlap.png.
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.preprocessing.motion_io import load_recording  # noqa: E402

FS = 50.0  # common grid, Hz
MAX_LAG_S = 5.0
G = 9.80665
OURS = {"phone": "iPhone (thigh pocket)", "watch": "Watch (wrist)", "airpods": "AirPods (head)"}


def commercial_streams(csv, tz):
    d = pd.read_csv(csv)
    t = pd.to_datetime(d["timestamp"]).dt.tz_localize(tz).astype("int64") / 1e9
    d = d.assign(unix=t.values)
    out = {}
    for sid, g in d.groupby("source_id"):
        g = g.sort_values("unix").drop_duplicates("unix")
        out[sid] = {
            "t": g["unix"].to_numpy(),
            "gyro": g[["gx", "gy", "gz"]].to_numpy(float),
            "acc": g[["ax", "ay", "az"]].to_numpy(float),
        }
    return out


def our_streams(session):
    rec = load_recording(session)
    out = {}
    for s in rec.streams.values():
        # Specific force in m/s^2 with the usual sign (+1 g up at rest); Apple reports gravity down.
        acc = -(s.gravity + s.user_acc) * G
        out[s.device] = {"t": s.t + s.boot_to_unix, "gyro": s.rot_rate, "acc": acc}
    return out


def on_grid(stream, grid):
    """Linear interpolation onto `grid`; NaN outside the stream or across gaps > 0.25 s."""
    t = stream["t"]
    out = {}
    for key in ("gyro", "acc"):
        v = np.stack([np.interp(grid, t, stream[key][:, k]) for k in range(3)], axis=1)
        out[key] = v
    idx = np.searchsorted(t, grid)
    left, right = t[np.clip(idx - 1, 0, len(t) - 1)], t[np.clip(idx, 0, len(t) - 1)]
    bad = (grid < t[0]) | (grid > t[-1]) | (right - left > 0.25)
    for key in out:
        out[key][bad] = np.nan
    return out


def zscore(x):
    x = x - np.nanmean(x)
    return x / (np.nanstd(x) + 1e-9)


def best_lag(a, b, max_lag):
    """Lag (samples) that best aligns b to a: corr(a[t], b[t + lag]), NaN-aware."""
    best = (0, -np.inf)
    for lag in range(-max_lag, max_lag + 1):
        x, y = (a[: len(a) - lag], b[lag:]) if lag >= 0 else (a[-lag:], b[: len(b) + lag])
        ok = ~np.isnan(x) & ~np.isnan(y)
        if ok.sum() < FS * 20:
            continue
        r = np.corrcoef(x[ok], y[ok])[0, 1]
        if r > best[1]:
            best = (lag, r)
    return best


def shift(v, lag):
    out = np.full_like(v, np.nan)
    if lag >= 0:
        out[: len(v) - lag] = v[lag:]
    else:
        out[-lag:] = v[: len(v) + lag]
    return out


def kabsch(a, b):
    """Rotation R minimising |a - b R^T| (rows are vectors): maps b's axes onto a's."""
    h = b.T @ a
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    return vt.T @ np.diag([1, 1, d]) @ u.T


def compare(ours, theirs, max_lag):
    wa, wb = np.linalg.norm(ours["gyro"], axis=1), np.linalg.norm(theirs["gyro"], axis=1)
    lag, r = best_lag(zscore(wa), zscore(wb), max_lag)
    g_b = np.stack([shift(theirs["gyro"][:, k], lag) for k in range(3)], 1)
    a_b = np.stack([shift(theirs["acc"][:, k], lag) for k in range(3)], 1)
    ok = ~np.isnan(ours["gyro"]).any(1) & ~np.isnan(g_b).any(1)
    R = kabsch(ours["gyro"][ok], g_b[ok])
    g_rot = g_b @ R.T
    err = ours["gyro"][ok] - g_rot[ok]
    axis_corr = [float(np.corrcoef(ours["gyro"][ok, k], g_rot[ok, k])[0, 1]) for k in range(3)]
    acc_mag_a, acc_mag_b = np.linalg.norm(ours["acc"][ok], axis=1), np.linalg.norm(a_b[ok], axis=1)
    return {
        "lag_s": lag / FS,
        "gyro_mag_corr": round(float(r), 3),
        "overlap_s": round(ok.sum() / FS, 1),
        "gyro_rmse_deg_s": round(float(np.degrees(np.sqrt((err**2).sum(1).mean()))), 1),
        "gyro_axis_corr": [round(c, 3) for c in axis_corr],
        "gyro_peak_deg_s": [
            round(float(np.degrees(np.nanpercentile(wa[ok], 99))), 0),
            round(float(np.degrees(np.nanpercentile(np.linalg.norm(g_b[ok], axis=1), 99))), 0),
        ],
        "acc_mag_corr": round(float(np.corrcoef(acc_mag_a, acc_mag_b)[0, 1]), 3),
        "acc_mag_rmse_m_s2": round(float(np.sqrt(((acc_mag_a - acc_mag_b) ** 2).mean())), 2),
        "rotation_deg": round(
            float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))), 1
        ),
        "_series": (wa, np.linalg.norm(g_b, axis=1)),
    }


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("session", type=Path)
    p.add_argument("commercial", type=Path)
    p.add_argument("--tz", default="America/New_York")
    args = p.parse_args()

    theirs_raw = commercial_streams(args.commercial, args.tz)
    ours_raw = our_streams(args.session)
    t0 = max(min(s["t"][0] for s in theirs_raw.values()), min(s["t"][0] for s in ours_raw.values()))
    t1 = min(
        max(s["t"][-1] for s in theirs_raw.values()), max(s["t"][-1] for s in ours_raw.values())
    )
    if t1 - t0 < 30:
        raise SystemExit(f"only {t1 - t0:.0f} s of overlap")
    grid = np.arange(t0, t1, 1 / FS)
    ours = {k: on_grid(v, grid) for k, v in ours_raw.items()}
    theirs = {k: on_grid(v, grid) for k, v in theirs_raw.items()}

    max_lag = int(MAX_LAG_S * FS)
    results = {}
    for sid, b in theirs.items():
        results[sid] = {dev: compare(a, b, max_lag) for dev, a in ours.items()}
    # Placement: the device of ours each commercial sensor moves most like.
    match = {sid: max(r, key=lambda dev: r[dev]["gyro_mag_corr"]) for sid, r in results.items()}

    out = Path(__file__).parent / "results" / args.session.name
    out.mkdir(parents=True, exist_ok=True)
    clean = {
        sid: {dev: {k: v for k, v in m.items() if not k.startswith("_")} for dev, m in r.items()}
        for sid, r in results.items()
    }
    meta = {
        "session": args.session.name,
        "commercial": args.commercial.name,
        "overlap_s": round(t1 - t0, 1),
    }
    (out / "metrics.json").write_text(
        json.dumps({**meta, "match": match, "pairs": clean}, indent=2) + "\n"
    )

    lines = [
        f"# E05: {args.session.name} vs {args.commercial.name}",
        "",
        f"Overlap {t1 - t0:.0f} s. Rotation-speed correlation of every pair (best lag within ±{MAX_LAG_S:.0f} s):",
        "",
        "| commercial | " + " | ".join(OURS.get(d, d) for d in ours) + " | best match |",
        "|---|" + "---|" * (len(ours) + 1),
    ]
    for sid, r in results.items():
        lines.append(
            f"| {sid} | "
            + " | ".join(f"{r[d]['gyro_mag_corr']:.2f}" for d in ours)
            + f" | {match[sid]} |"
        )
    lines += ["", "Matched pairs, after the fixed rotation between the two sensors' axes:", ""]
    lines += [
        "| commercial → ours | lag s | gyro RMSE °/s | axis corr | p99 rotation speed °/s (ours / theirs) | acc magnitude corr | acc RMSE m/s² |",
        "|---|---|---|---|---|---|---|",
    ]
    for sid, dev in match.items():
        m = results[sid][dev]
        lines.append(
            f"| {sid} → {dev} | {m['lag_s']:+.2f} | {m['gyro_rmse_deg_s']} | {', '.join(f'{c:.2f}' for c in m['gyro_axis_corr'])} | "
            f"{m['gyro_peak_deg_s'][0]:.0f} / {m['gyro_peak_deg_s'][1]:.0f} | {m['acc_mag_corr']:.2f} | {m['acc_mag_rmse_m_s2']} |"
        )
    (out / "summary.md").write_text("\n".join(lines) + "\n")

    fig, axes = plt.subplots(
        len(match), 1, figsize=(13, 2.6 * len(match)), sharex=True, squeeze=False
    )
    for ax, (sid, dev) in zip(axes[:, 0], match.items()):
        wa, wb = results[sid][dev]["_series"]
        ax.plot(grid - t0, np.degrees(wa), lw=0.8, label=f"ours: {OURS.get(dev, dev)}")
        ax.plot(
            grid - t0,
            np.degrees(wb),
            lw=0.8,
            alpha=0.8,
            label=f"commercial: {sid} (shifted {results[sid][dev]['lag_s']:+.2f} s)",
        )
        ax.set_ylabel("rotation speed (°/s)")
        ax.legend(loc="upper right", fontsize=8)
        ax.set_title(
            f"{sid} → {dev}: r = {results[sid][dev]['gyro_mag_corr']:.2f}, RMSE {results[sid][dev]['gyro_rmse_deg_s']} °/s",
            fontsize=9,
        )
    axes[-1, 0].set_xlabel("s from start of overlap")
    fig.tight_layout()
    fig.savefig(out / "gyro_overlap.png", dpi=110)
    print("\n".join(lines))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
