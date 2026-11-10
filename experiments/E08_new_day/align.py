"""Put each 11/05 OpenCap recording on the phone's unix clock, the way 10/28 was aligned: the
right forearm's rotation speed from OpenCap cross-correlated with the Apple Watch's (30 Hz).

Reports the correlation peak and the runner-up outside ±2 s, then re-checks the offset segment by
segment (a ±1 s search around it) so a wrong lock shows as scattered per-segment lags. Writes
`data/external/20261105/aligned/<rec>/alignment.json` with `unix0` (clip time + unix0 = unix).

    .venv/bin/python -m experiments.E08_new_day.align
"""

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ALIGNED = ROOT / "data" / "external" / "20261105" / "aligned"
SESSION = ROOT / "data" / "recordings" / "field" / "20261105-124805-P01"
FS = 30.0


def watch_speed():
    import sys

    sys.path.insert(0, str(ROOT))
    from pipeline.preprocessing.motion_io import load_recording

    rec = load_recording(SESSION)
    w = next(s for s in rec.streams.values() if s.device == "watch")
    return w.t + w.boot_to_unix, np.linalg.norm(w.rot_rate, axis=1)


def norm(x):
    return (x - x.mean()) / (x.std() + 1e-9)


def xcorr_lag(a, b):
    """Lag k (samples) maximising sum a[i + k] * b[i], and the normalised correlation curve."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    c /= np.sqrt((a**2).sum() * (b**2).sum()) + 1e-9
    k = int(np.argmax(c))
    return (k if k < n // 2 else k - n), c


def main():
    tw, sw = watch_speed()
    ga = np.arange(tw[0], tw[-1], 1 / FS)
    a = norm(np.interp(ga, tw, sw))
    for rec_dir in sorted(ALIGNED.iterdir()):
        z = np.load(rec_dir / "opencap_gt.npz")
        tv, names = z["t"], list(z["body_names"])
        wv = np.linalg.norm(z["W"][:, names.index("radius_r")], axis=1)
        gv = np.arange(tv[0], tv[-1], 1 / FS)
        j = np.clip(np.searchsorted(tv, gv), 1, len(tv) - 1)
        covered = np.minimum(np.abs(tv[j] - gv), np.abs(tv[j - 1] - gv)) < 0.05
        b = np.where(covered, np.interp(gv, tv, wv), 0.0)
        b[covered] = norm(b[covered])
        k, c = xcorr_lag(a, b)
        cc = np.r_[c[c.size // 2 :], c[: c.size // 2]]
        lag0 = c.size // 2
        peak = cc[lag0 + k]
        far = np.abs(np.arange(cc.size) - (lag0 + k)) > 2 * FS
        unix0 = ga[0] + k / FS - gv[0]
        # per segment: best lag within ±1 s of the global one
        seg_lags = []
        for s in np.unique(z["seg"]):
            m = z["seg"] == s
            ts = tv[m]
            g = np.arange(ts[0], ts[-1], 1 / FS)
            bs = norm(np.interp(g, ts, wv[m]))
            best, bl = -1, 0
            for d in np.arange(-30, 31):
                aa = norm(np.interp(g + unix0 + d / FS, tw, sw))
                r = float((aa * bs).mean())
                if r > best:
                    best, bl = r, d
            seg_lags.append((str(s), bl / FS, best))
        lags = np.array([x[1] for x in seg_lags])
        rs = np.array([x[2] for x in seg_lags])
        out = {
            "unix0": unix0,
            "peak": float(peak),
            "runner_up": float(cc[far].max()),
            "segment_lag_s": {s: [round(lag, 3), round(r, 3)] for s, lag, r in seg_lags},
            "segment_lag_median_s": float(np.median(lags)),
            "segment_lag_iqr_s": float(np.subtract(*np.percentile(lags, [75, 25]))),
            "segment_r_median": float(np.median(rs)),
            "watch_session": SESSION.name,
        }
        (rec_dir / "alignment.json").write_text(json.dumps(out, indent=1))
        print(
            f"{rec_dir.name}: peak {peak:.3f} (next best {out['runner_up']:.3f}), "
            f"segments {len(lags)}: lag median {np.median(lags) * 1000:+.0f} ms, "
            f"IQR {out['segment_lag_iqr_s'] * 1000:.0f} ms, r median {np.median(rs):.2f}"
        )


if __name__ == "__main__":
    main()
