"""Head and thigh trajectories over time for one recording (pocket phone + AirPods).

Run in the `mobileposer` conda env, from project/code:
    ~/miniconda3/envs/mobileposer/bin/python live/plot_trajectories.py recordings/<session> [--screen leg]

Writes recordings/<session>/phase2/trajectories.png (angles and heights over time) and
trajectories_side.png (side view of the head and knee paths).

Measured = calibrated sensor orientation in the body frame (x left, y up, z forward).
Model = MobilePoser lp_h output (phone + AirPods), offline, with root translation.
"""

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from replay import THIGH_JOINTS, model_input, pitch_deg, run_model  # noqa: E402

from calibration import (  # noqa: E402
    AIRPODS_FORWARD,
    calibrate,
    event_window,
    find_still_window,
    thigh_pitch_deg,
    to_body,
)
from motion_io import SLOTS, load_recording  # noqa: E402
from resample import Resampled, resample  # noqa: E402

HEAD_JOINT = 15
KNEES = {"left": 4, "right": 5}


def head_angles(ori):
    """Pitch (+ = looking down), yaw (+ = turned left), roll (+ = tilted left), degrees."""
    f = ori @ np.array([0.0, 0.0, 1.0])
    u = ori @ np.array([0.0, 1.0, 0.0])
    pitch = np.degrees(np.arctan2(-f[:, 1], np.hypot(f[:, 0], f[:, 2])))
    yaw = np.degrees(np.arctan2(f[:, 0], f[:, 2]))
    roll = np.degrees(np.arctan2(u[:, 0], u[:, 1]))
    return pitch, yaw, roll


def reconstruct(session, screen=None):
    """Calibrate phone + AirPods, resample to one 30 Hz grid, run MobilePoser lp_h offline."""
    rec = load_recording(session)
    loc = next(l for l, s in rec.streams.items() if s.device == "phone")
    phone, head = rec.streams[loc], rec.streams.get("head")
    if head is None:
        sys.exit("No AirPods stream in this recording.")
    screen = screen or rec.setting("pocket_screen", "leg")
    t_start = rec.last_event("start")["t_phone"]

    window = event_window(rec) or find_still_window(phone)
    cal_phone = calibrate(phone, window, pocket_screen=screen)
    cal_head = calibrate(head, window, forward_device=AIRPODS_FORWARD)

    t0, t1 = max(phone.t[0], head.t[0]), min(phone.t[-1], head.t[-1])
    res_p, res_h = resample(phone, t_start=t0, t_end=t1), resample(head, t_start=t0, t_end=t1)
    n = min(len(res_p.t), len(res_h.t))
    res_p, res_h = (
        Resampled(*(getattr(r, f)[:n] for f in Resampled.__dataclass_fields__))
        for r in (res_p, res_h)
    )
    acc_p, ori_p = to_body(cal_phone, res_p)
    acc_h, ori_h = to_body(cal_head, res_h)
    imu = model_input(acc_p, ori_p, SLOTS[loc], extra=[(acc_h, ori_h, SLOTS["head"])])
    pose, joints, tran, body = run_model(imu)
    return SimpleNamespace(
        rec=rec,
        loc=loc,
        side=loc.split("_")[0],
        screen=screen,
        t_start=t_start,
        window=window,
        t=res_p.t - t_start,
        res_p=res_p,
        res_h=res_h,
        acc_p=acc_p,
        ori_p=ori_p,
        acc_h=acc_h,
        ori_h=ori_h,
        pose=pose,
        joints=joints,
        tran=tran,
        world=joints + tran[:, None],
        body=body,
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", type=Path)
    parser.add_argument(
        "--screen",
        choices=["leg", "outward"],
        default=None,
        help="phone screen direction in the pocket (default: the app's setting)",
    )
    args = parser.parse_args()

    session = args.session.resolve()
    r = reconstruct(session, args.screen)
    rec, side, t_start, window = r.rec, r.side, r.t_start, r.window
    res_p, res_h, acc_p, ori_p, acc_h, ori_h = r.res_p, r.res_h, r.acc_p, r.ori_p, r.acc_h, r.ori_h
    joints, world = r.joints, r.world

    t = res_p.t - t_start
    after_cal = t >= window[1] - t_start
    thigh_meas = thigh_pitch_deg(ori_p)
    thigh_model = {s: pitch_deg(joints[:, k] - joints[:, h]) for s, (h, k) in THIGH_JOINTS.items()}
    h_pitch, h_yaw, h_roll = head_angles(ori_h)
    standing = (t >= window[0] - t_start) & (t <= window[1] - t_start)
    floor = (
        world[standing][:, [10, 11], 1].min(axis=1).mean()
    )  # feet height while standing for calibration
    stop = rec.last_event("stop")
    worn = after_cal & (t <= (stop["t_phone"] - t_start - 3 if stop else t[-1]))  # as in replay.py

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True)
    ax = axes[0]
    ax.plot(t, thigh_meas, color="black", lw=1.6, label=f"{side} thigh, measured (phone)")
    for s, color in (("left", "tab:blue"), ("right", "tab:orange")):
        ax.plot(t, thigh_model[s], color=color, lw=1, alpha=0.85, label=f"{s} thigh, model")
    ax.set_ylabel("thigh pitch (deg)\n+ = knee forward")

    ax = axes[1]
    ax.plot(t, h_pitch, label="pitch (+ = looking down)")
    ax.plot(t, h_yaw, label="yaw (+ = turned left)")
    ax.plot(t, h_roll, label="roll (+ = tilted left)")
    ax.plot(
        t[~res_h.valid],
        np.zeros((~res_h.valid).sum()),
        "|",
        color="red",
        ms=8,
        label="AirPods gap > 0.25 s",
    )
    ax.set_ylabel("head angles (deg)\nmeasured (AirPods)")

    ax = axes[2]
    ax.plot(t, world[:, HEAD_JOINT, 1] - floor, color="tab:green", label="head")
    for s, color in (("left", "tab:blue"), ("right", "tab:orange")):
        ax.plot(t, world[:, KNEES[s], 1] - floor, color=color, label=f"{s} knee")
    ax.set_ylabel("height above floor (m)\nmodel")

    ax = axes[3]
    ax.plot(t, np.linalg.norm(acc_p, axis=1), color="gray", lw=0.8, label="phone (thigh)")
    ax.plot(
        t,
        np.linalg.norm(acc_h, axis=1),
        color="tab:green",
        lw=0.8,
        alpha=0.8,
        label="AirPods (head)",
    )
    ax.set_ylabel("|acceleration| (m/s²)\nmeasured")
    ax.set_xlabel("seconds after Start")

    cal_span = (window[0] - t_start, window[1] - t_start)
    for ax in axes:
        ax.axvspan(t[0], cal_span[0], color="gray", alpha=0.08)
        ax.axvspan(*cal_span, color="green", alpha=0.15)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper left", fontsize=8, ncol=4)
    axes[0].text(
        np.mean(cal_span), axes[0].get_ylim()[1], "calibrate", ha="center", va="bottom", fontsize=8
    )
    fig.suptitle(
        f"{rec.session}: head and thigh over time (phone in {side} pocket + AirPods, model lp_h)"
    )
    fig.tight_layout()
    out = session / "phase2"
    out.mkdir(exist_ok=True)
    fig.savefig(out / "trajectories.png", dpi=110)

    # Side view: forward (z) vs height (y), root-relative so drift does not smear the paths.
    rel = joints - joints[:, :1]
    fig, ax = plt.subplots(figsize=(7, 8))
    for name, j, marker in (
        ("head", HEAD_JOINT, "o"),
        ("left knee", KNEES["left"], "^"),
        ("right knee", KNEES["right"], "s"),
    ):
        sc = ax.scatter(
            rel[worn, j, 2],
            rel[worn, j, 1],
            c=t[worn],
            cmap="viridis",
            s=10,
            marker=marker,
            label=name,
            vmin=t[worn].min(),
            vmax=t[worn].max(),
        )
    ax.scatter([0], [0], marker="x", color="black", label="pelvis (fixed)")
    fig.colorbar(sc, ax=ax, label="seconds after Start")
    ax.set_xlabel("forward (m), relative to pelvis")
    ax.set_ylabel("up (m), relative to pelvis")
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    legend = ax.legend(loc="lower left", fontsize=8)
    for handle in (
        legend.legend_handles if hasattr(legend, "legend_handles") else legend.legendHandles
    ):
        handle.set_color("gray")
    ax.set_title(f"{rec.session}: side view of head and knees (model)")
    fig.tight_layout()
    fig.savefig(out / "trajectories_side.png", dpi=110)
    print(f"Saved {out / 'trajectories.png'} and {out / 'trajectories_side.png'}")


if __name__ == "__main__":
    main()
