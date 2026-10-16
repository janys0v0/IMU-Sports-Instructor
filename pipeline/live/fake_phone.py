"""Sends synthetic MotionStreamer packets to test pipeline/live/receiver.py without devices.

Usage:
    python -m pipeline.live.fake_phone [--seconds 20] [--drop 0.02] [--port 5005]

Simulates a 60 Hz phone stream, a 60 Hz Watch stream with randomly dropped
batches, start/stop events, a Watch disconnect, and clock-sync pings.
"""

import argparse
import json
import random
import socket
import time

FIELDS = 14


def sample(t):
    return [t, 0.0, 0.0, 0.0, 1.0] + [0.0] * 3 + [0.0, 0.0, -1.0] + [0.0] * 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument(
        "--drop", type=float, default=0.02, help="fraction of Watch batches dropped"
    )
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    session = time.strftime("%Y%m%d-%H%M%S") + "-FAKE"
    boot = time.time() - time.monotonic()
    rate, batch = 60.0, 10
    acks = 0

    def send(packet):
        packet.update({"v": 1, "session": session})
        sock.sendto(json.dumps(packet).encode(), (args.host, args.port))

    def event(name, detail=None):
        e = {"type": "event", "name": name, "t_phone": time.monotonic(), "unix": time.time()}
        if detail:
            e["detail"] = detail
        send(e)

    event("start")
    start = time.monotonic()
    index = {"phone": 0, "watch": 0}
    seq = {"phone": 0, "watch": 0}
    next_batch = start + batch / rate
    next_sync = start + 5
    disconnected = False
    while time.monotonic() - start < args.seconds:
        now = time.monotonic()
        if now >= next_batch:
            for device, loc in (("phone", "left_pocket"), ("watch", "left_wrist")):
                t0 = now - batch / rate
                samples = [sample(t0 + i / rate) for i in range(batch)]
                packet = {
                    "type": "imu",
                    "device": device,
                    "loc": loc,
                    "seq": seq[device],
                    "first_index": index[device],
                    "rate_hz": rate,
                    "boot_to_unix": boot,
                    "ref_frame": "xMagneticNorthZVertical",
                    "send_phone": now,
                    "s": samples,
                }
                index[device] += batch
                seq[device] += 1
                if device == "watch" and random.random() < args.drop:
                    continue
                send(packet)
            next_batch += batch / rate
        if not disconnected and now - start > args.seconds / 2:
            event("watch_unreachable")
            event("watch_reachable")
            disconnected = True
        if now >= next_sync:
            send(
                {
                    "type": "sync",
                    "t_phone_send": now,
                    "t_watch": now + 123.4,
                    "t_phone_recv": now + 0.03,
                }
            )
            next_sync += 5
        try:
            while True:
                sock.recvfrom(1024)
                acks += 1
        except BlockingIOError:
            pass
        time.sleep(0.002)
    event("stop")
    print(
        f"Sent session {session}: {index['phone']} phone + {index['watch']} watch samples, {acks} acks received"
    )


if __name__ == "__main__":
    main()
