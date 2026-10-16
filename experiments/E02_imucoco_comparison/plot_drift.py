"""Relative drift of MobilePoser and IMUCoCo on a common baseline.

Run from project/code after run.py:
    .venv/bin/python -m experiments.E02_imucoco_comparison.plot_drift [SESSION]

Both models are zeroed on the same reference, the "standing_still" window right after
calibration, so constant offsets cancel and only change over time is compared:
- Translation drift: the reference routine is done in place, so true horizontal root motion is
  ~0 and the model's horizontal root displacement from the reference window is drift (metres).
- Orientation drift: for each sensor-bearing bone, a constant model-to-sensor rotation is fitted
  in the reference window and removed; the residual angle over time is drift plus motion-related
  error. Drift itself is read only where the device returns to the reference pose (still: rotation
  rate < 0.3 rad/s, and within 20 deg of its calibration orientation): there the true pose matches
  the reference, so what remains is drift. Drift rate (deg/min) = line fitted to those frames; it
  is left empty when a device never returns to its reference pose.
Writes results/<SESSION>/drift.png and drift.json. Reads saved outputs only.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from experiments.common import metrics, paths
from experiments.common import mobileposer_runner as mp
from experiments.common.session import SENSOR_JOINT, load_session

HERE = Path(__file__).resolve().parent

MODELS = {"MobilePoser": "#1f77b4", "IMUCoCo": "#d62728"}
BONES = {
    "head": "head (AirPods)",
    "right_pocket": "right thigh (phone)",
    "right_wrist": "right forearm (Watch)",
}
COMBOS = ["rw_rp_h", "rw_rp", "rp_h", "rp", "rw_h", "rw", "h"]
LABEL = {
    "rw_rp_h": "Watch+phone+AirPods",
    "rw_rp": "Watch+phone",
    "rp_h": "phone+AirPods",
    "rp": "phone",
    "rw_h": "Watch+AirPods",
    "rw": "Watch",
    "h": "AirPods",
}
ACT_COLORS = {
    "standing_still": "#7f7f7f",
    "jumping_jacks": "#2ca02c",
    "tennis_swings": "#9467bd",
    "squats": "#ff7f0e",
    "head_turns": "#8c564b",
}
STILL_RAD_S = 0.3
NEAR_REF_DEG = 20.0


def load(res, model, combo, body):
    import torch

    d = np.load(res / "outputs" / f"{model}_{combo}.npz")
    glb = body.forward_kinematics(torch.from_numpy(d["pose"]).float())[0].numpy()
    return d["t"], d["tran"], glb


def translation_drift(t, tran, ref_w, end):
    """Horizontal distance (m) of the root from its mean position in the reference window."""
    h = tran[:, [0, 2]] - tran[ref_w][:, [0, 2]].mean(axis=0)
    return np.linalg.norm(h, axis=1), h


def orientation_residual(R_model, R_sensor, ref_w):
    """Angle between model bone and sensor after removing the constant offset fitted in ref_w."""
    offset = (
        Rotation.from_matrix(np.swapaxes(R_sensor[ref_w], 1, 2) @ R_model[ref_w]).mean().as_matrix()
    )
    return metrics.angle_deg(R_model, R_sensor @ offset)


def shade(ax, annotation):
    for a in annotation["activities"]:
        ax.axvspan(a["start"], a["end"], color=ACT_COLORS.get(a["name"], "gray"), alpha=0.08, lw=0)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default="20261008-153213-P01")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    res = paths.results_dir(HERE / "run.py", args.session)
    session = load_session(args.session)
    annotation = metrics.load_annotation(session.name)
    acts = {a["name"]: a for a in annotation["activities"]}
    ref_a = acts["standing_still"]
    end = max(a["end"] for a in annotation["activities"])
    body = mp.body_model()
    rot_rate = {
        b: np.linalg.norm(np.concatenate([s.devices[b].rot_rate for s in session.segments]), axis=1)
        for b in BONES
    }
    from_ref = {
        b: metrics.angle_deg(
            np.concatenate([s.devices[b].ori for s in session.segments]), np.eye(3)
        )
        for b in BONES
    }

    def at_reference(b, t):
        n = len(t)
        return (
            (t >= ref_a["start"])
            & (t <= end)
            & (rot_rate[b][:n] < STILL_RAD_S)
            & (from_ref[b][:n] < NEAR_REF_DEG)
        )

    out = {
        "reference_window_s": [ref_a["start"], ref_a["end"]],
        "routine_end_s": end,
        "full": {},
        "translation_by_combo": {},
    }
    runs = {}
    for model in MODELS:
        t, tran, glb = load(res, model, "rw_rp_h", body)
        ref_w = (t >= ref_a["start"]) & (t <= ref_a["end"])
        r = t <= end
        dist, horiz = translation_drift(t, tran, ref_w, end)
        sensors = metrics.reference(session, len(t))
        resid = {
            b: orientation_residual(glb[:, SENSOR_JOINT[b]], sensors[b][0], ref_w) for b in BONES
        }
        rates = {}
        for b in BONES:
            back = at_reference(b, t)
            late = back & (
                t > ref_a["end"] + 5
            )  # returns to the reference pose later in the routine
            ok = late.sum() >= 10
            slope = np.polyfit(t[back] / 60, resid[b][back], 1)[0] if ok else None
            rates[b] = {
                "frames_back_at_reference": int(late.sum()),
                "drift_deg_per_min": None if slope is None else round(float(slope), 1),
                "residual_at_reference_late_deg": round(float(np.median(resid[b][late])), 1)
                if ok
                else None,
                "residual_mean_deg": round(float(resid[b][r & (t >= ref_a["start"])].mean()), 1),
            }
        k_end = np.argmin(np.abs(t - end))
        span_min = (end - ref_a["end"]) / 60
        out["full"][model] = {
            "translation_m_at_routine_end": round(float(dist[k_end]), 2),
            "translation_m_max": round(float(dist[r].max()), 2),
            "translation_m_per_min": round(float(dist[k_end] / span_min), 2),
            "vertical_range_m": round(float(np.ptp(tran[r & (t >= ref_a["start"]), 1])), 2),
            "orientation": rates,
        }
        runs[model] = (t, dist, horiz, resid)
    for combo in COMBOS:
        out["translation_by_combo"][combo] = {}
        for model in MODELS:
            t, tran, _ = load(res, model, combo, body)
            ref_w = (t >= ref_a["start"]) & (t <= ref_a["end"])
            dist, _ = translation_drift(t, tran, ref_w, end)
            out["translation_by_combo"][combo][model] = round(
                float(dist[np.argmin(np.abs(t - end))]), 2
            )

    fig = plt.figure(figsize=(19, 12.5))
    gs = GridSpec(3, 3, figure=fig, width_ratios=[1.25, 1.6, 1.1], hspace=0.45, wspace=0.42)
    fig.suptitle(
        f"{session.name}: relative drift, both models zeroed on the same reference "
        f"(standing still {ref_a['start']}-{ref_a['end']} s, devices: {LABEL['rw_rp_h']})",
        fontsize=13,
        y=0.97,
    )

    # Top view of the root path
    ax = fig.add_subplot(gs[0:2, 0])
    for model, color in MODELS.items():
        t, dist, horiz, _ = runs[model]
        w = (t >= ref_a["start"]) & (t <= end)
        ax.plot(horiz[w, 0], horiz[w, 1], color=color, lw=1.2, label=model)
        ax.scatter(*horiz[w][-1], color=color, s=30, marker="s", zorder=3)
    ax.scatter([0], [0], color="black", s=40, zorder=4, label="reference (start)")
    pts = np.concatenate(
        [runs[m][2][(runs[m][0] >= ref_a["start"]) & (runs[m][0] <= end)] for m in MODELS]
    )
    mid, half = (pts.max(0) + pts.min(0)) / 2, (pts.max(0) - pts.min(0)).max() / 2 * 1.1
    ax.set_xlim(mid[0] - half, mid[0] + half)
    ax.set_ylim(mid[1] - half, mid[1] + half)
    ax.set_aspect("equal")
    ax.set_xlabel("x: subject's left (m)")
    ax.set_ylabel("z: forward (m)")
    ax.set_title("Root path from above (routine done in place)", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="best")

    # Distance from start over time
    ax = fig.add_subplot(gs[0, 1])
    for model, color in MODELS.items():
        t, dist, _, _ = runs[model]
        w = (t >= ref_a["start"]) & (t <= end)
        s = out["full"][model]
        ax.plot(
            t[w],
            dist[w],
            color=color,
            lw=1.4,
            label=f"{model}: {s['translation_m_at_routine_end']} m at routine end ({s['translation_m_per_min']} m/min)",
        )
    ax.set_ylabel("horizontal root drift (m)")
    ax.set_title("Translation drift over time", fontsize=10)
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.3)
    shade(ax, annotation)

    # Offset-removed orientation residual over time, per bone
    row = gs[1:3, 1].subgridspec(3, 1, hspace=0.45)
    for i, (b, bname) in enumerate(BONES.items()):
        ax = fig.add_subplot(row[i, 0])
        for model, color in MODELS.items():
            t, _, _, resid = runs[model]
            w = (t >= ref_a["start"]) & (t <= end)
            back = at_reference(b, t)
            ax.plot(t[w], resid[b][w], color=color, lw=0.8, alpha=0.6)
            ax.plot(t[back], resid[b][back], "o", ms=3, color=color)
            o = out["full"][model]["orientation"][b]
            if o["drift_deg_per_min"] is not None:
                p = np.polyfit(t[back], resid[b][back], 1)
                ax.plot(
                    t[w],
                    np.polyval(p, t[w]),
                    "--",
                    color=color,
                    lw=1.3,
                    label=f"{model}: drift {o['drift_deg_per_min']:+.1f}°/min",
                )
            else:
                ax.plot(
                    [], [], "--", color=color, label=f"{model}: device never back at reference pose"
                )
        ax.set_ylabel("angle after offset\nremoval (deg)", fontsize=8)
        ax.set_title(bname, fontsize=9)
        ax.set_ylim(0, None)
        ax.legend(fontsize=7, loc="upper left")
        ax.grid(alpha=0.3)
        shade(ax, annotation)
        if i == 2:
            ax.set_xlabel(
                "s after Start (dots: device back at its reference pose; drift is read there)"
            )

    # Translation drift for every combination
    ax = fig.add_subplot(gs[0:2, 2])
    y = np.arange(len(COMBOS))
    for k, (model, color) in enumerate(MODELS.items()):
        vals = [out["translation_by_combo"][c][model] for c in COMBOS]
        ax.barh(y + (k - 0.5) * 0.38, vals, 0.38, color=color, label=model)
    ax.set_yticks(y)
    ax.set_yticklabels(
        [LABEL[c].replace("+", "+\n", 1) if len(LABEL[c]) > 12 else LABEL[c] for c in COMBOS],
        fontsize=8,
    )
    ax.invert_yaxis()
    ax.set_xlabel("horizontal root drift at routine end (m)")
    ax.set_title("Translation drift by device combination", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(axis="x", alpha=0.3)

    # Orientation drift summary
    ax = fig.add_subplot(gs[2, 2])
    x = np.arange(len(BONES))
    for k, (model, color) in enumerate(MODELS.items()):
        ax.bar(
            x + (k - 0.5) * 0.38,
            [out["full"][model]["orientation"][b]["residual_mean_deg"] for b in BONES],
            0.38,
            color=color,
            label=f"{model}: mean after offset removal",
        )
    ax.set_xticks(x)
    ax.set_xticklabels([v.replace(" (", "\n(") for v in BONES.values()], fontsize=8)
    ax.set_ylabel("deg")
    ax.set_title("Orientation residual, routine mean", fontsize=10)
    ax.legend(fontsize=7)
    ax.grid(axis="y", alpha=0.3)

    fig.text(
        0.07,
        0.015,
        "Same scale: both models are re-zeroed on the same standing-still window, so constant offsets (e.g. the Watch "
        "calibration bias) cancel. Translation: the routine is done in place, so horizontal root motion is drift. "
        "Orientation: residual = drift + motion-related error;\ndrift is read where a device returns to its reference pose "
        f"(still, within {NEAR_REF_DEG:.0f}° of calibration). Agreement with the sensors, not ground-truth error.",
        fontsize=8.5,
    )
    fig.savefig(res / "drift.png", dpi=100, bbox_inches="tight")
    (res / "drift.json").write_text(json.dumps(out, indent=2))
    print("Saved", res / "drift.png")
    print(
        json.dumps(
            {m: {k: v for k, v in d.items() if k != "orientation"} for m, d in out["full"].items()},
            indent=1,
        )
    )
    print(json.dumps({m: d["orientation"] for m, d in out["full"].items()}, indent=1))
    print(json.dumps(out["translation_by_combo"]))


if __name__ == "__main__":
    main()
