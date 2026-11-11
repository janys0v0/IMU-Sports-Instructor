"""Our own learned arm models, trained on the 10/28 data against OpenCap.

Inputs are heading-free (no magnetometer or body-forward needed): each device's gravity direction,
rotation rate and acceleration in its own frame, and the Watch's orientation relative to the
pocket phone (and, in the commercial blocks, the upper-arm and chest sensors relative to each
other). Outputs: the upper-arm and forearm long axes in the trunk frame.

Splits: "xplayer" trains on the other player only; "personal" adds the test player's own minutes
outside the scored block (the E07 commercial block; at least 10 s away). Scored on the block grid.

Models: ridge regression on per-frame features plus ±0.5 s context means (a linear baseline), and a
bidirectional GRU over 4 s windows (CPU).

    .venv/bin/python -m experiments.E07_pose_methods.learned_own
"""

import numpy as np
from scipy.spatial.transform import Rotation

from .common import save
from .data import PLAYERS, load

VARIANTS = {
    "watch": ["watch"],
    "watch_phone": ["watch", "phone"],
    "watch_phone_airpods": ["watch", "phone", "airpods"],
}
WIN, HOP = 120, 30


def r6(R):
    return R[:, :, :2].reshape(len(R), 6)


def features(d, devs, extra=None):
    f = []
    for dv in devs:
        f += [d[f"{dv}_grav"], d[f"{dv}_gyro"] / 10.0, d[f"{dv}_acc"]]
    if "phone" in devs:
        Rp = Rotation.from_quat(d["phone_quat"]).as_matrix()
        Rw = Rotation.from_quat(d["watch_quat"]).as_matrix()
        f.append(r6(np.einsum("nji,njk->nik", Rp, Rw)))
    if extra is not None:
        f.append(extra)
    return np.concatenate(f, 1).astype(np.float32)


def targets(d):
    return np.concatenate([d["gt_hum"], d["gt_fore"]], 1).astype(np.float32)


def split_mask(full, block):
    """Frames of the full dataset at least 10 s away from every block frame."""
    t = full["t"]
    lo, hi = block["t"][0] - 10, block["t"][-1] + 10
    return ~((t > lo) & (t < hi))


def windows(n, seg):
    starts = []
    for k in np.unique(seg):
        idx = np.nonzero(seg == k)[0]
        a, b = idx[0], idx[-1] + 1
        s = list(range(a, max(a + 1, b - WIN + 1), HOP))
        if b - WIN > a and s[-1] != b - WIN:
            s.append(b - WIN)
        starts += [x for x in s if x + WIN <= b]
    return np.array(starts)


class GRU:
    def __init__(self, n_in, hidden=96, device=None):
        import torch

        self.torch = torch
        self.dev = (
            device or "cpu"
        )  # MPS returns NaN for this GRU in torch 2.1; CPU is fast enough here
        self.net = torch.nn.ModuleDict(
            {
                "gru": torch.nn.GRU(
                    n_in, hidden, num_layers=2, batch_first=True, bidirectional=True, dropout=0.2
                ),
                "out": torch.nn.Linear(2 * hidden, 6),
            }
        ).to(self.dev)

    def forward(self, x):
        h, _ = self.net["gru"](x)
        y = self.net["out"](h).view(*h.shape[:2], 2, 3)
        return self.torch.nn.functional.normalize(y, dim=-1).view(*h.shape[:2], 6)

    def fit(self, X, Y, M, seg, epochs=40, lr=2e-3, seed=0):
        torch = self.torch
        torch.manual_seed(seed)
        st = windows(len(X), seg)
        xs = torch.tensor(np.stack([X[s : s + WIN] for s in st])).to(self.dev)
        ys = torch.tensor(np.stack([Y[s : s + WIN] for s in st])).to(self.dev)
        ms = torch.tensor(np.stack([M[s : s + WIN] for s in st])).float().to(self.dev)
        opt = torch.optim.AdamW(self.net.parameters(), lr=lr, weight_decay=1e-3)
        self.net.train()
        for _ in range(epochs):
            perm = torch.randperm(len(xs))
            for b in range(0, len(xs), 64):
                i = perm[b : b + 64]
                xb = xs[i] + 0.02 * torch.randn_like(xs[i])
                p = self.forward(xb)
                cos = (p.view(*p.shape[:2], 2, 3) * ys[i].view(*p.shape[:2], 2, 3)).sum(
                    -1
                )  # (B, T, 2)
                loss = ((1 - cos).sum(-1) * ms[i]).sum() / ms[i].sum().clamp(min=1)
                opt.zero_grad()
                loss.backward()
                opt.step()
        return self

    def predict(self, X, seg):
        torch = self.torch
        out, cnt = np.zeros((len(X), 6)), np.zeros(len(X))
        st = windows(len(X), seg)
        w = np.hanning(WIN + 2)[1:-1]
        self.net.eval()  # dropout off at test time
        with torch.no_grad():
            for b in range(0, len(st), 256):
                ss = st[b : b + 256]
                p = (
                    self.forward(torch.tensor(np.stack([X[s : s + WIN] for s in ss])).to(self.dev))
                    .cpu()
                    .numpy()
                )
                for s, pp in zip(ss, p):
                    out[s : s + WIN] += pp * w[:, None]
                    cnt[s : s + WIN] += w
        out = out / np.maximum(cnt, 1e-9)[:, None]
        return out


def context(X, seg, half=15):
    """Per-frame features plus their mean and std over ±half frames (within the segment)."""
    from scipy.ndimage import uniform_filter1d

    m, m2 = np.empty_like(X), np.empty_like(X)
    for k in np.unique(seg):
        i = np.nonzero(seg == k)[0]
        m[i] = uniform_filter1d(X[i], 2 * half + 1, axis=0, mode="nearest")
        m2[i] = uniform_filter1d(X[i] ** 2, 2 * half + 1, axis=0, mode="nearest")
    sd = np.sqrt(np.maximum(m2 - m**2, 0))
    return np.concatenate([X, m, sd], 1)


def ridge_fit_predict(Xtr, Ytr, Xte, lam=10.0):
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    A = (Xtr - mu) / sd
    A = np.c_[A, np.ones(len(A))]
    W = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ Ytr)
    B = np.c_[(Xte - mu) / sd, np.ones(len(Xte))]
    return B @ W


def unit_pair(P):
    h, f = P[:, :3], P[:, 3:]
    return h / np.linalg.norm(h, axis=1, keepdims=True), f / np.linalg.norm(
        f, axis=1, keepdims=True
    )


def run_split(test, name, devs, split, model):
    other = [p for p in PLAYERS if p != test][0]
    blk = load(test)
    tr_sets = [load(other, full=True)]
    if split == "personal":
        full = load(test, full=True)
        keep = split_mask(full, blk) & full["gt_valid"]
        if keep.sum() < 30 * 60:  # less than a minute of the test player outside the block
            print(f"{test}: no own data outside the block, personal split skipped")
            return
        keep = split_mask(full, blk)
        tr_sets.append(
            {
                k: (v[keep] if hasattr(v, "shape") and v.shape[:1] == keep.shape else v)
                for k, v in full.items()
            }
        )
    Xtr = [features(s, devs) for s in tr_sets]
    Ytr = [targets(s) for s in tr_sets]
    Mtr = [s["gt_valid"] for s in tr_sets]
    segtr = [s["seg"] + 1000 * i for i, s in enumerate(tr_sets)]
    Xte = features(blk, devs)
    mu = np.concatenate(Xtr).mean(0)
    sd = np.concatenate(Xtr).std(0) + 1e-6
    if model == "ridge":
        Xc = [context(x, s) for x, s in zip(Xtr, segtr)]
        M = np.concatenate(Mtr)
        P = ridge_fit_predict(
            np.concatenate(Xc)[M], np.concatenate(Ytr)[M], context(Xte, blk["seg"])
        )
    else:
        X = np.concatenate([(x - mu) / sd for x in Xtr]).astype(np.float32)
        net = GRU(X.shape[1]).fit(
            X, np.concatenate(Ytr), np.concatenate(Mtr), np.concatenate(segtr)
        )
        P = net.predict(((Xte - mu) / sd).astype(np.float32), blk["seg"])
    hum, fore = unit_pair(P)
    save(test, f"own_{model}_{name}_{split}", hum, fore, valid=np.isfinite(fore).all(1))


def all_sensor_features(player):
    """Apple features plus the aligned commercial upper arm and chest (blocks only)."""
    from .align import load_aligned

    d = load(player)
    a = load_aligned(player)
    rel = lambda A, B: r6(np.einsum("nji,njk->nik", A, B))  # noqa: E731
    extra = np.concatenate(
        [
            rel(a["trunk_R"], a["upper_R"]),
            rel(a["trunk_R"], a["watch_R"]),
            rel(a["upper_R"], a["watch_R"]),
            d["upper_arm_grav"],
            d["upper_arm_gyro"] / 10,
            d["upper_arm_acc"],
            d["trunk_grav"],
            d["trunk_gyro"] / 10,
            d["trunk_acc"],
        ],
        1,
    )
    return d, features(d, ["watch", "phone", "airpods"], extra)


def run_all_sensors(test, model):
    """Every sensor; trained on the other player's block (xplayer) and, 'personal', also on the test
    player's other half of the block (two-fold in time, 10 s gap)."""
    other = [p for p in PLAYERS if p != test][0]
    dtr, Xo = all_sensor_features(other)
    dte, Xt = all_sensor_features(test)
    for split in ("xplayer", "personal"):
        P = np.full((len(Xt), 6), np.nan)
        half = np.median(dte["t"])
        folds = [None] if split == "xplayer" else [dte["t"] < half, dte["t"] >= half]
        for test_mask in folds:
            Xtr, Ytr, Mtr, Str = [Xo], [targets(dtr)], [dtr["gt_valid"]], [dtr["seg"]]
            if test_mask is not None:
                far = np.abs(dte["t"] - half) > 10
                tr_mask = ~test_mask & far
                Xtr.append(Xt[tr_mask])
                Ytr.append(targets(dte)[tr_mask])
                Mtr.append(dte["gt_valid"][tr_mask])
                Str.append(dte["seg"][tr_mask] + 1000)
            mu = np.concatenate(Xtr).mean(0)
            sd = np.concatenate(Xtr).std(0) + 1e-6
            if model == "ridge":
                Xc = [context(x, s_) for x, s_ in zip(Xtr, Str)]
                M = np.concatenate(Mtr)
                pred = ridge_fit_predict(
                    np.concatenate(Xc)[M], np.concatenate(Ytr)[M], context(Xt, dte["seg"])
                )
            else:
                X = np.concatenate([(x - mu) / sd for x in Xtr]).astype(np.float32)
                net = GRU(X.shape[1]).fit(
                    X, np.concatenate(Ytr), np.concatenate(Mtr), np.concatenate(Str)
                )
                pred = net.predict(((Xt - mu) / sd).astype(np.float32), dte["seg"])
            sel = np.ones(len(Xt), bool) if test_mask is None else test_mask
            P[sel] = pred[sel]
        hum, fore = unit_pair(P)
        save(test, f"own_{model}_allsensors_{split}", hum, fore, valid=np.isfinite(fore).all(1))


def main():
    import sys

    models = [m for m in ("ridge", "gru") if m in sys.argv] or ["ridge", "gru"]
    if "--all-sensors" in sys.argv:
        for model in models:
            for test in PLAYERS:
                run_all_sensors(test, model)
                print(model, "allsensors", test, "done", flush=True)
        return
    for model in models:
        for name, devs in VARIANTS.items():
            for split in ("xplayer", "personal"):
                for test in PLAYERS:
                    run_split(test, name, devs, split, model)
                    print(model, name, split, test, "done", flush=True)


if __name__ == "__main__":
    main()
