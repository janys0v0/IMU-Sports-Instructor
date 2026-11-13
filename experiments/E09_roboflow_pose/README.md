# E09: Roboflow YOLO pose on one camera vs OpenCap

**Question:** how close does a monocular 2D pose model (our Roboflow workflow
`tennis-swing-motion-baseline`, YOLO pose + a racket detector) get to OpenCap on the
tennis court, from one phone?

**Data:** Janys, 10/28, phone1 (by the net, 1920×1080, 59.94 fps), 20 s from 35 s into the
block (600 frames on E07's 30 Hz grid, OpenCap valid on 599, 150 frames in swings). Ground truth:
OpenCap's 3D video keypoints projected into phone1 with E06's fitted camera (median fit error
7.2 px; [`camera.py`](../E06_side_by_side/camera.py)).

**Method:**
1. `run.py` sends each frame (JPEG, full size) to the hosted workflow and saves its keypoints
   (`results/<player>/predictions.jsonl`). The key comes from `ROBOFLOW_API_KEY`.
2. `evaluate.py` takes the detection nearest OpenCap's projected mid-hip (none if > 150 px away),
   drops keypoints below 0.3 confidence, and scores 12 joints (shoulders, elbows, wrists, hips,
   knees, ankles) in pixels, as PCK at 0.2 × torso length, and the right elbow's image-plane
   angle.
3. `video.py` draws both skeletons on a crop that follows the player.

```bash
ROBOFLOW_API_KEY=... .venv/bin/python -m experiments.E09_roboflow_pose.run janys --start 35 --seconds 20
.venv/bin/python -m experiments.E09_roboflow_pose.evaluate janys
.venv/bin/python -m experiments.E09_roboflow_pose.video janys
```

## Results ([`results/janys/summary.md`](results/janys/summary.md))

Player found in 98 % of frames; torso about 82 px tall in this view.

| Joints | Median px | Swing median px | PCK@0.2 torso |
|---|---|---|---|
| Shoulders | 6–7 | 9–10 | 92 % |
| Hips | 9–10 | 10–11 | 94–95 % |
| Elbows | 10–15 | 17–27 | 55–71 % |
| Wrists | 13–14 | 18–27 | 60–62 % |
| Knees, ankles | 18–24 | 17–23 | 12–37 % |

All joints: median 14 px, PCK 60 %. Right elbow angle (image plane): 9° median, 38° in swings.

- **Trunk agrees within the reference's own error.** Shoulders and hips are within 7–10 px,
  about the camera fit's 7 px.
- **Arms and legs: the reference is the limit, not Roboflow.** On the preview, Roboflow's legs sit
  on the visible legs in the ready stance while the projected OpenCap legs do not, and mid-swing
  its arm follows the real arm while OpenCap's sits above it. Knee and ankle errors stay flat at
  ~20 px whatever the motion, which points to an offset in the reference. The leg numbers and the
  38° swing-elbow number therefore partly measure OpenCap + the phone1 fit.
- The workflow is deterministic: a second run returned the same keypoints (0.0 px).

**Limits:** one player, 20 s, one camera far from the player (torso 82 px); image-plane angles
only; the reference is OpenCap reprojected through a camera fitted from feet and head, not
hand labels.

**Next:** hand-label 30–50 swing frames to grade the arms and legs fairly; or project into one
of OpenCap's own calibrated cameras instead of phone1.
