"""Put the IMG_0021 camera clip (behind Janys) on the unix clock and fit its projection, so the
Janys 11/05 comparison video can show the footage with OpenCap's skeleton drawn on it.

jtchen's OpenCap calibration of this phone was not shared, so both come from the footage:
1. 2D keypoints from Apple Vision (`vision2d.swift`), the largest person per frame (Janys is
   nearest to this camera).
2. Offset: the right wrist's speed in the image cross-correlated with OpenCap's right-wrist marker
   speed (both 10 Hz, unix clock via `align.py`).
3. Projection: normalized DLT (Hartley) with RANSAC from OpenCap's 3D markers to the 2D keypoints
   (E06's unnormalized DLT locked onto a degenerate fit here); the offset is then refined (±1.5 s
   in 1/30 s steps) by the share of keypoints within 25 px. The clip's recorded creation time
   (12:47:14) agrees with the coarse offset to under a second.

    swift experiments/E08_janys_1105/vision2d.swift <clip> <json> --stride 6 --start 0 --seconds 1200
    .venv/bin/python -m experiments.E08_janys_1105.camera     # writes results/camera.json
"""

import json
from pathlib import Path

import numpy as np

from experiments.E06_side_by_side.camera import project

ROOT = Path(__file__).resolve().parents[2]
CAMS = ROOT / "data" / "external" / "20261105" / "cameras"
ALIGNED = ROOT / "data" / "external" / "20261105" / "aligned"
OUT = Path(__file__).resolve().parent / "results"
CLIP = CAMS / "IMG_0021.MOV"
VISION = sorted(CAMS.glob("IMG_0021_vision_*.json"))
JOINTS = ["Neck", "RShoulder", "RElbow", "RWrist", "LShoulder", "LElbow", "LWrist", "midHip",
          "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle"]  # fmt: skip
FS = 10.0


def vision_frames():
    frames = []
    for p in VISION:
        frames += json.loads(p.read_text())["frames"]
    t = np.array([f["t"] for f in frames])
    kp = np.full((len(frames), len(JOINTS), 2), np.nan)
    for i, f in enumerate(frames):
        if not f["people"]:
            continue

        def extent(p):
            pts = np.array([v[:2] for v in p.values()])
            return np.ptp(pts[:, 1]) if len(pts) > 2 else 0

        p = max(f["people"], key=extent)
        for j, n in enumerate(JOINTS):
            if n in p:
                kp[i, j] = p[n][:2]
    order = np.argsort(t)
    return t[order], kp[order]


def opencap_unix():
    """All recordings' markers on the unix clock."""
    ts, mks, names = [], [], None
    for rec in sorted(ALIGNED.iterdir()):
        z = np.load(rec / "opencap_gt.npz")
        unix0 = json.loads((rec / "alignment.json").read_text())["unix0"]
        ts.append(z["t"] + unix0)
        mks.append(z["mk"])
        names = list(z["mk_names"])
    t = np.concatenate(ts)
    o = np.argsort(t)
    return t[o], np.concatenate(mks)[o], names


def ndlt(X, x):
    """Normalized DLT: 3 x 4 projection from >= 6 point pairs (Hartley normalization)."""
    mX, sX = X.mean(0), X.std()
    mx, sx = x.mean(0), x.std()
    Xn, xn = (X - mX) / sX, (x - mx) / sx
    A = np.zeros((2 * len(X), 12))
    A[0::2, 0:3], A[0::2, 3] = Xn, 1
    A[0::2, 8:11], A[0::2, 11] = -xn[:, :1] * Xn, -xn[:, 0]
    A[1::2, 4:7], A[1::2, 7] = Xn, 1
    A[1::2, 8:11], A[1::2, 11] = -xn[:, 1:2] * Xn, -xn[:, 1]
    Pn = np.linalg.svd(A, full_matrices=False)[2][-1].reshape(3, 4)
    T = np.array([[1 / sx, 0, -mx[0] / sx], [0, 1 / sx, -mx[1] / sx], [0, 0, 1]])
    U = np.eye(4)
    U[:3, :3] /= sX
    U[:3, 3] = -mX / sX
    return np.linalg.inv(T) @ Pn @ U


def sample(t_src, x, tq, max_gap=0.05):
    j = np.clip(np.searchsorted(t_src, tq), 1, len(t_src) - 1)
    j = np.where(np.abs(t_src[j - 1] - tq) < np.abs(t_src[j] - tq), j - 1, j)
    ok = np.abs(t_src[j] - tq) < max_gap
    return x[j], ok


def main():
    tc, kp = vision_frames()
    tu, mk, names = opencap_unix()
    iw = JOINTS.index("RWrist")
    mw = names.index("RWrist")
    # image speed of the right wrist (px/s) and OpenCap's (m/s), each on its own 10 Hz grid
    gc = np.arange(tc[0], tc[-1], 1 / FS)
    w2, okc = sample(tc, kp[:, iw], gc, 0.2)
    okc &= np.isfinite(w2).all(1)
    sc = np.r_[0, np.linalg.norm(np.diff(w2, axis=0), axis=1)] * FS
    sc[~(okc & np.r_[False, okc[:-1]])] = np.nan
    gu = np.arange(tu[0], tu[-1], 1 / FS)
    w3, oku = sample(tu, mk[:, mw], gu)
    su = np.r_[0, np.linalg.norm(np.diff(w3, axis=0), axis=1)] * FS
    su[~(oku & np.r_[False, oku[:-1]])] = np.nan

    def z(v):
        v = np.where(np.isfinite(v), v, np.nanmean(v))
        v = (v - v.mean()) / (v.std() + 1e-9)
        return np.clip(v, -4, 6)

    a, b = z(su), z(sc)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    c /= np.sqrt((a**2).sum() * (b**2).sum())
    k = int(np.argmax(c))
    k = k if k < n // 2 else k - n
    clip_unix0 = gu[0] + k / FS - gc[0]  # unix = clip time + clip_unix0
    far = np.abs((np.arange(n) + n // 2) % n - n // 2 - k) > 2 * FS
    print(
        f"coarse offset: clip t=0 at unix {clip_unix0:.2f}, peak {c.max():.3f} (next {c[far].max():.3f})"
    )

    def fit(off, tries=400):
        X, x = [], []
        for i in range(0, len(tc), 3):
            m3, ok = sample(tu, mk, np.array([tc[i] + off]), 0.02)
            if not ok[0]:
                continue
            for j, nm in enumerate(JOINTS):
                if np.isfinite(kp[i, j]).all() and nm in names:
                    X.append(m3[0, names.index(nm)])
                    x.append(kp[i, j])
        X, x = np.array(X), np.array(x)
        if len(X) < 50:
            return None, np.inf, 0.0
        rng = np.random.default_rng(0)
        best_in = None
        for _ in range(tries):
            s_ = rng.choice(len(X), 12, replace=False)
            inl = np.linalg.norm(project(ndlt(X[s_], x[s_]), X) - x, axis=1) < 25
            if best_in is None or inl.sum() > best_in.sum():
                best_in = inl
        P = ndlt(X[best_in], x[best_in])
        err = np.linalg.norm(project(P, X) - x, axis=1)
        return P, float(np.median(err)), float((err < 25).mean())

    best = (None, np.inf, 0.0, clip_unix0)
    for d in np.arange(-1.5, 1.51, 1 / 30):
        P, e, share = fit(clip_unix0 + d)
        if share > best[2]:
            best = (P, e, share, clip_unix0 + d)
    P, e, share, off = best
    P, e, share = fit(off, tries=3000)
    ni = share
    print(
        f"refined: clip t=0 at unix {off:.3f} ({off - clip_unix0:+.3f} s), median reprojection {e:.1f} px, {ni:.0%} of keypoints within 25 px"
    )
    out = {"clip": CLIP.name, "clip_unix0": off, "P": np.asarray(P).tolist(), "frame_size": [1920, 1080],
           "reprojection_median_px": e, "share_within_25px": ni, "coarse_peak": float(c.max())}  # fmt: skip
    (OUT / "camera.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
