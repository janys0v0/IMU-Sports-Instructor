"""Real-time MobilePoser mesh viewer for macOS.

Run in the `mobileposer` conda env, from project/code:
    ~/miniconda3/envs/mobileposer/bin/python live/live_viewer.py [--port 5005] [--screen leg|outward] [--tran]

Takes the place of receiver/phase1_receiver.py during a live session: same UDP port, same acks
to the iPhone app, and every packet is still saved to recordings/<session>/mac_stream.jsonl.

1. Start this script and enter the printed IP in the iPhone app. Tap Start.
2. Tap Calibrate in the app, pocket the phone and stand straight, looking ahead.
3. After the 3 s hold the mesh turns blue and follows you. Calibrate again at any time.

Mesh colour: grey = waiting for calibration, blue = live, orange = a stream stopped (> 0.5 s).
Each frame uses the newest sample from every calibrated device (sample-and-hold at 30 Hz).
A stream counts as stopped when no packet from it has arrived for STALE_S (Mac arrival time).
MobilePoser's online model adds ~167 ms of look-ahead latency (5 future frames).
"""

import argparse
import collections
import json
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

HERE = Path(__file__).resolve().parent
CODE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CODE / "receiver"))

import phase1_receiver  # noqa: E402
from phase1_receiver import Session, local_ip  # noqa: E402
from replay import MOBILEPOSER_DIR, model_input  # noqa: E402

from calibration import AIRPODS_FORWARD, Calibration, G, calibrate  # noqa: E402
from motion_io import SLOTS, DeviceStream  # noqa: E402

FPS = 30.0
BUFFER_S = 15.0
STALE_S = 0.5
COLORS = {"waiting": (0.7, 0.7, 0.7), "live": (0.45, 0.65, 0.95), "stale": (0.95, 0.6, 0.3)}


class Receiver(threading.Thread):
    """UDP thread: logs packets, acks the phone, keeps recent samples per device."""

    def __init__(self, port, out_dir):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", port))
        self.sock.settimeout(0.5)
        self.out_dir = out_dir
        self.lock = threading.Lock()
        self.samples = {}  # loc -> deque of 14-number samples
        self.meta = {}  # loc -> {"device", "ref_frame", "boot_to_unix"}
        self.arrival = {}  # loc -> time.monotonic() of the last packet
        self.events = collections.deque()
        self.session = None
        self.pocket_screen = None

    def run(self):
        received, last_ack = {}, {}
        while True:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                self._maybe_finish()
                continue
            recv_unix = time.time()
            try:
                packet = json.loads(data)
            except json.JSONDecodeError:
                continue
            session_id = packet.get("session") or "unknown"
            if self.session is None or self.session.id != session_id:
                if self.session is not None:
                    self.session.finish()
                print(f"\nNew session: {session_id} from {addr[0]}")
                self.session = Session(session_id, self.out_dir, ("phone",))
                with self.lock:
                    self.samples.clear()
                    self.meta.clear()
                    self.arrival.clear()
            self.session.handle(packet, recv_unix)
            packet["recv_mac_unix"] = recv_unix
            self.session.file.write(json.dumps(packet) + "\n")
            self._consume(packet)
            received[addr] = received.get(addr, 0) + 1
            now = time.monotonic()
            if now - last_ack.get(addr, 0) >= 1:
                self.sock.sendto(
                    json.dumps({"type": "ack", "received": received[addr]}).encode(), addr
                )
                last_ack[addr] = now
            self._maybe_finish()

    def _consume(self, packet):
        kind = packet.get("type")
        with self.lock:
            if kind == "imu":
                loc = packet["loc"]
                buf = self.samples.setdefault(loc, collections.deque())
                buf.extend(packet["s"])
                while buf and buf[-1][0] - buf[0][0] > BUFFER_S:
                    buf.popleft()
                self.meta[loc] = {k: packet.get(k) for k in ("device", "ref_frame", "boot_to_unix")}
                self.arrival[loc] = time.monotonic()
            elif kind == "event":
                if "pocket_screen" in packet:
                    self.pocket_screen = packet["pocket_screen"]
                self.events.append(packet)

    def _maybe_finish(self):
        if (
            self.session
            and self.session.stopped_at
            and time.monotonic() - self.session.stopped_at > 2
        ):
            self.session.finish()
            self.session = None

    def stream(self, loc):
        """DeviceStream copy of the buffered samples for one device (sorted, de-duplicated)."""
        with self.lock:
            rows = list(self.samples.get(loc, ()))
            meta = dict(self.meta.get(loc, {}))
        if len(rows) < 2:
            return None
        arr = np.asarray(rows, dtype=float)
        arr = arr[np.argsort(arr[:, 0], kind="stable")]
        arr = arr[np.concatenate([[True], np.diff(arr[:, 0]) > 1e-6])]
        return DeviceStream(
            device=meta.get("device", ""),
            loc=loc,
            t=arr[:, 0],
            quat=arr[:, 1:5],
            user_acc=arr[:, 5:8],
            gravity=arr[:, 8:11],
            rot_rate=arr[:, 11:14],
            boot_to_unix=meta.get("boot_to_unix") or 0.0,
            ref_frame=meta.get("ref_frame") or "",
        )

    def latest(self):
        """loc -> newest sample (by device time)."""
        with self.lock:
            return {loc: max(buf, key=lambda s: s[0]) for loc, buf in self.samples.items() if buf}

    def devices(self):
        """loc -> device name ("phone", "watch", "airpods")."""
        with self.lock:
            return {loc: m.get("device") for loc, m in self.meta.items()}

    def ages(self):
        """loc -> seconds since its last packet arrived."""
        now = time.monotonic()
        with self.lock:
            return {loc: now - t for loc, t in self.arrival.items()}

    def pop_events(self):
        with self.lock:
            events = list(self.events)
            self.events.clear()
        return events


def calibrate_shared(stream: DeviceStream, window, R_MI) -> Calibration:
    """A device in the phone's reference frame (e.g. the Watch): reuse the phone's heading."""
    sel = stream.window(*window)
    if sel.sum() < 10:
        raise ValueError(f"only {sel.sum()} samples in the calibration window")
    rots = Rotation.from_quat(stream.quat[sel])
    device2bone = (R_MI @ rots.mean().as_matrix()).T
    acc_offset = (R_MI @ rots.apply(-G * stream.user_acc[sel]).T).T.mean(axis=0)
    rot_rms = float(np.sqrt(np.mean(np.sum(stream.rot_rate[sel] ** 2, axis=1))))
    return Calibration(
        R_MI=R_MI,
        device2bone=device2bone,
        acc_offset=acc_offset,
        window=window,
        pocket_screen="",
        checks={"still_rot_rms_rad_s": round(rot_rms, 3), "passed": rot_rms < 0.2},
    )


def to_body_sample(cal: Calibration, sample):
    R_IS = Rotation.from_quat(sample[1:5]).as_matrix()
    ori = cal.R_MI @ R_IS @ cal.device2bone
    acc = cal.R_MI @ (R_IS @ (-G * np.asarray(sample[5:8]))) - cal.acc_offset
    return acc, ori


class Viewer:
    """Open3D window with one SMPL mesh and a floor grid."""

    def __init__(self, faces, verts, floor_y):
        import open3d as o3d

        self.o3d = o3d
        self.vis = o3d.visualization.Visualizer()
        self.vis.create_window("MobilePoser live", width=900, height=900)
        self.mesh = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(verts), o3d.utility.Vector3iVector(faces)
        )
        self.mesh.compute_vertex_normals()
        self.mesh.paint_uniform_color(COLORS["waiting"])
        self.vis.add_geometry(self.mesh)
        self.vis.add_geometry(self._grid(floor_y))
        opt = self.vis.get_render_option()
        opt.background_color = np.array([1.0, 1.0, 1.0])
        opt.mesh_show_back_face = True
        view = self.vis.get_view_control()
        view.set_front(
            [0.35, 0.25, 1.0]
        )  # camera in front of the body (+z), slightly right and above
        view.set_up([0.0, 1.0, 0.0])
        view.set_lookat([0.0, -0.3, 0.0])
        view.set_zoom(0.9)
        self.color = "waiting"

    def _grid(self, y, half=2.0, step=0.25):
        ticks = np.arange(-half, half + 1e-9, step)
        points, lines = [], []
        for v in ticks:
            points += [[v, y, -half], [v, y, half], [-half, y, v], [half, y, v]]
            n = len(points)
            lines += [[n - 4, n - 3], [n - 2, n - 1]]
        grid = self.o3d.geometry.LineSet(
            self.o3d.utility.Vector3dVector(points), self.o3d.utility.Vector2iVector(lines)
        )
        grid.paint_uniform_color((0.85, 0.85, 0.85))
        return grid

    def update(self, verts, color):
        self.mesh.vertices = self.o3d.utility.Vector3dVector(verts)
        self.mesh.compute_vertex_normals()
        if color != self.color:
            self.mesh.paint_uniform_color(COLORS[color])
            self.color = color
        self.vis.update_geometry(self.mesh)

    def tick(self):
        """Process window events; False once the window is closed."""
        alive = self.vis.poll_events()
        self.vis.update_renderer()
        return alive


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument(
        "--screen",
        choices=["leg", "outward"],
        default=None,
        help="phone screen direction in the pocket (default: the app's setting)",
    )
    parser.add_argument(
        "--tran", action="store_true", help="move the root (drifts ~30%% of distance walked)"
    )
    parser.add_argument("--no-head", action="store_true", help="ignore the AirPods stream")
    parser.add_argument("--out", type=Path, default=CODE / "recordings")
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="don't render reconstruction.mp4 after each session",
    )
    args = parser.parse_args()
    phase1_receiver.AUTO_RENDER = not args.no_render

    import os

    import torch

    torch.set_num_threads(4)  # leave cores for the renderer; must run before any torch work
    os.chdir(MOBILEPOSER_DIR)  # MobilePoser resolves weights/SMPL relative to the working directory
    from mobileposer.config import paths
    from mobileposer.utils.model_utils import load_model

    model = load_model(paths.weights_file).eval()
    body = model.bodymodel
    rest = torch.eye(3).repeat(1, 24, 1, 1)
    verts0 = body.forward_kinematics(rest, calc_mesh=True)[2][0].cpu().numpy()
    viewer = Viewer(body.face, verts0, model.floor_y)

    receiver = Receiver(args.port, args.out)
    receiver.start()
    print(f"Listening on {local_ip()}:{args.port}  (enter this IP in the iPhone app)")
    print("Tap Start, then Calibrate. Close the window or press Ctrl+C to quit.\n")

    inference = Inference(model, receiver, args)
    inference.rest_verts = verts0
    inference.start()
    shown = 0
    try:
        while viewer.tick():
            frame = inference.frame
            if frame is not None and frame[0] != shown:
                shown, verts, color = frame
                viewer.update(verts, color)
            time.sleep(0.004)
    except KeyboardInterrupt:
        pass
    if receiver.session:
        receiver.session.finish()
    print("\nStopped.")


class Inference(threading.Thread):
    """30 Hz loop: handles calibration events, runs MobilePoser, publishes mesh vertices.
    Runs apart from the window thread so rendering never delays the model."""

    def __init__(self, model, receiver, args):
        super().__init__(daemon=True)
        self.model, self.receiver, self.args = model, receiver, args
        self.frame = None  # (frame number, verts, colour), replaced atomically
        self.rest_verts = None

    def run(self):
        import torch

        model, receiver, args, body = self.model, self.receiver, self.args, self.model.bodymodel
        cals = {}  # loc -> Calibration
        pending = None  # calibrate event waiting for its hold to finish
        infer_ms = collections.deque(maxlen=60)
        n, frames, last_status = 0, 0, time.monotonic()
        next_frame = time.monotonic()
        while True:
            now = time.monotonic()
            if now < next_frame:
                time.sleep(next_frame - now)
                continue
            next_frame = max(next_frame + 1 / FPS, now)

            for event in receiver.pop_events():
                if event.get("name") in ("start", "stop"):
                    if cals:
                        self.frame = (n := n + 1, self.rest_verts, "waiting")
                    cals, pending = {}, None
                elif event.get("name") == "calibrate":
                    pending = event
                    print(
                        f"\nCalibrating: stand straight and look ahead for {event.get('hold_s', 3):.0f} s"
                    )

            latest = receiver.latest()
            phone_loc = next((loc for loc, d in receiver.devices().items() if d == "phone"), None)

            # Finish a calibration once the phone has samples past the end of the hold.
            if pending and phone_loc and phone_loc in latest:
                t0 = pending["t_phone"]
                window = (t0 + 0.3, t0 + pending.get("hold_s", 3.0))
                if latest[phone_loc][0] >= window[1]:
                    pending = None
                    cals = run_calibration(receiver, phone_loc, window, args)
                    model.reset()

            if cals and all(loc in latest for loc in cals):
                ages = receiver.ages()
                inputs = []
                for loc, cal in cals.items():
                    acc, ori = to_body_sample(cal, latest[loc])
                    inputs.append((acc[None], ori[None], SLOTS[loc]))
                (acc, ori, slot), rest_inputs = inputs[0], inputs[1:]
                x = torch.from_numpy(model_input(acc, ori, slot, rest_inputs)[0]).float()
                start = time.perf_counter()
                pose, _, tran, _ = model.forward_online(x)
                verts = (
                    body.forward_kinematics(
                        pose.view(1, 24, 3, 3),
                        tran=tran.view(1, 3) if args.tran else None,
                        calc_mesh=True,
                    )[2][0]
                    .cpu()
                    .numpy()
                )
                infer_ms.append((time.perf_counter() - start) * 1000)
                n += 1
                frames += 1
                self.frame = (
                    n,
                    verts,
                    "stale" if max(ages[loc] for loc in cals) > STALE_S else "live",
                )

            if now - last_status >= 1:
                status = [
                    f"{'LIVE' if cals else 'waiting'}",
                    f"{frames / (now - last_status):4.1f} fps",
                ]
                if infer_ms:
                    status.append(f"model {np.median(infer_ms):4.1f} ms")
                for loc, age in sorted(receiver.ages().items()):
                    status.append(
                        f"{loc} {age * 1000:3.0f} ms ago{'' if not cals or loc in cals else ' (unused)'}"
                    )
                print("\r" + " | ".join(status) + "\033[K", end="", flush=True)
                frames, last_status = 0, now


def run_calibration(receiver, phone_loc, window, args):
    """Calibrate every device that has samples in the hold window. Returns loc -> Calibration."""
    phone = receiver.stream(phone_loc)
    screen = args.screen or receiver.pocket_screen or "leg"
    cals = {}
    try:
        cals[phone_loc] = calibrate(phone, window, pocket_screen=screen)
    except ValueError as e:
        print(f"\nCalibration failed ({phone_loc}): {e}")
        return {}
    report = [
        f"{phone_loc} (screen {screen}) {'ok' if cals[phone_loc].checks['passed'] else 'CHECK FAILED'}"
        f" rot {cals[phone_loc].checks['still_rot_rms_rad_s']}"
    ]
    for loc in receiver.devices():
        if loc == phone_loc or loc not in SLOTS or (loc == "head" and args.no_head):
            continue
        stream = receiver.stream(loc)
        if stream is None:
            continue
        # The window is on the phone clock; the Watch counts from its own boot. Map through
        # each device's wall clock (boot_to_unix). AirPods samples already use the phone clock.
        shift = phone.boot_to_unix - stream.boot_to_unix if stream.device == "watch" else 0.0
        device_window = (window[0] + shift, window[1] + shift)
        try:
            if loc == "head":
                cal = calibrate(stream, device_window, forward_device=AIRPODS_FORWARD)
            elif stream.ref_frame == phone.ref_frame:
                cal = calibrate_shared(stream, device_window, cals[phone_loc].R_MI)
            else:
                report.append(f"{loc} skipped (reference frame {stream.ref_frame} != phone's)")
                continue
        except ValueError as e:
            report.append(f"{loc} skipped ({e})")
            continue
        cals[loc] = cal
        report.append(
            f"{loc} {'ok' if cal.checks['passed'] else 'CHECK FAILED'} rot {cal.checks['still_rot_rms_rad_s']}"
        )
    print("\nCalibrated: " + "; ".join(report))
    if not cals[phone_loc].checks["passed"]:
        print(
            "  Phone check failed (moved during the hold?). Tap Calibrate again if the pose looks wrong."
        )
    return cals


if __name__ == "__main__":
    main()
