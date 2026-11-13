"""E09 shared setup: the clip window, the Roboflow workflow and the COCO <-> OpenCap joint map."""

import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "results"
FPS = 30  # E07's dataset grid
WORKFLOW_URL = (
    "https://serverless.roboflow.com/janyss-workspace/workflows/"
    "tennis-swing-motion-baseline-1794547375163"
)
# OpenCap marker -> COCO keypoint (both name the person's own left and right)
JOINTS = {
    "RShoulder": "right_shoulder",
    "LShoulder": "left_shoulder",
    "RElbow": "right_elbow",
    "LElbow": "left_elbow",
    "RWrist": "right_wrist",
    "LWrist": "left_wrist",
    "RHip": "right_hip",
    "LHip": "left_hip",
    "RKnee": "right_knee",
    "LKnee": "left_knee",
    "RAnkle": "right_ankle",
    "LAnkle": "left_ankle",
}
MIN_CONF = 0.3  # keypoints below this count as missing
MAX_MATCH_PX = 150.0  # a detection further than this from OpenCap's hip is someone else


def clip_info(player: str) -> tuple:
    """(phone1 clip path, its first frame on our clock, fitted 3x4 projection) from E06's fit."""
    from experiments.E06_side_by_side import camera
    from experiments.E07_pose_methods.data import PLAYERS

    fit = json.loads(camera.CAMERA_JSON.read_text())
    c = fit["clips"][PLAYERS[player][0]]
    return camera.DATA / c["clip"], c["start_unix"], np.asarray(fit["P"])


def window(start_s: float, seconds: float) -> range:
    """Dataset rows (30 Hz) for `seconds` from `start_s` into the block."""
    return range(int(round(start_s * FPS)), int(round((start_s + seconds) * FPS)))


def read_predictions(path: Path) -> dict:
    """{dataset row: {"clip_frame", "pose", "racket", ...}} from run.py's jsonl."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {r["i"]: r for r in rows}
