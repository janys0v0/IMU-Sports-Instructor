"""Model errors against device signals: when does each model drift away from a sensor?

Run from project/code after run.py:
    .venv/bin/python experiments/E02_imucoco_comparison/plot_error_vs_signals.py [SESSION]

Rows = sensor-bearing bones (head/AirPods, right thigh/phone, right forearm/Watch). Columns =
what that bone's own device was doing in the same 30 Hz frame:
  rotation rate (rad/s) | body-frame acceleration (m/s^2) | rotation away from the calibration
  pose (deg) | age of the nearest real sample (ms; large = model input interpolated over a gap).
Lines = median model-vs-sensor angle per bin (band = interquartile range) for MobilePoser and
IMUCoCo, solid when the models were given that sensor (all devices) and dashed when it was held
out (largest combination without it). Dots = individual frames for the all-devices runs.
Agreement with the sensor, not ground-truth error. Reads saved outputs only.
Writes results/<SESSION>/error_vs_signals.png and error_vs_signals.json (Spearman rho per panel).
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import metrics, paths, stream_quality  # noqa: E402
from common import mobileposer_runner as mp  # noqa: E402
from common.session import load_session  # noqa: E402

MODELS = {"MobilePoser": "#1f77b4", "IMUCoCo": "#d62728"}
BONES = {
    "head": "head (AirPods)",
    "right_pocket": "right thigh (phone)",
    "right_wrist": "right forearm (Watch)",
}
HELD_OUT = {
    "head": "rw_rp",
    "right_pocket": "rw_h",
    "right_wrist": "rp_h",
}  # largest combo without the sensor
FULL = "rw_rp_h"
SIGNALS = [
    ("rot_rate", "device rotation rate (rad/s)"),
    ("acc", "body-frame acceleration (m/s²)"),
    ("from_cal", "rotation from calibration pose (deg)"),
    ("age", "age of nearest real sample (ms)"),
]


def model_angles(res, combo, session, body):
    import torch

    out = {}
    for model in MODELS:
        d = np.load(res / "outputs" / f"{model}_{combo}.npz")
        glb = body.forward_kinematics(torch.from_numpy(d["pose"]).float())[0].numpy()
        sig = metrics.signals(
            mp.Output(d["t"], d["pose"], glb, d["joints"], d["tran"]),
            metrics.reference(session, len(d["t"])),
        )
        out[model] = {b: sig[f"orientation_error_{b}"] for b in BONES}
    return out


def device_signals(session, rec, n):
    """bone -> signal name -> (n,) per-frame value from that bone's own device."""
    t = np.concatenate([s.t for s in session.segments])[:n]
    out = {}
    for b in BONES:
        rr = np.concatenate([s.devices[b].rot_rate for s in session.segments])[:n]
        acc = np.concatenate([s.devices[b].acc for s in session.segments])[:n]
        ori = np.concatenate([s.devices[b].ori for s in session.segments])[:n]
        raw = rec.streams[b].t
        k = np.clip(np.searchsorted(raw, t), 1, len(raw) - 1)
        age = np.minimum(np.abs(t - raw[k - 1]), np.abs(raw[k] - t)) * 1000
        out[b] = {
            "rot_rate": np.linalg.norm(rr, axis=1),
            "acc": np.linalg.norm(acc, axis=1),
            "from_cal": metrics.angle_deg(ori, np.eye(3)),
            "age": age,
        }
    return t, out


def binned(x, y, edges):
    centers, med, q1, q3 = [], [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        w = (x >= lo) & (x < hi)
        if w.sum() >= 15:
            centers.append((lo + hi) / 2)
            med.append(np.median(y[w]))
            q1.append(np.percentile(y[w], 25))
            q3.append(np.percentile(y[w], 75))
    return map(np.asarray, (centers, med, q1, q3))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default="20261008-153213-P01")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    res = paths.results_dir(HERE / "run.py", args.session)
    session = load_session(args.session)
    rec = stream_quality.load(args.session)
    annotation = metrics.load_annotation(session.name)
    body = mp.body_model()
    full = model_angles(res, FULL, session, body)
    held = {b: model_angles(res, HELD_OUT[b], session, body) for b in BONES}
    n = min(
        len(next(iter(full.values()))["head"]),
        *(len(h["MobilePoser"]["head"]) for h in held.values()),
    )
    t, dev = device_signals(session, rec, n)
    routine = (
        np.any([(t >= a["start"]) & (t <= a["end"]) for a in annotation["activities"]], axis=0)
        if annotation
        else np.ones(n, bool)
    )

    fig, axes = plt.subplots(len(BONES), len(SIGNALS), figsize=(19, 12.5))
    stats = {}
    for r, (b, bname) in enumerate(BONES.items()):
        stats[b] = {}
        for c, (key, xlabel) in enumerate(SIGNALS):
            ax = axes[r, c]
            x = dev[b][key][routine]
            hi = np.percentile(x, 99)
            edges = (
                np.unique(np.quantile(x[x <= hi], np.linspace(0, 1, 13)))
                if key != "age"
                else np.array([0, 10, 20, 30, 50, 100, 200, 400])
            )
            stats[b][key] = {}
            for model, color in MODELS.items():
                for case, data, ls in (
                    ("input", full[model][b], "-"),
                    ("held out", held[b][model][b], "--"),
                ):
                    y = data[:n][routine]
                    if case == "input":
                        ax.scatter(np.minimum(x, hi * 1.05), y, s=2, color=color, alpha=0.12, lw=0)
                    cx, med, q1, q3 = binned(x, y, edges)
                    ax.plot(
                        cx,
                        med,
                        ls,
                        color=color,
                        lw=1.8 if case == "input" else 1.3,
                        label=f"{model}, sensor {case}",
                    )
                    if case == "input":
                        ax.fill_between(cx, q1, q3, color=color, alpha=0.15, lw=0)
                    rho = spearmanr(x, y).correlation
                    stats[b][key][f"{model} ({case})"] = round(float(rho), 2)
            if key == "age":
                ax.set_xscale("symlog", linthresh=30)
                ax.axvline(100, color="gray", lw=0.8, ls=":")
            else:
                ax.set_xlim(0, hi * 1.05)
            ax.set_ylim(0, None)
            ax.grid(alpha=0.3)
            s_in = stats[b][key]
            ax.text(
                0.98,
                0.97,
                "Spearman ρ (input / held out)\n"
                f"MP {s_in['MobilePoser (input)']:+.2f} / {s_in['MobilePoser (held out)']:+.2f}\n"
                f"CoCo {s_in['IMUCoCo (input)']:+.2f} / {s_in['IMUCoCo (held out)']:+.2f}",
                transform=ax.transAxes,
                ha="right",
                va="top",
                fontsize=7,
                bbox=dict(facecolor="white", alpha=0.85, lw=0),
            )
            if r == len(BONES) - 1:
                ax.set_xlabel(xlabel)
            if c == 0:
                ax.set_ylabel(f"{bname}\nmodel vs sensor angle (deg)")
            if r == 0:
                ax.set_title(xlabel.split(" (")[0], fontsize=11)
    axes[0, 0].legend(fontsize=7.5, loc="upper left")
    fig.suptitle(
        f"{session.name}: model-vs-sensor angle against each bone's own device signal "
        f"(frames in the annotated routine, n = {int(routine.sum())})",
        fontsize=13,
    )
    fig.text(
        0.5,
        0.005,
        "Solid + band: models given all devices (median, interquartile range). Dashed: sensor held out "
        "(head: Watch+phone; thigh: Watch+AirPods; forearm: phone+AirPods). Dots: frames, all-devices runs. "
        "Agreement with the sensor, not ground-truth error.",
        ha="center",
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(res / "error_vs_signals.png", dpi=100)
    (res / "error_vs_signals.json").write_text(
        json.dumps(
            {"session": session.name, "frames": int(routine.sum()), "spearman_rho": stats}, indent=2
        )
    )
    print("Saved", res / "error_vs_signals.png")


if __name__ == "__main__":
    main()
