"""Phase 2 replay: recording -> 30 Hz -> body frame -> MobilePoser, with checks.

Run in the `mobileposer` conda env, from project/code:
    python live/replay.py recordings/<session> [--screen leg|outward] [--window auto|event]
                          [--render --from 60 --to 90] [--head]

Writes recordings/<session>/phase2/: calibration.json, body_input.npz,
model_output.npz, replay.png (and replay.mp4 with --render).

Checks
- Calibration: still window, gravity maps to body -y, heading usable, valid rotations.
- Per-slot test: the pocket phone's signed thigh pitch should track the model's thigh
  on the same side (correlation) more than the other side. Needs knee lifts on
  each side (see the Phase 2 protocol); free-form recordings are not decisive.
- Heading sign: while sitting (thigh > 60 deg from vertical) the phone thigh should
  point forward (pitch ~ +90). About -90 means the "screen faces" setting is reversed.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
MOBILEPOSER_DIR = HERE.parent / "MobilePoser" / "mobileposer"

from calibration import (  # noqa: E402
    AIRPODS_FORWARD,
    calibrate,
    event_window,
    find_still_window,
    mediolateral_check,
    thigh_pitch_deg,
    to_body,
)
from motion_io import SLOTS, load_recording  # noqa: E402
from resample import MODEL_FPS, Resampled, resample  # noqa: E402

COMBO_FOR_SLOT = {0: "lw", 1: "rw", 2: "lp", 3: "rp"}
THIGH_JOINTS = {"left": (1, 4), "right": (2, 5)}  # SMPL (hip, knee)


def model_input(acc, ori, slot, extra=()):
    """[N, 60]: 5 x 3 accelerations / acc_scale, then 5 x 3x3 orientations; unused slots zero.
    `extra`: more (acc, ori, slot) inputs, e.g. the AirPods head."""
    n = len(acc)
    acc5 = np.zeros((n, 5, 3), dtype=np.float32)
    ori5 = np.zeros((n, 5, 3, 3), dtype=np.float32)
    for a, o, k in [(acc, ori, slot), *extra]:
        acc5[:, k] = a / 30.0  # amass.acc_scale
        ori5[:, k] = o
    return np.concatenate([acc5.reshape(n, 15), ori5.reshape(n, 45)], axis=1)


def pitch_deg(vectors):
    """Signed forward swing of a hip->knee vector in the body frame (+ = knee forward)."""
    return np.degrees(np.arctan2(vectors[..., 2], -vectors[..., 1]))


def inclination_deg(vectors):
    """Angle between a bone vector and straight down."""
    v = vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.degrees(np.arccos(np.clip(-v[..., 1], -1, 1)))


def run_model(imu, body=None):
    os.chdir(MOBILEPOSER_DIR)  # MobilePoser resolves weights/SMPL relative to the working directory
    import mobileposer.articulate as art
    import torch
    from mobileposer.config import model_config, paths
    from mobileposer.utils.model_utils import load_model

    model = load_model(paths.weights_file).eval()
    x = torch.from_numpy(imu).float().to(model_config.device)
    model.reset()
    with torch.no_grad():
        pose, _, tran, _ = model.forward_offline(x.unsqueeze(0), [x.shape[0]])
    pose = pose.view(-1, 24, 3, 3).cpu()
    body = body or art.model.ParametricModel(paths.smpl_file)
    joints = body.forward_kinematics(pose)[1]
    return pose.numpy(), joints.numpy(), tran.view(-1, 3).cpu().numpy(), body


def render(body, poses, trans, out_path):
    """One subject per (pose, tran); several render side by side, left to right."""
    import torch

    body.view_motion(
        [torch.from_numpy(p) for p in poses],
        [torch.from_numpy(t) for t in trans],
        fps=int(MODEL_FPS),
    )
    shutil.move(str(MOBILEPOSER_DIR / "a.mp4"), out_path)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", type=Path)
    parser.add_argument(
        "--loc", default=None, help="stream to use, e.g. left_pocket (default: the phone's)"
    )
    parser.add_argument(
        "--slot",
        type=int,
        default=None,
        help="override the MobilePoser input slot (0 lw, 1 rw, 2 lp, 3 rp, 4 head)",
    )
    parser.add_argument(
        "--screen",
        choices=["leg", "outward"],
        default=None,
        help="phone screen direction in the pocket (default: from the recording, else leg)",
    )
    parser.add_argument(
        "--window",
        choices=["auto", "event"],
        default=None,
        help="calibration window (default: event if the app's countdown was used)",
    )
    parser.add_argument("--render", action="store_true")
    parser.add_argument(
        "--single",
        action="store_true",
        help="with --head: render only the phone + AirPods mesh (replay_lp_h.mp4)",
    )
    parser.add_argument(
        "--no-tran", action="store_true", help="render with the root fixed in place (pose only)"
    )
    parser.add_argument(
        "--head",
        action="store_true",
        help="also run with the AirPods head stream (slot 4); renders phone-only | phone+head",
    )
    parser.add_argument(
        "--from", dest="t_from", type=float, default=None, help="render start, s after start"
    )
    parser.add_argument(
        "--to", dest="t_to", type=float, default=None, help="render end, s after start"
    )
    args = parser.parse_args()

    session = args.session.resolve()
    rec = load_recording(session)
    loc = args.loc or next(l for l, s in rec.streams.items() if s.device == "phone")
    stream = rec.streams[loc]
    slot = SLOTS[loc] if args.slot is None else args.slot
    side = loc.split("_")[0]
    screen = args.screen or rec.setting("pocket_screen", "leg")
    out = session / "phase2"
    out.mkdir(exist_ok=True)

    # Calibration window: the app's countdown event (if it has the hold field) or auto-detected.
    window, source = None, None
    has_countdown = rec.last_event("calibrate") is not None and "hold_s" in rec.last_event(
        "calibrate"
    )
    if args.window == "event" or (args.window is None and has_countdown):
        window, source = event_window(rec), "event"
    if window is None:
        window, source = find_still_window(stream), "auto"
    if window is None:
        sys.exit("No still, upright window found for calibration.")
    cal = calibrate(stream, window, pocket_screen=screen)
    t_start = rec.last_event("start")["t_phone"] if rec.last_event("start") else stream.t[0]

    head = rec.streams.get("head") if args.head else None
    if args.head and head is None:
        sys.exit("--head: no AirPods stream in this recording.")
    if head is not None:
        # Same clock as the phone; share one 30 Hz grid over the overlap.
        t0, t1 = max(stream.t[0], head.t[0]), min(stream.t[-1], head.t[-1])
        res, res_head = resample(stream, t_start=t0, t_end=t1), resample(head, t_start=t0, t_end=t1)
        n = min(len(res.t), len(res_head.t))
        res, res_head = (
            Resampled(*(getattr(r, f)[:n] for f in Resampled.__dataclass_fields__))
            for r in (res, res_head)
        )
        cal_head = calibrate(head, window, forward_device=AIRPODS_FORWARD)
        acc_head, ori_head = to_body(cal_head, res_head)
    else:
        res = resample(stream)
    acc, ori = to_body(cal, res)
    imu = model_input(acc, ori, slot)
    pose, joints, tran, body = run_model(imu)
    if head is not None:
        imu_head = model_input(acc, ori, slot, extra=[(acc_head, ori_head, SLOTS["head"])])
        pose_h, joints_h, tran_h, _ = run_model(imu_head, body)

    # Per-slot test and heading-sign check.
    phone_axis = ori @ np.array([0.0, -1.0, 0.0])
    phone_incl = inclination_deg(phone_axis)
    model_pitch = {s: pitch_deg(joints[:, k] - joints[:, h]) for s, (h, k) in THIGH_JOINTS.items()}
    # Score only while the phone is worn: from the end of calibration to 3 s before stop.
    t_rel = res.t - t_start
    stop = rec.last_event("stop")
    t_end = (stop["t_phone"] - t_start - 3) if stop else t_rel[-1]
    worn = (t_rel >= window[1] - t_start) & (t_rel <= t_end)
    ok = res.valid & worn
    pitch = thigh_pitch_deg(ori)
    corr = {s: round(float(np.corrcoef(pitch[ok], v[ok])[0, 1]), 3) for s, v in model_pitch.items()}
    other = "right" if side == "left" else "left"
    sitting = (phone_incl > 60) & ok
    sitting_pitch = (
        round(float(np.median(pitch[sitting])), 1) if sitting.sum() > MODEL_FPS else None
    )
    results = {
        "session": rec.session,
        "stream": loc,
        "slot": slot,
        "combo": COMBO_FOR_SLOT.get(slot),
        "pocket_screen": screen,
        "delivered_rate_hz": round(stream.rate_hz, 2),
        "frames_30hz": len(res.t),
        "invalid_frames": int((~res.valid).sum()),
        "scored_s_after_start": [round(float(window[1] - t_start), 1), round(float(t_end), 1)],
        "calibration": {
            "source": source,
            "window_s_after_start": [round(window[0] - t_start, 2), round(window[1] - t_start, 2)],
            **cal.checks,
        },
        "per_slot_test": {
            f"corr_phone_vs_model_{side}_thigh": corr[side],
            f"corr_phone_vs_model_{other}_thigh": corr[other],
            "passed": bool(corr[side] > 0.8 and corr[side] > corr[other]),
        },
        "heading": {
            "sitting_pitch_deg": sitting_pitch,  # ~ +90 when correct; ~ -90 when screen setting reversed
            "sitting_frames": int(sitting.sum()),
            "mediolateral_axis_vs_left_deg": mediolateral_check(cal, stream),
            "passed": None if sitting_pitch is None else bool(sitting_pitch > 45),
        },
    }
    if head is not None:
        results["head"] = {
            "combo": COMBO_FOR_SLOT.get(slot) + "_h",
            "delivered_rate_hz": round(head.rate_hz, 2),
            "invalid_frames": int((~res_head.valid).sum()),
            "calibration": cal_head.checks,
        }
        np.savez_compressed(
            out / "model_output_head.npz",
            t=res.t - t_start,
            pose=pose_h,
            joints=joints_h,
            tran=tran_h,
            valid=res_head.valid,
        )
    (out / "calibration.json").write_text(json.dumps(results, indent=2))
    np.savez_compressed(
        out / "body_input.npz",
        t=res.t - t_start,
        acc=acc,
        ori=ori,
        imu=imu,
        valid=res.valid,
        R_MI=cal.R_MI,
        device2bone=cal.device2bone,
    )
    np.savez_compressed(
        out / "model_output.npz", t=res.t - t_start, pose=pose, joints=joints, tran=tran
    )

    # Plot: inclinations and acceleration with app events.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = res.t - t_start
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    axes[0].plot(t, pitch, label=f"phone thigh ({side}, measured)", color="black")
    axes[0].plot(t, model_pitch[side], label=f"model {side} thigh", alpha=0.8)
    axes[0].plot(t, model_pitch[other], label=f"model {other} thigh", alpha=0.8)
    axes[0].set_ylabel("thigh pitch, + = knee forward (deg)")
    axes[0].legend(loc="upper right")
    axes[1].plot(t, np.linalg.norm(acc, axis=1), color="gray")
    axes[1].set_ylabel("|acc| body (m/s²)")
    axes[1].set_xlabel("s after start")
    for ax in axes:
        ax.axvspan(window[0] - t_start, window[1] - t_start, color="green", alpha=0.2)
        ax.axvspan(t[0], window[1] - t_start, color="gray", alpha=0.08)
        ax.axvspan(t_end, t[-1], color="gray", alpha=0.08)
        for e in rec.events:
            if e["name"] in ("calibrate", "marker", "stop"):
                ax.axvline(e["t_phone"] - t_start, color="red", lw=0.8, ls="--")
    fig.suptitle(
        f"{rec.session}  per-slot corr {side} {corr[side]:.2f} / {other} {corr[other]:.2f}"
    )
    fig.tight_layout()
    fig.savefig(out / "replay.png", dpi=110)

    if args.render:
        sel = np.ones(len(t), bool)
        if args.t_from is not None:
            sel &= t >= args.t_from
        if args.t_to is not None:
            sel &= t <= args.t_to
        if args.no_tran:
            tran, tran_h = (
                np.zeros_like(tran),
                (np.zeros_like(tran_h) if head is not None else None),
            )
        if head is not None and args.single:
            render(body, [pose_h[sel]], [tran_h[sel]], out / "replay_lp_h.mp4")
        elif head is not None:
            render(
                body, [pose[sel], pose_h[sel]], [tran[sel], tran_h[sel]], out / "replay_head.mp4"
            )
        else:
            render(body, [pose[sel]], [tran[sel]], out / "replay.mp4")

    print(json.dumps(results, indent=2))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
