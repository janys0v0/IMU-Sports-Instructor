"""Phone1 camera footage with OpenCap's skeleton drawn on it.

- Camera: phone1 (on a stand by the net, the same view both sessions) is not one of OpenCap's two
  calibrated cameras, so its 3 x 4 projection is fitted here, by DLT with RANSAC, from OpenCap's
  3D markers and the player's feet and head top found in phone1 frames (difference from the
  median frame = the empty court; the largest moving blob above the net is the player).
- Time: the clip's first frame on our clock, from its sound against the commercial logger's
  (`sync.py`), then the logger's known offset from our clock.

Fit once, after run.py and with OpenCap aligned (writes results/phone1_camera.json):
    .venv/bin/python -m experiments.E06_side_by_side.camera
"""

import json
from pathlib import Path

import cv2
import numpy as np

from . import sync

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parents[1] / "data" / "external" / "20261028"
CAMERA_JSON = ROOT / "results" / "phone1_camera.json"
# label -> (phone1 clip, logger audio, OpenCap trial)
CLIPS = {
    "janys-IMU1": ("phone1/janys_IMG_0032.MOV", "IMU1/tennis_20261028T1100_20261028T1231_audio.flac", "janys"),
    "tom-IMU4": ("phone1/tom_IMG_0033.MOV", "IMU4/tennis_20261028T1131_20261028T1236_audio.flac", "tom"),
}  # fmt: skip
HEAD_ABOVE_NECK_M = 0.27  # OpenCap has no head-top marker
BONES = [("Neck", "RShoulder"), ("RShoulder", "RElbow"), ("RElbow", "RWrist"), ("Neck", "LShoulder"),
         ("LShoulder", "LElbow"), ("LElbow", "LWrist"), ("Neck", "midHip"), ("midHip", "RHip"),
         ("RHip", "RKnee"), ("RKnee", "RAnkle"), ("RAnkle", "RHeel"), ("RHeel", "RBigToe"),
         ("midHip", "LHip"), ("LHip", "LKnee"), ("LKnee", "LAnkle"), ("LAnkle", "LHeel"), ("LHeel", "LBigToe")]  # fmt: skip


def clip_start_unix(clip, logger_flac, logger_csv, logger_lag_s) -> tuple:
    """(our-clock unix time of the clip's first frame, onset match z-score). `logger_lag_s`: logger
    clock minus ours (run.py's clock_lag_s)."""
    start = sync.logger_start_unix(logger_flac, logger_csv)
    ref, other = sync.onsets(sync.read_audio(logger_flac)), sync.onsets(sync.read_audio(clip))
    n = 1 << int(np.ceil(np.log2(len(ref) + len(other))))
    c = np.fft.irfft(np.fft.rfft(other, n) * np.conj(np.fft.rfft(ref, n)), n)
    k = int(np.argmax(c))
    off = (k if k < n // 2 else k - n) / sync.RATE  # logger-audio time a is clip time a + off
    return start - off - logger_lag_s, float((c[k] - np.median(c)) / c.std())


def dlt(X, x) -> np.ndarray:
    A = []
    for (a, b, c), (u, v) in zip(X, x):
        A.append([a, b, c, 1, 0, 0, 0, 0, -u * a, -u * b, -u * c, -u])
        A.append([0, 0, 0, 0, a, b, c, 1, -v * a, -v * b, -v * c, -v])
    return np.linalg.svd(np.array(A))[2][-1].reshape(3, 4)


def project(P, X) -> np.ndarray:
    """OpenCap points (n, 3) -> pixels (n, 2) of the full-size clip."""
    h = np.c_[X, np.ones(len(X))] @ np.asarray(P).T
    return h[:, :2] / h[:, 2:]


def fit_projection(X, x, tol_px=25.0, tries=3000, seed=0) -> tuple:
    """DLT on RANSAC inliers: (P, inlier mask)."""
    rng = np.random.default_rng(seed)
    best = np.zeros(len(X), bool)
    for _ in range(tries):
        i = rng.choice(len(X), 8, replace=False)
        inl = np.linalg.norm(project(dlt(X[i], x[i]), X) - x, axis=1) < tol_px
        if inl.sum() > best.sum():
            best = inl
    P = dlt(X[best], x[best])
    return P, np.linalg.norm(project(P, X) - x, axis=1) < tol_px


def below_net(u, v) -> np.ndarray:
    """Pixels in front of the net (lower right of phone1's view), where the net's sway shows up."""
    return v > 1080 - (u - 660) * (440 / 1260)


def player_points(clip, clip_unix, unix0, mk_t, mk, names, step_s=4.0):
    """(3D, 2D) feet and head-top pairs, one of each every `step_s` of OpenCap time."""
    cap = cv2.VideoCapture(str(clip))
    fps, nfr = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def frame(i):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        return cv2.resize(f, (960, 540)) if ok else None

    bg = np.median(np.stack([frame(i) for i in np.linspace(100, nfr - 100, 41)]), axis=0).astype(
        np.uint8
    )
    i_of = {n: k for k, n in enumerate(names)}
    X, x = [], []
    for tq in np.arange(mk_t[0] + 1, mk_t[-1] - 1, step_s):
        j = int(np.argmin(np.abs(mk_t - tq)))
        fi = round((mk_t[j] + unix0 - clip_unix) * fps)
        f = frame(fi) if abs(mk_t[j] - tq) < 0.05 and 0 <= fi < nfr else None
        if f is None:
            continue
        m = cv2.morphologyEx((cv2.absdiff(f, bg).max(axis=2) > 40).astype(np.uint8), cv2.MORPH_CLOSE,
                             np.ones((7, 5), np.uint8))  # fmt: skip
        m[:120] = 0  # far courts and stands
        n, lab, st, _ = cv2.connectedComponentsWithStats(m)
        if n < 2:
            continue
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        _, y, _, h, area = st[k]
        if area < 300 or h < 40:
            continue
        ys, xs = np.nonzero(lab == k)
        foot = (2 * np.median(xs[ys > y + 0.85 * h]), 2 * (y + h))
        if below_net(*foot):
            continue
        head = (2 * np.median(xs[ys < y + 0.12 * h]), 2 * y)
        M = mk[j]
        ground = M[[i_of["RHeel"], i_of["LHeel"], i_of["RBigToe"], i_of["LBigToe"]]].mean(axis=0)
        X += [ground, M[i_of["Neck"]] + [0, HEAD_ABOVE_NECK_M, 0]]
        x += [foot, head]
    return np.array(X), np.array(x)


def draw_skeleton(img, uv, names, right=(60, 60, 210), left=(230, 200, 60), thick=3):
    i = {n: k for k, n in enumerate(names)}
    for a, b in BONES:
        color = right if a.startswith("R") or b.startswith("R") else left
        if (a, b) == ("Neck", "midHip"):
            color = (255, 255, 255)
        pa, pb = tuple(np.round(uv[i[a]]).astype(int)), tuple(np.round(uv[i[b]]).astype(int))
        cv2.line(img, pa, pb, (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.line(img, pa, pb, color, thick, cv2.LINE_AA)
    for k in range(len(names)):
        cv2.circle(img, tuple(np.round(uv[k]).astype(int)), thick, (255, 255, 255), -1, cv2.LINE_AA)


class Follow:
    """A crop that follows the player smoothly (exponential smoothing of the hip position)."""

    def __init__(self, frame_size, crop_size, alpha=0.15):
        self.W, self.H = frame_size
        self.w, self.h = crop_size
        self.alpha, self.c = alpha, None

    def window(self, centre):
        if centre is not None:
            c = np.asarray(centre, float)
            self.c = c if self.c is None else (1 - self.alpha) * self.c + self.alpha * c
        if self.c is None:
            self.c = np.array([self.W / 2, self.H / 2])
        x0 = int(np.clip(self.c[0] - self.w / 2, 0, self.W - self.w))
        y0 = int(np.clip(self.c[1] - self.h * 0.55, 0, self.H - self.h))
        return x0, y0


def main():
    from pipeline.preprocessing.motion_io import load_recording

    from .make_video import opencap_markers, opencap_series

    X, x, out = [], [], {"clips": {}}
    for label, (clip, flac, trial) in CLIPS.items():
        meta = json.loads((ROOT / "results" / label / "meta.json").read_text())
        clip_unix, z = clip_start_unix(DATA / clip, DATA / flac, (DATA / flac).with_suffix(".csv"),
                                       meta["clock_lag_s"])  # fmt: skip
        rec = load_recording(Path(meta["session_dir"]))
        w = next(s for s in rec.streams.values() if s.device == "watch")
        _, unix0, _ = opencap_series(DATA / "aligned_hrnet3" / trial, w.t + w.boot_to_unix, w.rot_rate,
                                     np.zeros(1))  # fmt: skip
        mk_t, mk, names = opencap_markers(DATA / "aligned_hrnet3" / trial)
        Xi, xi = player_points(DATA / clip, clip_unix, unix0, mk_t, mk, names)
        X.append(Xi)
        x.append(xi)
        out["clips"][label] = {"clip": clip, "start_unix": clip_unix, "audio_match_z": round(z, 1)}
        print(f"{label}: clip starts {clip_unix:.3f} (audio match z {z:.1f}), {len(Xi)} points")
    P, inl = fit_projection(np.concatenate(X), np.concatenate(x))
    err = np.linalg.norm(project(P, np.concatenate(X)) - np.concatenate(x), axis=1)
    out.update(P=(P / np.linalg.norm(P)).tolist(), frame_size=[1920, 1080], inliers=f"{inl.sum()}/{len(inl)}",
               median_inlier_err_px=round(float(np.median(err[inl])), 1))  # fmt: skip
    CAMERA_JSON.write_text(json.dumps(out, indent=1) + "\n")
    print(
        f"inliers {out['inliers']}, median error {out['median_inlier_err_px']} px -> {CAMERA_JSON}"
    )


if __name__ == "__main__":
    main()
