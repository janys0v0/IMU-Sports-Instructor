"""Run the Roboflow pose workflow (YOLO pose) on every 30 Hz frame of a phone1 window.

Needs ROBOFLOW_API_KEY in the environment (never in a file in the repo). Writes
results/<player>/predictions.jsonl (not committed):
    .venv/bin/python -m experiments.E09_roboflow_pose.run janys --start 35 --seconds 20
"""

import argparse
import base64
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import cv2

from .common import OUT, WORKFLOW_URL, clip_info, window


def infer(jpg_b64: str, key: str, tries: int = 4) -> dict:
    """One frame through the workflow: person keypoints and racket boxes."""
    body = json.dumps({"inputs": {"image": {"type": "base64", "value": jpg_b64}}}).encode()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    err = ""
    for k in range(tries):
        try:
            t = time.time()
            req = urllib.request.Request(WORKFLOW_URL, data=body, headers=headers)
            r = json.load(urllib.request.urlopen(req, timeout=120))["outputs"][0]
            return {
                "pose": r["body_pose"]["predictions"],
                "racket": r["racket_predictions"]["predictions"],
                "latency_s": round(time.time() - t, 3),
            }
        except Exception as e:  # network or server error: back off and retry
            err = str(e)
            time.sleep(2 * (k + 1))
    return {"error": err}


def main():
    from experiments.E07_pose_methods.common import load

    p = argparse.ArgumentParser()
    p.add_argument("player", choices=["janys", "tom"])
    p.add_argument("--start", type=float, default=35.0, help="seconds into the block")
    p.add_argument("--seconds", type=float, default=20.0)
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args()
    key = os.environ["ROBOFLOW_API_KEY"]

    d = load(a.player)
    clip, clip_unix, _ = clip_info(a.player)
    cap = cv2.VideoCapture(str(clip))
    cfps = cap.get(cv2.CAP_PROP_FPS)
    rows = list(window(a.start, a.seconds))
    frame_of = {i: int(round((d["t"][i] - clip_unix) * cfps)) for i in rows}
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_of[rows[0]])
    pos, jpgs = frame_of[rows[0]] - 1, {}
    for i in rows:
        while pos < frame_of[i]:
            ok, f = cap.read()
            pos += 1
        jpgs[i] = base64.b64encode(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 90])[1])
    print(f"{len(rows)} frames from {clip.name}; calling the workflow")

    out = OUT / a.player
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda i: infer(jpgs[i].decode(), key), rows))
    with open(out / "predictions.jsonl", "w") as fh:
        for i, r in zip(rows, res):
            fh.write(json.dumps({"i": i, "clip_frame": frame_of[i], **r}) + "\n")
    print(f"errors: {sum('error' in r for r in res)}; wrote {out / 'predictions.jsonl'}")


if __name__ == "__main__":
    main()
