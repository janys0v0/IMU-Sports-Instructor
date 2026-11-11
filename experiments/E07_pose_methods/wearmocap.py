"""WearMoCap's pretrained smartwatch arm-pose LSTMs (Weigend et al., IROS 2023 / ICRA 2024, MIT) on
our Apple Watch (+ pocket phone) data.

Repo: https://github.com/wearable-motion-capture/arm-pose-estimation, cloned to third_party/wearmocap.
Deployed checkpoints (src/wear_mocap_ape/data_deploy/nn/<hash>):
- WATCH_ONLY  04f4ad63...  -> method "wearmocap_watch"
- WATCH_PHONE_POCKET 670b66fa... (watch + phone hip yaw) -> method "wearmocap_watch_phone"

What the models expect (from the repo and its Wear OS app, sensor-stream-apps):
- a LEFT-wrist Wear OS watch (x toward the hand, z out of the screen), Android units: gyro rad/s,
  linear acceleration m/s^2 (physical), gravity m/s^2 pointing UP, "lvel" = linear acceleration
  integrated over the message interval, dt = message interval (~12-13 ms, i.e. ~80 Hz);
- orientation as 6D (first two columns) of the watch rotation in a calibrated, left-handed global
  frame X right, Y up, Z forward (forward fixed at the start pose);
- pressure relative to the start pose (wrist at chest height), hPa;
- phone variant: hip yaw since the start pose (sin, cos) from the pocket phone.
Outputs: lower- and upper-arm rotations (6D) in that global frame; the bone points along -X
(left T-pose); the phone variant also predicts hip yaw.

Our mapping:
- Mirror: our Watch is on the RIGHT wrist. The world is mirrored through the sagittal plane so it
  becomes a left-wrist watch. Apple Watch axes (from the Calibrate holds: gravity along +x with the
  arm hanging): x toward the hand, z out of the screen, same as the left Wear OS watch, so the
  virtual left watch's x and z are the mirror images of ours. In sensor coordinates this is
  v -> (vx, -vy, vz) for vectors and w -> (-wx, wy, -wz) for rotation rates. Outputs are mirrored
  back (right component negated).
- Frame: global Z (forward) = the hold's body forward from the pocket phone (common.body_basis), so
  the hold replaces WearMoCap's start-pose calibration (which uses the watch held level across the
  chest); no watch pose is needed for it. Watch-only output is in this fixed frame = our static
  trunk. The phone variant's arm rotations are de-rotated by its own predicted hip yaw, i.e. the
  hip frame stands in for our trunk frame.
- Pressure: no barometer in our set; fed the training mean (normalised input 0).
- Rate: inputs interpolated from the 30 Hz grid to the model's training rate (1 / mean dt), outputs
  linearly interpolated back to the grid. MC dropout replaced by eval mode (dropout off); the
  watch-only model's default 10-step causal smoothing is kept.

    .venv/bin/python -m experiments.E07_pose_methods.wearmocap
"""

import pickle
import sys

import numpy as np
import torch
from scipy.spatial.transform import Rotation, Slerp

from .common import body_basis, save
from .data import PLAYERS, ROOT, load

SRC = ROOT / "third_party" / "wearmocap" / "src"
sys.path.insert(0, str(SRC))
from wear_mocap_ape.estimate import nn_models  # noqa: E402
from wear_mocap_ape.utility import transformations as ts  # noqa: E402

DEPLOY = SRC / "wear_mocap_ape" / "data_deploy"
G = 9.81
VARIANTS = {
    "wearmocap_watch": dict(
        hash="04f4ad63bfccb3668f7598c9375403e10b1fae2a",
        stats="WATCH_ONLY_CAL_ORI_CAL_LARM_UARM",
        smooth=10,
        phone=False,
    ),
    "wearmocap_watch_phone": dict(
        hash="670b66fa7664252d1cfb3b5a8a362002ffeeba5c",
        stats="WATCH_PHONE_CAL_HIP_ORI_CAL_LARM_UARM_HIPS",
        smooth=1,
        phone=True,
    ),
}


def to_global(v_body):
    """Body (forward, up, right) -> mirrored WearMoCap global (X right, Y up, Z forward)."""
    return np.stack([-v_body[..., 2], v_body[..., 1], v_body[..., 0]], -1)


def from_global(v_glob):
    """Mirrored WearMoCap global -> our trunk frame (x forward, y up, z right)."""
    return np.stack([v_glob[..., 2], v_glob[..., 1], -v_glob[..., 0]], -1)


def resample(d, m, t_hi, dev):
    """A device's fields on a high-rate time base inside one segment."""
    t = d["t"][m]
    R = Slerp(t, Rotation.from_quat(d[f"{dev}_quat"][m]))(t_hi).as_matrix()
    lin = lambda x: np.stack([np.interp(t_hi, t, x[:, k]) for k in range(3)], 1)  # noqa: E731
    return R, lin(d[f"{dev}_gyro"][m]), lin(d[f"{dev}_acc"][m]), lin(d[f"{dev}_grav"][m])


def features(d, k, t_hi, dt, pres, phone):
    m = d["seg"] == k
    B = body_basis(d["phone_hold_quat"][k])  # world <- body
    R, gyro, acc, grav = resample(d, m, t_hi, "watch")
    Rb = np.einsum("ji,njk->nik", B, R)  # body <- watch sensor
    x = to_global(Rb[:, :, 0])  # toward the hand
    z = to_global(Rb[:, :, 2])  # out of the screen
    six = np.stack(
        [x[:, 0], z[:, 0], x[:, 1], z[:, 1], x[:, 2], z[:, 2]], 1
    )  # columns x, z of [x z y]
    pol = np.array([1.0, -1.0, 1.0])
    lacc = -G * acc * pol  # Apple userAcceleration is minus the physical one
    gr = -G * grav * pol  # Android gravity points up
    w = gyro * np.array([-1.0, 1.0, -1.0])
    n = len(t_hi)
    cols = [np.full((n, 1), dt), w, lacc * dt, lacc, gr, six, np.full((n, 1), pres)]
    if phone:
        Rp, *_ = resample(d, m, t_hi, "phone")
        Rp0 = Rotation.from_quat(d["phone_hold_quat"][k]).as_matrix()
        f = np.einsum(
            "ji,njk,lk,l->ni", B, Rp, Rp0, B[:, 0]
        )  # body forward turned by the phone since the hold
        fg = to_global(f)
        yaw = np.arctan2(fg[:, 0], fg[:, 2])
        cols += [np.sin(yaw)[:, None], np.cos(yaw)[:, None]]
    return np.hstack(cols).astype(np.float32)


def predict(model, xx, seq_len, stats):
    xx = (xx - stats["xx_m"]) / stats["xx_s"]
    pad = np.vstack([np.repeat(xx[:1], seq_len - 1, 0), xx])
    idx = np.arange(len(xx))[:, None] + np.arange(seq_len)[None, :]
    out = []
    with torch.no_grad():
        for s in range(0, len(xx), 4096):
            win = torch.tensor(pad[idx[s : s + 4096]], dtype=torch.float32)
            out.append(model(win)[:, -1, :].numpy())
    return np.vstack(out) * stats["yy_s"] + stats["yy_m"]


def causal_mean(y, w):
    if w <= 1:
        return y
    c = np.cumsum(np.vstack([np.repeat(y[:1], w, 0), y]), 0)
    return (c[w:] - c[:-w]) / w


def bone_dirs(y, phone):
    larm = ts.six_drr_1x6_to_rot_mat_1x9(y[:, :6]).reshape(-1, 3, 3)
    uarm = ts.six_drr_1x6_to_rot_mat_1x9(y[:, 6:12]).reshape(-1, 3, 3)
    fore, hum = -larm[:, :, 0], -uarm[:, :, 0]  # bone along -X
    if phone:
        yaw = np.arctan2(y[:, 12], y[:, 13])
        H = ts.quat_to_rot_mat_1x9(ts.hips_sin_cos_to_quat(y[:, 12], y[:, 13])).reshape(-1, 3, 3)
        assert np.allclose(np.arctan2(H[:, 0, 2], H[:, 2, 2]), yaw, atol=1e-6)  # H turns Z by yaw
        fore, hum = np.einsum("nji,nj->ni", H, fore), np.einsum("nji,nj->ni", H, hum)
    return hum, fore


def run(d, name, cfg):
    model, params = nn_models.load_deployed_model_from_hash(cfg["hash"])
    model.eval()
    with open(DEPLOY / "data_stats" / f"{cfg['stats']}.pkl", "rb") as fh:
        stats = pickle.load(fh)  # the repo's own normalisation stats (trusted local checkout)
    assert stats["x_inputs"] == params["x_inputs_v"]
    dt = float(stats["xx_m"][0])
    pres = float(stats["xx_m"][params["x_inputs_v"].index("sw_pres_cal")])
    n = len(d["t"])
    hum, fore = np.full((n, 3), np.nan), np.full((n, 3), np.nan)
    for k in np.unique(d["seg"]):
        m = d["seg"] == k
        t = d["t"][m]
        t_hi = np.minimum(np.arange(t[0], t[-1], dt), t[-1])
        xx = features(d, k, t_hi, dt, pres, cfg["phone"])
        y = causal_mean(predict(model, xx, params["sequence_len"], stats), cfg["smooth"])
        h, f = bone_dirs(y, cfg["phone"])
        for src, dst in ((h, hum), (f, fore)):
            v = np.stack([np.interp(t, t_hi, src[:, j]) for j in range(3)], 1)
            dst[m] = from_global(v / np.linalg.norm(v, axis=1, keepdims=True))
    valid = d["watch_valid"].astype(bool) & (
        d["phone_valid"].astype(bool) if cfg["phone"] else True
    )
    return hum, fore, valid


def main():
    for p in PLAYERS:
        d = load(p)
        for name, cfg in VARIANTS.items():
            hum, fore, valid = run(d, name, cfg)
            path = save(p, name, hum, fore, valid=valid)
            first = [np.nonzero(d["seg"] == k)[0][:30] for k in np.unique(d["seg"])]
            print(
                p,
                name,
                "-> ",
                path.name,
                "| first 1 s per segment: hum",
                [hum[i].mean(0).round(2) for i in first],
                "fore",
                [fore[i].mean(0).round(2) for i in first],
            )


if __name__ == "__main__":
    main()
