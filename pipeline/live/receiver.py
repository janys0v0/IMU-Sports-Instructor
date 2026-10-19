"""Phase 1 receiver: logs MotionStreamer packets and checks stream coverage.

Usage:
    python -m pipeline.live.receiver [--port 5005] [--out data/recordings] [--expect phone]

Prints this Mac's IP address (enter it in the iPhone app), saves every packet with
its Mac arrival time to <out>/<session>/mac_stream.jsonl, shows live per-stream
rates, and writes <out>/<session>/summary.json when the phone sends "stop".

Phase 1 exit criterion checked in the summary:
    session >= 120 s, coverage >= 95% for every stream, disconnects listed.
Coverage is relative to the rate each device actually delivers, measured from the
median interval between its sample timestamps.
Standard library only.
"""

import argparse
import json
import socket
import statistics
import subprocess
import time
from pathlib import Path

from pipeline.paths import RECORDINGS, ROOT, VENV_PYTHON

MIN_DURATION_S = 120
MIN_COVERAGE = 0.95

AUTO_RENDER = (
    True  # render <session>/reconstruction.mp4 when a session ends (--no-render turns it off)
)


_render = None  # the render process; one at a time, each uses several cores


def session_of(packet, current):
    """The packet's session. Packets without one (sensor packets from older app builds) belong to
    the current session; switching on them would end the real session ~20 times a second. Before
    any session is known there is nothing to file them under: None, and callers skip them."""
    return packet.get("session") or current


def start_render(session_dir):
    """Start pipeline.pose.render_session in the background; it writes reconstruction.mp4 and render.log."""
    global _render
    python = VENV_PYTHON
    if not python.exists():
        print(f"  not rendering: {python} not found")
        return
    if _render is not None and _render.poll() is None:
        print(
            f"  not rendering now (another render is running); later: {python} -m pipeline.pose.render_session {session_dir}"
        )
        return
    log = open(session_dir / "render.log", "w")  # noqa: SIM115 - owned by the render process
    # Own process group, so Ctrl+C on the receiver does not stop a render in progress.
    _render = subprocess.Popen(
        [str(python), "-W", "ignore", "-m", "pipeline.pose.render_session", str(session_dir)],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(
        f"  rendering {session_dir / 'reconstruction.mp4'} in the background (progress: render.log)\n"
    )


def local_ip():
    """Primary LAN address (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class Stream:
    """Counters for one device stream within a session."""

    def __init__(self, rate_hz):
        self.rate_hz = rate_hz
        self.seen = set()  # sample indices received; retried/duplicate packets are counted once
        self.lo = self.hi = None
        self.next_index = None
        self.last_t = None
        self.max_gap_s = 0.0
        self.window_start = time.monotonic()
        self.window_samples = 0
        self.measured_hz = 0.0
        self.last_recv = None
        self.transit_ms = []  # phone send -> Mac arrival, phone clock mapped via boot_to_unix
        self.intervals = []  # first sample intervals (device clock)

    @property
    def nominal_hz(self):
        """Rate the device actually delivers (iOS may give less than requested)."""
        if len(self.intervals) < 10:
            return self.rate_hz
        median = statistics.median(self.intervals)
        return 1 / median if median > 0 else self.rate_hz

    @property
    def samples(self):
        return len(self.seen)

    @property
    def missing(self):
        """Indices absent between the first and last received sample."""
        return self.hi - self.lo + 1 - len(self.seen) if self.seen else 0

    def add(self, packet, recv_unix):
        first, samples = packet["first_index"], packet["s"]
        for i, sample in enumerate(samples):
            index = first + i
            if index in self.seen:
                continue
            self.seen.add(index)
            self.lo = index if self.lo is None else min(self.lo, index)
            self.hi = index if self.hi is None else max(self.hi, index)
            self.window_samples += 1
            if (
                self.next_index is None or index >= self.next_index
            ):  # in order: track gaps and intervals
                if self.last_t is not None:
                    dt = sample[0] - self.last_t
                    self.max_gap_s = max(self.max_gap_s, dt)
                    if len(self.intervals) < 200:
                        self.intervals.append(dt)
                self.last_t = sample[0]
                self.next_index = index + 1
        now = time.monotonic()
        self.last_recv = now
        if now - self.window_start >= 2:
            self.measured_hz = self.window_samples / (now - self.window_start)
            self.window_start, self.window_samples = now, 0


class Session:
    def __init__(self, session_id, out_dir, expect=("phone", "watch")):
        self.expect = expect
        self.id = session_id
        self.dir = out_dir / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = open(self.dir / "mac_stream.jsonl", "a")  # noqa: SIM115 - open for the whole session
        self.streams = {}
        self.events = []
        self.syncs = []
        self.start_phone = None
        self.stop_phone = None
        self.start_mac = time.monotonic()
        self.stopped_at = None
        self.packets = 0

    def handle(self, packet, recv_unix):
        self.packets += 1
        kind = packet.get("type")
        if kind == "imu":
            key = f'{packet["device"]}:{packet["loc"]}'
            stream = self.streams.setdefault(key, Stream(packet.get("rate_hz", 60)))
            stream.add(packet, recv_unix)
            if packet["device"] == "phone" and "send_phone" in packet:
                sent_unix = packet["send_phone"] + packet["boot_to_unix"]
                stream.transit_ms.append((recv_unix - sent_unix) * 1000)
        elif kind == "event":
            self.events.append(
                {k: packet[k] for k in ("name", "t_phone", "unix", "detail") if k in packet}
            )
            if packet["name"] == "start":
                self.start_phone = packet["t_phone"]
            elif packet["name"] == "stop":
                self.stop_phone = packet["t_phone"]
                self.stopped_at = time.monotonic()
            print(f'  event: {packet["name"]} {packet.get("detail", "")}')
        elif kind == "sync":
            self.syncs.append(packet)

    def duration(self):
        if self.start_phone is not None and self.stop_phone is not None:
            return self.stop_phone - self.start_phone
        return time.monotonic() - self.start_mac

    def status_line(self):
        parts = [f"{self.id} {self.duration():6.0f}s"]
        for key, s in sorted(self.streams.items()):
            cov = s.samples / (s.nominal_hz * self.duration()) if self.duration() > 1 else 0
            parts.append(
                f"{key} {s.measured_hz:5.1f}Hz (device {s.nominal_hz:4.1f}) cov {cov:6.1%} miss {s.missing}"
            )
        return " | ".join(parts)

    def summary(self):
        duration = self.duration()
        streams = {}
        passed = duration >= MIN_DURATION_S
        for key, s in sorted(self.streams.items()):
            expected = s.nominal_hz * duration
            coverage = s.samples / expected if expected else 0
            passed &= coverage >= MIN_COVERAGE
            streams[key] = {
                "requested_rate_hz": s.rate_hz,
                "delivered_rate_hz": round(s.nominal_hz, 2),
                "samples": s.samples,
                "expected": round(expected),
                "coverage": round(coverage, 4),
                "missing_samples": s.missing,
                "longest_gap_s": round(s.max_gap_s, 3),
                "phone_to_mac_ms_median": round(statistics.median(s.transit_ms), 1)
                if s.transit_ms
                else None,
            }
        for device in self.expect:
            if not any(k.startswith(device) for k in streams):
                passed = False
                streams[f"{device}:missing"] = "no packets received"
        rtts = [(p["t_phone_recv"] - p["t_phone_send"]) * 1000 for p in self.syncs]
        disconnects = [
            e
            for e in self.events
            if e["name"] in ("watch_unreachable", "watch_reachable", "watch_launch_failed")
        ]
        return {
            "session": self.id,
            "duration_s": round(duration, 1),
            "packets_received": self.packets,
            "streams": streams,
            "watch_sync_pings": len(self.syncs),
            "watch_ping_rtt_ms_median": round(statistics.median(rtts), 1) if rtts else None,
            "disconnect_events": disconnects,
            "events": self.events,
            "exit_criterion": {
                "devices": list(self.expect),
                "min_duration_s": MIN_DURATION_S,
                "min_coverage": MIN_COVERAGE,
                "passed": bool(passed),
            },
        }

    def finish(self):
        summary = self.summary()
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=2))
        self.file.close()
        print("\n=== Session summary:", self.id)
        print(f'duration {summary["duration_s"]} s, packets {summary["packets_received"]}')
        for key, s in summary["streams"].items():
            print(f"  {key}: {s}")
        print(f'  disconnect events: {len(summary["disconnect_events"])}')
        print(
            f'  Phase 1 exit criterion: {"PASS" if summary["exit_criterion"]["passed"] else "FAIL"}'
        )
        print(f'  saved {self.dir / "summary.json"}\n')
        if AUTO_RENDER:
            start_render(self.dir)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument(
        "--expect",
        default="phone,watch",
        help="devices required to pass, e.g. 'phone' for a phone-only session",
    )
    parser.add_argument("--out", type=Path, default=RECORDINGS)
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="don't render reconstruction.mp4 after each session",
    )
    args = parser.parse_args()
    global AUTO_RENDER
    AUTO_RENDER = not args.no_render

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.5)
    print(f"Listening on {local_ip()}:{args.port}  (enter this IP in the iPhone app)")
    print(f"Saving to {args.out}\n")

    sessions = {}
    current = None  # newest session ID, for packets that carry none
    received_by_addr = {}
    last_ack = {}
    last_print = time.monotonic()
    try:
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                data = None
            now = time.monotonic()
            if data:
                recv_unix = time.time()
                try:
                    packet = json.loads(data)
                except json.JSONDecodeError:
                    print(f"  bad packet from {addr}")
                    continue
                session_id = session_of(packet, current)
                if session_id is None:
                    continue
                current = session_id
                if session_id not in sessions:
                    print(f"New session: {session_id} from {addr[0]}")
                    sessions[session_id] = Session(
                        session_id, args.out, tuple(args.expect.split(","))
                    )
                session = sessions[session_id]
                session.handle(packet, recv_unix)
                packet["recv_mac_unix"] = recv_unix
                session.file.write(json.dumps(packet) + "\n")
                received_by_addr[addr] = received_by_addr.get(addr, 0) + 1
                if now - last_ack.get(addr, 0) >= 1:
                    sock.sendto(
                        json.dumps({"type": "ack", "received": received_by_addr[addr]}).encode(),
                        addr,
                    )
                    last_ack[addr] = now
            # Finalize sessions 2 s after "stop" so late Watch packets are counted.
            for session_id, session in list(sessions.items()):
                if session.stopped_at and now - session.stopped_at > 2:
                    session.finish()
                    del sessions[session_id]
            if now - last_print >= 2 and sessions:
                for session in sessions.values():
                    print(session.status_line())
                last_print = now
    except KeyboardInterrupt:
        for session in sessions.values():
            session.finish()
        print("Stopped.")


if __name__ == "__main__":
    main()
