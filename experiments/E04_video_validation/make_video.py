"""Side-by-side video: the camera with Vision's skeleton next to the IMU (MobilePoser) mesh.

Run after run.py (it reads alignment.json and vision_pose.json next to the video):
    .venv/bin/python -m experiments.E04_video_validation.make_video [SESSION]

Panels: camera (cropped to the subject, Vision skeleton drawn), then one SMPL mesh per Watch
calibration (standing, arms-out). Each panel shows the right elbow and right knee angle it
implies. A mirrored video gets mirrored meshes, so the Watch arm is on the same side.
Writes results/<SESSION>/videos/side_by_side.mp4 (videos are not committed).
"""

import argparse
import json

import cv2
import numpy as np

from experiments.common import metrics, paths, render
from experiments.common import mobileposer_runner as mp
from experiments.common.session import load_session

from . import angles as A
from .run import DEFAULT_SESSION, WRIST_POSES, find_video

PANEL = 540
SKELETON = [
    ("top_head", "center_head"), ("center_head", "center_shoulder"),
    ("center_shoulder", "left_shoulder"), ("center_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("center_shoulder", "spine"), ("spine", "root"), ("root", "left_hip"), ("root", "right_hip"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
]  # fmt: skip
WATCH_SIDE = {"right_shoulder", "right_elbow", "right_wrist"}
GREY, RED, DARK = (230, 230, 230), (40, 40, 220), (40, 40, 40)


def vision_name(short):
    return f"human_{short}_3D"


def draw_skeleton(img, frame, width, x0, crop_w, mirrored):
    """Vision's 2D skeleton on the panel (crop from x0, crop_w wide, scaled to PANEL).
    The Watch arm is drawn red; in a mirrored video Vision calls it the left arm."""
    watch = {n.replace("right", "left") for n in WATCH_SIDE} if mirrored else WATCH_SIDE
    sx = PANEL / crop_w
    pts = {}
    for short in {s for edge in SKELETON for s in edge}:
        p = frame.get("image", {}).get(vision_name(short))
        if p is not None:
            pts[short] = (int((p[0] * width - x0) * sx), int(p[1] * PANEL))
    for a, b in SKELETON:
        if a in pts and b in pts:
            color = RED if a in watch or b in watch else (60, 200, 60)
            cv2.line(img, pts[a], pts[b], color, 3, cv2.LINE_AA)
    for p in pts.values():
        cv2.circle(img, p, 4, (255, 255, 255), -1, cv2.LINE_AA)


def label(img, lines, color=DARK, bg=GREY):
    for i, text in enumerate(lines):
        y = 26 + 24 * i
        (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(img, (6, y - h - 6), (14 + w, y + 6), bg, -1)
        cv2.putText(img, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)


def activity_at(annotation, t):
    for a in (annotation or {}).get("activities", []):
        if a["start"] <= t <= a["end"]:
            return a["name"].replace("_", " ")
    return ""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("session", nargs="?", default=DEFAULT_SESSION)
    args = parser.parse_args(argv)

    folder = paths.session_dir(args.session)
    name = folder.name
    annotation = metrics.load_annotation(name)
    mask_left = (annotation or {}).get("video", {}).get("mask_left", 0.0)
    video = find_video(folder / "video")
    alignment = json.loads((video.parent / "alignment.json").read_text())
    mirrored = (annotation or {}).get("video", {}).get("mirrored", alignment.get("mirrored", False))
    vision = json.loads((video.parent / "vision_pose.json").read_text())["frames"]
    if not any("image" in f for f in vision):
        raise SystemExit("vision_pose.json has no image points: rerun vision_pose.swift")
    v_times = np.array([f["t"] for f in vision])
    with open(folder / "stream.jsonl") as f:
        start = next(
            json.loads(line) for line in f if '"name": "start"' in line or '"name":"start"' in line
        )

    out_dir = paths.results_dir(__file__, name) / "videos"
    out_dir.mkdir(exist_ok=True)
    body = mp.body_model()
    runs = {}
    for wrist_pose in WRIST_POSES:
        session = load_session(folder, wrist_pose=wrist_pose)
        out = mp.run(session, session.locs)
        mesh = out_dir / f"mesh_{wrist_pose}.mp4"
        if not mesh.exists() or render.frame_count(mesh) != len(out.pose):
            render.render_mesh(body, out.pose, mesh, size=PANEL)
        runs[wrist_pose] = (out, A.angles(A.smpl_joints(out.joints)), cv2.VideoCapture(str(mesh)))
    out = runs[WRIST_POSES[0]][0]
    if any(len(r[0].t) != len(out.t) for r in runs.values()):
        raise RuntimeError("the IMU runs differ in length")

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    x0 = int(width * mask_left)  # crop: hides the bystander, keeps the subject
    crop_w = int(width) - x0
    t_video = A.to_video_time(out.t, start["unix"], alignment)
    va_t, va_j = A.vision_joints(vision, mirrored=mirrored)
    va = A.angles(va_j)

    path = out_dir / "side_by_side.mp4"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"avc1"), render.FPS, (PANEL * (1 + len(runs)), PANEL)
    )
    frame_index, frame = -1, None
    for k, tv in enumerate(t_video):
        want = int(round(tv * fps))
        while frame_index < want:
            ok, img = cap.read()
            if not ok:
                break
            frame_index, frame = frame_index + 1, img
        if frame is None or frame_index < want:
            break  # the video ended before the IMU did
        cam = cv2.resize(frame[:, x0:], (PANEL, PANEL), interpolation=cv2.INTER_AREA)
        near = int(np.argmin(np.abs(v_times - tv)))
        lines = [
            "Camera + Vision pose",
            f"t = {out.t[k]:.1f} s  {activity_at(annotation, out.t[k])}",
        ]
        if abs(v_times[near] - tv) <= 0.07:
            draw_skeleton(cam, vision[near], width, x0, crop_w, mirrored)
            j = int(np.argmin(np.abs(va_t - tv)))
            if abs(va_t[j] - tv) <= 0.07:
                lines.append(f"R elbow {va['r_elbow'][j]:.0f}  R knee {va['r_knee'][j]:.0f}")
        label(cam, lines)
        panels = [cam]
        for wrist_pose, (_out, ia, mesh_cap) in runs.items():
            ok, m = mesh_cap.read()
            if not ok:
                m = np.zeros((PANEL, PANEL, 3), np.uint8)
            m = cv2.resize(m, (PANEL, PANEL))
            if mirrored:
                m = cv2.flip(m, 1)
            label(
                m,
                [
                    f"IMU mesh, Watch cal. {wrist_pose.replace('_', '-')}",
                    f"R elbow {ia['r_elbow'][k]:.0f}  R knee {ia['r_knee'][k]:.0f}",
                ],
            )
            panels.append(m)
        writer.write(np.hstack(panels))
    writer.release()
    print(
        f"{path}: {render.frame_count(path)} frames ({render.frame_count(path) / render.FPS:.0f} s)"
    )


if __name__ == "__main__":
    main()
