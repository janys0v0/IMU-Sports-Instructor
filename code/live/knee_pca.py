"""PCA of the knee path during the knee raises: the 3D movement reduced to its 2 main directions.

Run with the project environment, from code/:
    .venv/bin/python live/knee_pca.py recordings/<session> [--screen leg] [--from 23 --to 29]

The knee position is taken relative to the hip of the pocket side, in the body frame
(x = left, y = up, z = forward), two ways:
- measured: hip + thigh length x thigh direction from the phone (assumes a rigid thigh;
  the phone measures the thigh only, not the shank),
- model: MobilePoser's knee joint minus its hip joint.
Without --from/--to the knee-raise section is found from the measured thigh pitch peaks.

Writes recordings/<session>/phase2/knee_pca.png, knee_pca_3d.png and knee_pca.json.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from plot_trajectories import reconstruct  # noqa: E402
from replay import THIGH_JOINTS, pitch_deg  # noqa: E402

from calibration import thigh_pitch_deg  # noqa: E402
from resample import MODEL_FPS  # noqa: E402

AXES = ("left", "up", "forward")


def find_raise_section(t, pitch, after, min_pitch=60.0, max_gap_s=3.0, pad_s=0.8):
    """Longest run of thigh-pitch peaks (> min_pitch) spaced < max_gap_s apart, after calibration."""
    peaks, _ = find_peaks(
        np.where(after, pitch, -np.inf), height=min_pitch, distance=int(0.5 * MODEL_FPS)
    )
    if len(peaks) == 0:
        sys.exit(f"No thigh peaks above {min_pitch} deg; pass --from/--to.")
    groups, current = [], [peaks[0]]
    for p in peaks[1:]:
        if t[p] - t[current[-1]] < max_gap_s:
            current.append(p)
        else:
            groups.append(current)
            current = [p]
    groups.append(current)
    best = max(groups, key=len)
    return t[best[0]] - pad_s, t[best[-1]] + pad_s


def pca(points):
    """Principal axes of an (N, 3) path. Returns mean, axes (3, 3) rows, variance ratio, scores (N, 3)."""
    mean = points.mean(axis=0)
    _, s, vt = np.linalg.svd(points - mean, full_matrices=False)
    # Sign convention: each axis points mostly along +forward / +up / +left, for readable plots.
    for i in range(3):
        k = np.argmax(np.abs(vt[i]))
        if vt[i, k] < 0:
            vt[i] *= -1
    ratio = s**2 / np.sum(s**2)
    return mean, vt, ratio, (points - mean) @ vt.T


def describe(axis):
    """e.g. '0.71 forward + 0.70 up' (components above 0.2)."""
    parts = [
        f"{v:+.2f} {name}"
        for v, name in sorted(zip(axis, AXES), key=lambda p: -abs(p[0]))
        if abs(v) > 0.2
    ]
    return " ".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", type=Path)
    parser.add_argument("--screen", choices=["leg", "outward"], default=None)
    parser.add_argument(
        "--from", dest="t_from", type=float, default=None, help="section start, s after Start"
    )
    parser.add_argument(
        "--to", dest="t_to", type=float, default=None, help="section end, s after Start"
    )
    args = parser.parse_args()

    session = args.session.resolve()
    r = reconstruct(session, args.screen)
    t, side = r.t, r.side
    hip_j, knee_j = THIGH_JOINTS[side]
    pitch = thigh_pitch_deg(r.ori_p)
    after = t >= r.window[1] - r.t_start
    if args.t_from is None or args.t_to is None:
        t_from, t_to = find_raise_section(t, pitch, after)
    else:
        t_from, t_to = args.t_from, args.t_to
    sel = (t >= t_from) & (t <= t_to)
    ts = t[sel]

    model = (r.joints[:, knee_j] - r.joints[:, hip_j])[sel]  # metres, body frame
    thigh_len = float(np.median(np.linalg.norm(r.joints[:, knee_j] - r.joints[:, hip_j], axis=1)))
    measured = (r.ori_p @ np.array([0.0, -1.0, 0.0]))[sel] * thigh_len  # rigid-thigh knee position

    results = {
        "session": r.rec.session,
        "side": side,
        "section_s": [round(t_from, 2), round(t_to, 2)],
        "thigh_length_m": round(thigh_len, 3),
    }
    fits = {}
    for name, path in (("measured", measured), ("model", model)):
        mean, axes, ratio, scores = pca(path)
        fits[name] = (mean, axes, ratio, scores)
        results[name] = {
            "variance_ratio_pc1_pc2_pc3": np.round(ratio, 4).tolist(),
            "pc_axes_body_frame_left_up_forward": np.round(axes, 3).tolist(),
            "pc_axes_described": [describe(a) for a in axes],
            "range_m_pc1_pc2_pc3": np.round(scores.max(0) - scores.min(0), 3).tolist(),
        }
    # Angle between the measured and model movement planes (normals = PC3).
    n_meas, n_model = fits["measured"][1][2], fits["model"][1][2]
    results["plane_angle_measured_vs_model_deg"] = round(
        float(np.degrees(np.arccos(abs(n_meas @ n_model)))), 1
    )

    # Per-repetition metrics from the measured thigh pitch.
    peaks, _ = find_peaks(np.where(sel, pitch, -np.inf), height=40, distance=int(0.5 * MODEL_FPS))
    model_pitch = pitch_deg(r.joints[:, knee_j] - r.joints[:, hip_j])
    pitch_rate = np.gradient(pitch, 1 / MODEL_FPS)
    reps = []
    for i, p in enumerate(peaks):
        lo = peaks[i - 1] if i else np.flatnonzero(sel)[0]
        hi = peaks[i + 1] if i + 1 < len(peaks) else np.flatnonzero(sel)[-1]
        start = lo + np.argmin(pitch[lo : p + 1])
        end = p + np.argmin(pitch[p : hi + 1])
        reps.append(
            {
                "peak_t_s": round(float(t[p]), 2),
                "peak_hip_flexion_deg": round(float(pitch[p]), 1),
                "model_peak_hip_flexion_deg": round(float(model_pitch[start : end + 1].max()), 1),
                "rise_s": round(float(t[p] - t[start]), 2),
                "lower_s": round(float(t[end] - t[p]), 2),
                "peak_up_speed_deg_s": round(float(pitch_rate[start : p + 1].max()), 0),
                "peak_down_speed_deg_s": round(float(-pitch_rate[p : end + 1].min()), 0),
            }
        )
    results["repetitions"] = reps

    out = session / "phase2"
    out.mkdir(exist_ok=True)
    (out / "knee_pca.json").write_text(json.dumps(results, indent=2))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(2, 2, figsize=(13, 10))
    for ax, name in ((axs[0, 0], "measured"), (axs[0, 1], "model")):
        _, axes, ratio, scores = fits[name]
        ax.plot(scores[:, 0], scores[:, 1], color="lightgray", lw=0.8, zorder=1)
        sc = ax.scatter(scores[:, 0], scores[:, 1], c=ts, cmap="viridis", s=12, zorder=2)
        for rep in reps:
            k = np.argmin(np.abs(ts - rep["peak_t_s"]))
            ax.annotate(
                f"{rep['peak_t_s']:.1f}s",
                scores[k, :2],
                fontsize=7,
                xytext=(4, 4),
                textcoords="offset points",
            )
        ax.set_xlabel(f"PC1 (m): {describe(axes[0])}  [{ratio[0]:.0%}]")
        ax.set_ylabel(f"PC2 (m): {describe(axes[1])}  [{ratio[1]:.0%}]")
        ax.set_title(f"{side} knee path, {name}: PC3 out-of-plane = {ratio[2]:.1%}")
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(alpha=0.3)
        fig.colorbar(sc, ax=ax, label="seconds after Start")

    ax = axs[1, 0]
    for i, color in enumerate(("tab:blue", "tab:orange", "tab:green")):
        ax.plot(ts, fits["measured"][3][:, i], color=color, label=f"PC{i + 1} measured")
        ax.plot(
            ts, fits["model"][3][:, i], color=color, ls="--", alpha=0.8, label=f"PC{i + 1} model"
        )
    ax.set_xlabel("seconds after Start")
    ax.set_ylabel("PC score (m)")
    ax.set_title("Knee position along each principal direction over time")
    ax.legend(fontsize=8, ncol=3)
    ax.grid(alpha=0.3)

    ax = axs[1, 1]
    x = np.arange(len(reps))
    ax.bar(
        x - 0.2,
        [rp["peak_hip_flexion_deg"] for rp in reps],
        0.4,
        label="measured (phone)",
        color="black",
    )
    ax.bar(
        x + 0.2,
        [rp["model_peak_hip_flexion_deg"] for rp in reps],
        0.4,
        label="model",
        color="tab:blue",
    )
    ax.set_xticks(
        x, [f"rep {i + 1}\n{rp['peak_t_s']:.1f} s" for i, rp in enumerate(reps)], fontsize=8
    )
    for i, rp in enumerate(reps):
        ax.text(
            i - 0.2,
            rp["peak_hip_flexion_deg"] + 2,
            f"{rp['rise_s']:.2f}↑\n{rp['lower_s']:.2f}↓",
            ha="center",
            va="bottom",
            fontsize=7,
        )
    ax.set_ylim(0, max(rp["peak_hip_flexion_deg"] for rp in reps) * 1.25)
    ax.set_ylabel("peak hip flexion (deg)")
    ax.set_title("Per repetition: peak thigh lift; seconds up ↑ / down ↓ (measured)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")
    fig.suptitle(
        f"{r.rec.session}: {side} knee raises {t_from:.1f}-{t_to:.1f} s, PCA of the 3D knee path "
        f"(relative to the {side} hip)"
    )
    fig.tight_layout()
    fig.savefig(out / "knee_pca.png", dpi=110)

    # 3D view with the principal axes.
    fig = plt.figure(figsize=(8, 7))
    ax = fig.add_subplot(projection="3d")
    for name, path, color in (("measured", measured, "black"), ("model", model, "tab:blue")):
        # Plot as (forward, left, up) so up is vertical.
        ax.plot(path[:, 2], path[:, 0], path[:, 1], color=color, lw=1, label=name)
        mean, axes, ratio, _ = fits[name]
        for i, length in enumerate((0.25, 0.15)):
            a = axes[i] * length
            ax.quiver(
                mean[2],
                mean[0],
                mean[1],
                a[2],
                a[0],
                a[1],
                color=color,
                lw=2,
                alpha=0.9 if i == 0 else 0.5,
            )
    ax.scatter([0], [0], [0], color="red", s=30, label=f"{side} hip")
    ax.set_xlabel("forward (m)")
    ax.set_ylabel("left (m)")
    ax.set_zlabel("up (m)")
    ax.set_title(f"{side} knee path relative to hip, with PC1 (long) and PC2 (short) arrows")
    ax.legend(fontsize=8)
    ax.view_init(elev=15, azim=-60)
    fig.tight_layout()
    fig.savefig(out / "knee_pca_3d.png", dpi=110)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
