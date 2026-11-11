"""Align a camera video with an IMU session to about 0.1 s.

The video file's creation time gives the start to about 1 s (whole seconds, plus clock
differences between the Mac and the iPhone). The fine offset comes from cross-correlating
on-screen motion (frame differences, with an optional masked strip for bystanders) with the
Watch and phone motion; the two must agree.

Writes <session>/video/alignment.json with the rule
    video_t = imu_unix - video_start_unix_metadata + offset_s
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

SEARCH_S = 5.0
STEP_S = 0.02
GRID_S = 0.1


def video_start_unix(video: Path) -> float:
    """Recording start from the file's metadata (macOS Spotlight)."""
    raw = subprocess.run(
        ["mdls", "-raw", "-name", "kMDItemContentCreationDate", str(video)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %z").timestamp()


def frame_motion(video: Path, mask_left=0.0):
    """Mean absolute grey-level change per frame (small frames), left strip masked."""
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    prev, motion = None, []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (162, 108)).astype(float)
        g = g[:, int(162 * mask_left) :]
        motion.append(0.0 if prev is None else float(np.mean(np.abs(g - prev))))
        prev = g
    return np.arange(len(motion)) / fps, np.array(motion)


def imu_motion(packets, device):
    """(unix time, rotation rate + 3 x acceleration magnitude) of one device."""
    rows = sorted(
        (s[0] + p["boot_to_unix"], np.linalg.norm(s[8:11]) + 3 * np.linalg.norm(s[5:8]))
        for p in packets
        if p.get("type") == "imu" and p.get("device") == device
        for s in p["s"]
    )
    return np.array(rows)


def _z(x):
    return (x - x.mean()) / x.std()


def correlate(t_video, video, t_imu_video, imu, search_s=SEARCH_S, step=STEP_S):
    """Best shift (s) of the IMU series in video time, its r, and the best r ≥ 0.5 s away."""
    grid = np.arange(0, t_video[-1], GRID_S)
    v = np.interp(grid, t_video, np.convolve(video, np.ones(3) / 3, "same"))
    scores = []
    for lag in np.arange(-search_s, search_s + step / 2, step):
        i = np.interp(grid, t_imu_video + lag, imu, left=np.nan, right=np.nan)
        ok = ~np.isnan(i)
        if ok.sum() < 300:
            continue
        scores.append((float(np.corrcoef(_z(v[ok]), _z(i[ok]))[0, 1]), float(lag)))
    r, lag = max(scores)
    away = max((s for s, l in scores if abs(l - lag) >= 0.5), default=float("nan"))
    return round(lag, 2), round(r, 3), round(away, 3)


def align(session: Path, video: Path, mask_left=0.0, mirrored=False) -> dict:
    with open(session / "stream.jsonl") as f:
        packets = [json.loads(line) for line in f]
    start = video_start_unix(video)
    t_video, motion = frame_motion(video, mask_left)
    estimates = {}
    for device in ("watch", "phone"):
        m = imu_motion(packets, device)
        if len(m) > 100:
            lag, r, away = correlate(t_video, motion, m[:, 0] - start, m[:, 1])
            estimates[device] = {"lag_s": lag, "r": r, "next_best_r": away}
    offset = round(float(np.mean([e["lag_s"] for e in estimates.values()])), 2)
    spread = max(e["lag_s"] for e in estimates.values()) - min(
        e["lag_s"] for e in estimates.values()
    )
    result = {
        "video": video.name,
        "video_start_unix_metadata": start,
        "offset_s": offset,
        "rule": "video_t = imu_unix - video_start_unix_metadata + offset_s",
        "mirrored": mirrored,
        "mask_left": mask_left,
        "estimates": estimates,
        "agree": bool(spread <= 0.2),
    }
    (video.parent / "alignment.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
