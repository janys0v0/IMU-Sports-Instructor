# E04: IMU joint angles against single-camera video

**Question:** how closely do the joint angles from MobilePoser (Watch + phone + AirPods) match
what a camera sees, per joint and per activity? A first number before OpenCap
([`docs/deferred/opencap.md`](../../docs/deferred/opencap.md)); dev-plan stage 11.

## Method

1. **Align** (`align.py`): the video file's creation time gives the start to about 1 s. The
   offset is then refined by cross-correlating on-screen motion (frame differences; a strip can
   be masked for bystanders) with Watch and phone motion. Both devices must agree within 0.2 s.
2. **Video pose** (`vision_pose.swift`): Apple Vision's 3D body pose (built into macOS 14+, no
   download), every 2nd frame. A mirrored video (Photo Booth) only swaps left and right names.
3. **IMU pose:** MobilePoser on all devices, calibrated as in E01-E03 (`common/session.py`).
4. **Angles** (`angles.py`), computed the same way from both 3D joint sets, so neither world
   frame matters: elbow and knee flexion (0° straight), shoulder elevation (0° arm down).
5. **Agreement:** IMU angle interpolated at each video frame; bias, RMSE, MAE and correlation,
   overall and per activity (`annotations/<session>.json`); windows marked `excluded` are left out.
   Checks: the lag left after alignment, and that the Watch arm matches its own side best.

## Recording checklist

- Camera on a stand, landscape, whole body in frame with headroom, 3-5 m away, 45° to the front;
  plain background, nobody else in the frame.
- Start the video first, then Start; 3 hops and a clap on camera at the start and the end.
- Calibrate on camera facing the camera ("Face: the camera"); one Trial per motion, 30-60 s each,
  2 s still before and after.
- Photo Booth mirrors its videos: set `"video": {"mirrored": true}` in the annotation.

## Run

```bash
.venv/bin/python -m experiments.E04_video_validation.run field/20261019-000116-P01
```

Side-by-side video (camera with Vision's skeleton, then the IMU mesh for each Watch
calibration), after `run.py`:

```bash
.venv/bin/python -m experiments.E04_video_validation.make_video field/20261019-000116-P01
```

It crops the camera to the subject (the annotation's `mask_left`, which also hides bystanders)
and writes `results/<session>/videos/side_by_side.mp4` (not committed).

Put the video in `data/recordings/field/<session>/video/` (never committed). The first run
writes `alignment.json` and `vision_pose.json` next to it (Vision takes about 1 s per frame);
`--realign` redoes both. Results: `results/<session>/` (`metrics.json`, `summary.md`, `angles.png`).

## Limits

- Vision's 3D pose from one camera has its own error, worst for side-on poses and depth; this
  is agreement between two estimates, not accuracy against ground truth.
- Left-side limbs carry no sensor here (Watch on the right wrist, phone in the right pocket), so
  their angles test the model's inference, not a measurement.
- Angles only: positions and translation are not compared.

## Findings so far

- The Watch measures the forearm well (sensor alone vs video: r 0.80). The model was given the
  wrong rest pose for it until 2026-10-19 (`with_standing_rest`); fixed.
- Remaining arm error (~30°) is the model: one wrist sensor cannot separate upper-arm raise
  from elbow bend.

## Results

See the newest entry for E04 in [`EXPERIMENT_LOG.md`](../../EXPERIMENT_LOG.md) and
`results/<session>/summary.md`.
