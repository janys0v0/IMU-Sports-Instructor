"""Render a recording to <session>/reconstruction.mp4 with every device that was calibrated.

Run in the project venv, from project/code:
    .venv/bin/python -m pipeline.pose.render_session data/recordings/<session> [--no-tran | --full-tran] [--out NAME.mp4]

The root moves up and down only (squats lower the body); horizontal drift is removed so the
body stays inside the fixed camera. --full-tran keeps it, --no-tran pins the root entirely.

The receiver and live viewer start this automatically when a session ends (see
pipeline/live/receiver.py start_render). Each Calibrate in the session starts a new segment:
the devices are calibrated on that hold and used until the next Calibrate or Stop. A device is
used in a segment only if it has samples in the hold and covers most of the segment.
Segments run through MobilePoser offline and are joined, with the root continuing across joins.
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np

from pipeline.pose.replay import MOBILEPOSER_DIR, model_input
from pipeline.preprocessing.calibration import AIRPODS_FORWARD, calibrate, to_body
from pipeline.preprocessing.motion_io import SLOTS, load_recording
from pipeline.preprocessing.resample import MODEL_FPS, resample

MIN_SEGMENT_S = 2.0
MIN_DEVICE_COVERAGE = 0.9  # fraction of the segment a non-phone device must cover
STOP_MARGIN_S = 1.0  # drop the last second before Stop (hand reaching for the phone)


def calibrate_shared(stream, window, R_MI):
    # Same as live_viewer.calibrate_shared; imported lazily there to avoid pulling in the viewer.
    from live_viewer import calibrate_shared as shared

    return shared(stream, window, R_MI)


def segments(rec, phone):
    """(hold window, segment start, segment end) on the phone clock, one per Calibrate."""
    cals = [e for e in rec.events if e.get("name") == "calibrate" and "t_phone" in e]
    stop = rec.last_event("stop")
    end_all = (stop["t_phone"] if stop else phone.t[-1]) - STOP_MARGIN_S
    out = []
    for i, event in enumerate(cals):
        hold = (event["t_phone"] + 0.3, event["t_phone"] + event.get("hold_s", 3.0))
        end = cals[i + 1]["t_phone"] if i + 1 < len(cals) else end_all
        if end - hold[1] >= MIN_SEGMENT_S:
            out.append((hold, hold[1], min(end, end_all)))
    return out


def segment_input(rec, phone_loc, hold, t0, t1, screen):
    """Model input for one segment, plus the device names used."""
    phone = rec.streams[phone_loc]
    cal_p = calibrate(phone, hold, pocket_screen=screen)
    res_p = resample(phone, t_start=t0, t_end=t1)
    n = len(res_p.t)
    acc, ori = to_body(cal_p, res_p)
    used, extra = [phone_loc], []
    for loc, stream in rec.streams.items():
        if loc == phone_loc or loc not in SLOTS:
            continue
        # Watch samples count from the Watch's own boot; AirPods use the phone clock.
        shift = phone.boot_to_unix - stream.boot_to_unix if stream.device == "watch" else 0.0
        try:
            if loc == "head":
                cal = calibrate(
                    stream, (hold[0] + shift, hold[1] + shift), forward_device=AIRPODS_FORWARD
                )
            elif stream.ref_frame == phone.ref_frame:
                cal = calibrate_shared(stream, (hold[0] + shift, hold[1] + shift), cal_p.R_MI)
            else:
                continue
        except ValueError:
            continue  # no samples in the hold
        res = resample(stream, t_start=t0 + shift, t_end=t1 + shift)
        if len(res.t) < MIN_DEVICE_COVERAGE * n or res.valid.mean() < MIN_DEVICE_COVERAGE:
            continue  # stopped or dropped out during the segment
        n = min(n, len(res.t))
        a, o = to_body(cal, res)
        extra.append((a, o, SLOTS[loc]))
        used.append(loc)
    imu = model_input(acc[:n], ori[:n], SLOTS[phone_loc], [(a[:n], o[:n], s) for a, o, s in extra])
    return imu, used


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", type=Path)
    parser.add_argument(
        "--no-tran", action="store_true", help="keep the root fixed in place (pose only)"
    )
    parser.add_argument(
        "--full-tran",
        action="store_true",
        help="also move the root horizontally (drifts; the body can leave the fixed camera)",
    )
    parser.add_argument(
        "--out", default="reconstruction.mp4", help="file name inside the session folder"
    )
    args = parser.parse_args()

    session = args.session.resolve()
    rec = load_recording(session)
    phone_loc = next((loc for loc, s in rec.streams.items() if s.device == "phone"), None)
    if phone_loc is None or phone_loc not in SLOTS:
        sys.exit(f"{session.name}: no pocket phone stream, nothing to render.")
    screen = rec.setting("pocket_screen", "leg")
    segs = segments(rec, rec.streams[phone_loc])
    if not segs:
        sys.exit(
            f"{session.name}: no Calibrate followed by at least {MIN_SEGMENT_S:.0f} s of data, nothing to render."
        )

    os.chdir(MOBILEPOSER_DIR)  # MobilePoser resolves weights/SMPL relative to the working directory
    import torch
    import vctoolkit.viso3d as vo3d
    from mobileposer.config import paths
    from mobileposer.utils.model_utils import load_model

    model = load_model(paths.weights_file).eval()
    body = model.bodymodel
    poses, trans, offset = [], [], torch.zeros(3)
    for k, (hold, t0, t1) in enumerate(segs, 1):
        imu, used = segment_input(rec, phone_loc, hold, t0, t1, screen)
        model.reset()
        with torch.no_grad():
            pose, _, tran, _ = model.forward_offline(
                torch.from_numpy(imu).float().unsqueeze(0), [len(imu)]
            )
        tran = tran.view(-1, 3).cpu()
        tran = tran - tran[:1] + offset  # continue from where the previous segment ended
        offset = tran[-1].clone()
        poses.append(pose.view(-1, 24, 3, 3).cpu())
        trans.append(tran)
        print(f"segment {k}: {len(imu) / MODEL_FPS:.0f} s, devices: {', '.join(used)}")

    pose, tran = torch.cat(poses), torch.cat(trans)
    if args.no_tran:
        tran = torch.zeros_like(tran)
    elif not args.full_tran:
        tran[:, [0, 2]] = 0  # keep only up/down (squats), so the body stays in the fixed camera
    verts = np.concatenate(
        [
            body.forward_kinematics(pose[i : i + 500], tran=tran[i : i + 500], calc_mesh=True)[2]
            .numpy()
            .astype(np.float32)
            for i in range(0, len(pose), 500)
        ]
    )
    out = session / args.out
    print(f"rendering {len(verts)} frames ({len(verts) / MODEL_FPS:.0f} s) to {out}")
    vo3d.render_sequence_3d(verts, body.face, 720, 720, str(out), int(MODEL_FPS), visible=True)
    print("done")


if __name__ == "__main__":
    main()
