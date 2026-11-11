"""Live OpenSim view of the arm from MotionStreamer: OpenSense IK on every frame.

Run from the repo root (the IK runs in the OpenSim env, started automatically):
    .venv/bin/python -m pipeline.live.opensim_live [--port 5005] [--screen leg|outward] [--no-viz]

1. Start this script and enter the printed IP in the iPhone app. Tap Start.
2. Tap Calibrate, pocket the phone (right front pocket) and stand straight, arms hanging, palms
   facing your thighs, looking ahead.
3. After the 3 s hold the OpenSim model follows you. Calibrate again at any time.

Same UDP port, acks and saved packets as pipeline/live/receiver.py (data/recordings/<session>/
mac_stream.jsonl); each IK frame is also saved to opensim_live.jsonl there.
The Watch drives the right forearm (`radius_r`), the pocket phone the right thigh (`femur_r`), as
in the offline IK (experiments/E07_pose_methods/opensense_ik.py, "opensense_watch_phone"). Each is
the device's rotation since the hold, in the hold's body frame. AirPods are not used.
Accuracy: this is the offline Watch + phone OpenSense IK, the weakest arm method on 11/05
(swings: elbow ~29 deg, shoulder elevation ~40 deg off vs OpenCap); heading drifts after each
calibration, so the model slowly turns.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from pipeline.paths import RECORDINGS, ROOT

OPENSIM_PYTHON = Path(
    os.environ.get("OPENSIM_PYTHON", Path.home() / "micromamba-envs" / "opensim" / "bin" / "python")
)
SERVER = ROOT / "pipeline" / "live" / "opensim_ik_server.py"
FPS = 30.0
IMU_OF = {"watch": "radius_r_imu", "phone": "femur_r_imu"}  # device -> model IMU frame


def body_frame(R_MI):
    """World -> OpenSim body frame (x forward, y up, z right) from the phone calibration's
    world -> SMPL body rotation (rows: left, up, forward)."""
    left, up, forward = R_MI
    return np.stack([forward, up, -left])


def segment_quat(M, R_now, R_hold):
    """A device's rotation since its hold, in the hold's body frame, as [w, x, y, z]: the
    identity at the hold (the offline IK's virtual-IMU definition)."""
    q = Rotation.from_matrix(M @ R_now @ R_hold.T @ M.T).as_quat()  # x, y, z, w
    return [float(q[3]), float(q[0]), float(q[1]), float(q[2])]


class IKServer:
    """The OpenSim-env process; one JSON line out, one back."""

    def __init__(self, viz=True):
        if not OPENSIM_PYTHON.exists():
            sys.exit(f"OpenSim env not found at {OPENSIM_PYTHON} (set OPENSIM_PYTHON)")
        cmd = [str(OPENSIM_PYTHON), str(SERVER)] + ([] if viz else ["--no-viz"])
        self.p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=ROOT
        )
        self.reply()  # {"ready": true}

    def ask(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        return self.reply()

    def reply(self):
        while True:
            line = self.p.stdout.readline()
            if not line:
                sys.exit("OpenSim IK server stopped")
            if line.startswith("{"):  # skip any log line OpenSim prints
                return json.loads(line)

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


def calibrate_holds(receiver, phone_loc, window, screen):
    """(M, {device: (loc, R_hold, clock shift)}) or None. Uses the phone's calibration for the
    body frame; the Watch must share the phone's reference frame (as in live_viewer)."""
    from pipeline.preprocessing.calibration import calibrate

    phone = receiver.stream(phone_loc)
    try:
        cal = calibrate(phone, window, pocket_screen=screen)
    except ValueError as e:
        print(f"\nCalibration failed: {e}")
        return None
    holds = {}
    for loc, device in receiver.devices().items():
        if device not in IMU_OF:
            continue
        stream = receiver.stream(loc)
        if stream is None:
            continue
        if device == "watch" and stream.ref_frame != phone.ref_frame:
            print(f"\nWatch skipped: reference frame {stream.ref_frame} != phone's")
            continue
        # The window is on the phone clock; the Watch counts from its own boot.
        shift = phone.boot_to_unix - stream.boot_to_unix if device == "watch" else 0.0
        sel = stream.window(window[0] + shift, window[1] + shift)
        if sel.sum() < 10:
            print(f"\n{device} skipped: {sel.sum()} samples in the hold")
            continue
        if loc.startswith("left"):
            print(f"\n{device} reports {loc}: the model drives the RIGHT arm and leg")
        holds[device] = (loc, Rotation.from_quat(stream.quat[sel]).mean().as_matrix())
    checks = cal.checks
    print(
        f"\nCalibrated ({', '.join(sorted(holds))}); phone still check "
        f"{'ok' if checks['passed'] else 'FAILED (moved during the hold?)'}"
    )
    return body_frame(cal.R_MI), holds


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--screen", choices=["leg", "outward"], default=None,
                        help="phone screen direction in the pocket (default: the app's setting)")  # fmt: skip
    parser.add_argument("--no-viz", action="store_true", help="no OpenSim 3D window")
    parser.add_argument("--out", type=Path, default=RECORDINGS)
    args = parser.parse_args()

    import pipeline.live.receiver as receiver_module
    from pipeline.live.live_viewer import Receiver
    from pipeline.live.receiver import local_ip

    receiver_module.AUTO_RENDER = False  # no MobilePoser render after the session
    print("Starting OpenSim (model, IMU frames, viewer)...")
    ik = IKServer(viz=not args.no_viz)
    receiver = Receiver(args.port, args.out.resolve())
    receiver.start()
    print(f"Listening on {local_ip()}:{args.port}  (enter this IP in the iPhone app)")
    print("Tap Start, then Calibrate. Ctrl+C to quit.\n")

    cal, pending, log, log_session = None, None, None, None
    n, fails, solve_ms, last_status, out = 0, 0, [], time.monotonic(), {}
    next_frame = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if now < next_frame:
                time.sleep(next_frame - now)
                continue
            next_frame = max(next_frame + 1 / FPS, now)

            for event in receiver.pop_events():
                if event.get("name") in ("start", "stop"):
                    cal, pending = None, None
                elif event.get("name") == "calibrate":
                    pending = event
                    print(
                        f"\nCalibrating: stand straight, arms hanging, for {event.get('hold_s', 3):.0f} s"
                    )

            latest = receiver.latest()
            phone_loc = next((lc for lc, dv in receiver.devices().items() if dv == "phone"), None)
            if pending and phone_loc in latest:
                t0 = pending["t_phone"]
                window = (t0 + 0.3, t0 + pending.get("hold_s", 3.0))
                if latest[phone_loc][0] >= window[1]:
                    pending = None
                    screen = args.screen or receiver.pocket_screen or "leg"
                    cal = calibrate_holds(receiver, phone_loc, window, screen)
                    if cal:
                        ik.ask({"cmd": "calibrate"})

            if cal and cal[1] and all(loc in latest for loc, _ in cal[1].values()):
                M, holds = cal
                q = {}
                for device, (loc, R_hold) in holds.items():
                    R_now = Rotation.from_quat(latest[loc][1:5]).as_matrix()
                    q[IMU_OF[device]] = segment_quat(M, R_now, R_hold)
                out = ik.ask({"t": latest[phone_loc][0], "q": q})
                n += 1
                fails += not out.get("ok")
                solve_ms.append(out.get("ms", np.nan))
                session = receiver.session
                if session is not None and session is not log_session:
                    log = open(session.dir / "opensim_live.jsonl", "a")  # noqa: SIM115
                    log_session = session
                if log is not None:
                    log.write(
                        json.dumps(
                            {"mac_unix": time.time(), "t_phone": latest[phone_loc][0], **out}
                        )
                        + "\n"
                    )

            if now - last_status >= 0.5:
                if cal and out.get("ok"):
                    status = (
                        f"LIVE {n / (now - last_status):4.1f} fps | IK {np.nanmedian(solve_ms):4.1f} ms | "
                        f"elbow {out['elbow']:5.1f} | shoulder elev {out['elevation']:5.1f} "
                        f"plane {out['plane']:6.1f} | forearm twist {out['pro_sup']:5.1f} deg"
                    )
                else:
                    status = "waiting for Start + Calibrate" if not cal else "waiting for samples"
                ages = receiver.ages()
                status += " | " + " ".join(
                    f"{lc} {a * 1000:.0f}ms" for lc, a in sorted(ages.items())
                )
                if fails:
                    status += f" | {fails} IK fails"
                print("\r" + status + "\033[K", end="", flush=True)
                n, fails, solve_ms, last_status = 0, 0, [], now
    except KeyboardInterrupt:
        pass
    finally:
        if receiver.session:
            receiver.session.finish()
        ik.close()
        print("\nStopped.")


if __name__ == "__main__":
    main()
