"""Replay a saved session to the live viewer over UDP, at real-time pace (for testing without devices).

    python -m pipeline.live.send_recording data/recordings/<session> [--port 5005] [--speed 1.0]

Packets are resent in the order and with the spacing they reached the Mac; the session id
gets a "-REPLAY" suffix so the viewer logs it to a new folder.
"""

import argparse
import json
import socket
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()

    path = args.session / "mac_stream.jsonl" if args.session.is_dir() else args.session
    with open(path) as f:
        packets = [json.loads(line) for line in f]
    packets.sort(key=lambda p: p["recv_mac_unix"])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t_first, start = packets[0]["recv_mac_unix"], time.monotonic()
    for packet in packets:
        due = start + (packet.pop("recv_mac_unix") - t_first) / args.speed
        time.sleep(max(0.0, due - time.monotonic()))
        packet["session"] = packet["session"] + "-REPLAY"
        sock.sendto(json.dumps(packet).encode(), (args.host, args.port))
    print(f"Sent {len(packets)} packets in {time.monotonic() - start:.1f} s")


if __name__ == "__main__":
    main()
