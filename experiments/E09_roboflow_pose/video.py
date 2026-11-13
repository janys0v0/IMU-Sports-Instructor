"""Preview: OpenCap projected into phone1 (left) and Roboflow over OpenCap (right).

Reads run.py's predictions; writes results/<player>/videos/preview.mp4 (not committed):
    .venv/bin/python -m experiments.E09_roboflow_pose.video janys
"""

import argparse

import cv2
import numpy as np

from .common import FPS, JOINTS, OUT, clip_info, read_predictions
from .evaluate import frame_errors, keypoints, match_person, project_gt

BONES = [
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"), ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"), ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"),
    ("right_shoulder", "right_hip"), ("left_shoulder", "left_hip"), ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"), ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
]  # fmt: skip
CROP_W, CROP_H, SCALE = 360, 480, 2.0  # source px around the player, then enlarged


def label(img, text, org, size=0.7):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, size, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, size, (255, 255, 255), 2, cv2.LINE_AA)


def draw(img, pts: dict, origin: tuple, col: tuple, w: int):
    """Skeleton of COCO points (source px) on a crop whose top-left is `origin`."""

    def px(q):
        return int((q[0] - origin[0]) * SCALE), int((q[1] - origin[1]) * SCALE)

    for u, v in BONES:
        if u in pts and v in pts:
            cv2.line(img, px(pts[u]), px(pts[v]), col, w, cv2.LINE_AA)
    for q in pts.values():
        cv2.circle(img, px(q), w + 1, col, -1, cv2.LINE_AA)


def main():
    from experiments.E07_pose_methods.common import load

    p = argparse.ArgumentParser()
    p.add_argument("player", choices=["janys", "tom"])
    a = p.parse_args()
    d = load(a.player)
    clip, _, P = clip_info(a.player)
    preds = read_predictions(OUT / a.player / "predictions.jsonl")
    out = OUT / a.player / "videos"
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(clip))
    W, H = int(CROP_W * SCALE), int(CROP_H * SCALE)
    wr = cv2.VideoWriter(
        str(out / "preview.mp4"), cv2.VideoWriter_fourcc(*"avc1"), FPS, (2 * W, H + 60)
    )
    rows = sorted(preds)
    cap.set(cv2.CAP_PROP_POS_FRAMES, preds[rows[0]]["clip_frame"])
    pos, centre, frame = preds[rows[0]]["clip_frame"] - 1, None, None
    for i in rows:
        while pos < preds[i]["clip_frame"]:
            ok, frame = cap.read()
            pos += 1
        gt = project_gt(d, P, i)
        det = match_person(preds[i].get("pose", []), gt["midHip"])
        kp = keypoints(det)
        centre = gt["midHip"] if centre is None else 0.85 * centre + 0.15 * gt["midHip"]
        x0 = int(np.clip(centre[0] - CROP_W / 2, 0, frame.shape[1] - CROP_W))
        y0 = int(np.clip(centre[1] - 0.55 * CROP_H, 0, frame.shape[0] - CROP_H))
        crop = cv2.resize(
            frame[y0 : y0 + CROP_H, x0 : x0 + CROP_W], (W, H), interpolation=cv2.INTER_CUBIC
        )
        left, right = crop.copy(), crop.copy()

        gt_pts = {c: gt[o] for o, c in JOINTS.items()}
        draw(left, gt_pts, (x0, y0), (255, 255, 255), 3)
        draw(right, gt_pts, (x0, y0), (200, 200, 200), 1)
        draw(right, {k: v for k, v in kp.items() if k in gt_pts}, (x0, y0), (40, 140, 255), 3)
        label(left, "OpenCap (ground truth, projected)", (10, 28))
        label(right, "Roboflow YOLO pose (orange) vs OpenCap (grey)", (10, 28))
        bar = np.full((60, 2 * W, 3), 24, np.uint8)
        if det is None:
            txt = f"{a.player}  t={i / FPS:.1f}s  player not detected"
        else:
            e = frame_errors(kp, gt)
            torso = np.linalg.norm((gt["RShoulder"] + gt["LShoulder"]) / 2 - gt["midHip"])
            txt = (
                f"{a.player} 10/28  t={i / FPS:.1f}s  {'SWING' if d['in_swing'][i] else '     '}  "
                f"median joint error {np.nanmedian([e[o] for o in JOINTS]):.0f} px (torso {torso:.0f} px)"
                f"   R elbow angle err {e['elbow_err']:.0f} deg"
            )
        label(bar, txt, (12, 38), 0.75)
        wr.write(np.vstack([np.hstack([left, right]), bar]))
    wr.release()
    print(f"wrote {out / 'preview.mp4'}")


if __name__ == "__main__":
    main()
