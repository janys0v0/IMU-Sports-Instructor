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
4. `compare_imu.py` scores Roboflow's right arm next to E07's IMU methods in pixels;
   `lift3d.py` lifts it to 3D and scores everything with E08's metrics (below).

```bash
ROBOFLOW_API_KEY=... .venv/bin/python -m experiments.E09_roboflow_pose.run janys --start 35 --seconds 20
.venv/bin/python -m experiments.E09_roboflow_pose.evaluate janys
.venv/bin/python -m experiments.E09_roboflow_pose.video janys
.venv/bin/python -m experiments.E09_roboflow_pose.compare_imu janys
.venv/bin/python -m experiments.E09_roboflow_pose.lift3d janys
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

## Against our IMU methods ([`results/janys/compare_imu.md`](results/janys/compare_imu.md))

`compare_imu.py` puts E07's IMU arms into the same pixels: OpenCap's shoulder and torso rotation,
the player's segment lengths, each method's trunk-frame arm directions, projected with the same
camera. That hands the IMU methods a perfect trunk and shoulder, so Roboflow is also scored
shoulder-anchored. "OpenCap model axes" runs OpenCap's own arm through the same construction: the
floor it leaves (model bone axes vs video markers, 7–13 px/° in swings).

Right arm, swings (150 frames), medians against OpenCap:

| Method | Elbow px | Wrist px | Forearm dir ° | Elbow angle ° | 3D elbow ° |
|---|---|---|---|---|---|
| Roboflow, shoulder-anchored (as detected) | 17 (27) | 24 (27) | 25 | 38 | – |
| Ours GRU, all sensors, + own half of the block | 12 | 18 | 12 | 18 | 10 |
| IMUCoCo, Watch+phone+AirPods | 21 | 26 | 14 | 18 | 18 |
| WearMoCap, Watch | 21 | 38 | 18 | 26 | 31 |
| Ours GRU, Watch, other player only | 28 | 30 | 20 | 47 | 28 |
| MobilePoser | 38 | 57 | 41 | 41 | 35 |
| Geometric, qmt heading, rest 18° | 42 | 71 | 64 | 20 | 14 |
| OpenSense IK, 4 sensors | 39 | 74 | 81 | 15 | 30 |
| Constraints, Watch only | 42 | 52 | 17 | 62 | 40 |

Whole window (mostly between swings): Roboflow elbow 9–10 px, wrist 14 px, elbow angle 9°;
the best IMU methods are about the same (GRU personal 7 / 12 px, GRU Watch other player 8 / 12 px).

- **Between swings, Roboflow is as close to OpenCap as our best IMU models.**
- **In swings it disagrees with OpenCap more than IMUCoCo and the personal GRU do**, and less than
  the model-free methods, MobilePoser and the Watch-only GRU on the wrist. Two catches cut the
  other way: the IMU arms get OpenCap's shoulder and trunk for free, and the preview shows
  Roboflow following the visible arm where OpenCap does not. So part of its swing error is
  OpenCap's.
- **How good is OpenCap here?** This window can't say: it is the reference. E07 puts OpenCap's own
  error at ~15°, and the model-axes floor shows 7–13 px/° just from markers vs bones. Roboflow and
  OpenCap differ by 25–30° on arm segment direction in swings, about twice that; deciding which is
  right needs hand labels.
- Roboflow is 2D: no 3D elbow flexion or shoulder elevation, which E07's methods give.

## In 3D, with E08's metrics ([`results/janys/lift3d.md`](results/janys/lift3d.md))

The pixel scores above favour the IMU methods (depth errors don't show) and can't be compared with
E07/E08. `lift3d.py` lifts Roboflow's right arm to 3D and scores every method with E07's `score`,
the function E08 uses: elbow flexion, shoulder elevation, forearm inclination, segment direction,
elbow and wrist position.

**Lifting:** each keypoint pixel and phone1's camera give a ray. The elbow is where its ray meets a
sphere of upper-arm length around the shoulder, the wrist likewise around the elbow. Same help as
the IMU arms: OpenCap's shoulder, torso and segment lengths. A ray meets a sphere twice (segment
toward or away from the camera; 99 % of frames), so a smooth 3D path picks one;
"best pick" chooses with OpenCap, an upper bound. Lifting OpenCap's own pixels checks the method.

Right arm, swings, medians against OpenCap:

| Method | Elbow ° | Elev. ° | Forearm incl. ° | Upper-arm dir. ° | Forearm dir. ° | Elbow cm | Wrist cm |
|---|---|---|---|---|---|---|---|
| OpenCap's own 3D keypoints (floor) | 8 | 7 | 6 | 10 | 14 | 4 | 7 |
| OpenCap's pixels lifted, smooth path / best pick | 19 / 11 | 11 / 8 | 8 / 6 | 23 / 13 | 27 / 15 | 10 / 6 | 17 / 9 |
| **Roboflow lifted, smooth path / best pick** | 38 / 30 | 30 / 26 | 16 / 16 | 56 / 37 | 76 / 39 | 23 / 16 | 32 / 20 |
| Ours GRU, all sensors, + own half of the block | 10 | 9 | 9 | 17 | 14 | 7 | 10 |
| IMUCoCo, Watch+phone+AirPods | 18 | 25 | 11 | 41 | 28 | 17 | 22 |
| Ours GRU, Watch, other player only | 28 | 39 | 12 | 47 | 26 | 20 | 22 |
| WearMoCap, Watch | 31 | 24 | 16 | 42 | 45 | 18 | 31 |
| Geometric, qmt heading, rest 18° | 14 | 24 | 23 | 92 | 62 | 36 | 57 |
| OpenSense IK, 4 sensors | 30 | 18 | 21 | 88 | 74 | 34 | 58 |

- **In 3D, one camera loses to the better IMU methods in swings.** Even with a perfect front/back
  pick, Roboflow's lifted arm (wrist 20 cm, forearm 39°) is behind the personal GRU (10 cm, 14°),
  IMUCoCo (22 cm, 28°) and the Watch GRU (22 cm, 26°). It still beats the model-free IMU methods
  on direction, whose heading drifts.
- **Why:** depth from one side-on camera. Lifting OpenCap's perfect pixels gets close to the floor
  (wrist 9 cm) only with the right pick; the smooth path alone loses ~10°, and 5–10 px of pixel
  noise doubles the direction errors (checked by adding noise). Roboflow's arm keypoints are
  17–27 px off in swings.
- **Between swings** (whole window, `lift3d.md`) Roboflow lifted is mid-pack: elbow 15°, wrist
  15 cm (Watch GRU 16° / 11 cm, personal GRU 6° / 5 cm).
- These are one 20 s window of one player; the IMU numbers differ from E07's two-player blocks.

**Limits:** one player, 20 s, one camera far from the player (torso 82 px); image-plane angles
only; the reference is OpenCap reprojected through a camera fitted from feet and head, not
hand labels.

**Next:** fuse Roboflow's 2D arm with the IMUs (camera fixes heading, IMUs fix front/back);
hand-label 30–50 swing frames to grade Roboflow, OpenCap and the IMU arms on the same
images; or project into one
of OpenCap's own calibrated cameras instead of phone1.
