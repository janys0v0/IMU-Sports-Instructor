# ES 224 experiment log

The running record of every experiment: what was asked, what was run, and what came out.
Newest entries at the bottom. Code and per-experiment details live in
[`experiments/`](experiments/README.md); each experiment's own `README.md` holds its
method and full results.

## Index

| ID | Question | Folder | Status |
|---|---|---|---|
| E00 | Does published MobilePoser reproduce on the IMUPoser dataset? | [`experiments/E00_mobileposer_reproduction/README.md`](experiments/E00_mobileposer_reproduction/README.md) | Done 2026-09-30 |
| E01 | How much does each device (phone, Watch, AirPods) contribute to MobilePoser? | [`experiments/E01_mobileposer_device_ablation/`](experiments/E01_mobileposer_device_ablation/README.md) | Done 2026-10-08 |
| E02 | MobilePoser vs IMUCoCo on the same inputs | [`experiments/E02_imucoco_comparison/`](experiments/E02_imucoco_comparison/README.md) | Done 2026-10-08 |
| E03 | Data consistency of each sensor stream (rate, missingness, delay) vs motion | [`experiments/E03_stream_quality/`](experiments/E03_stream_quality/README.md) | Done 2026-10-14 |

## Reference recordings

| Session | Devices | Content | Labels |
|---|---|---|---|
| `20261008-153213-P01` | phone right pocket (screen to leg), Watch right wrist, AirPods | Calibrate, 3 slow jumping jacks, 3 tennis swings, 3 squats, look left and right (63.7 s; 45 s after calibration) | [`annotations/20261008-153213-P01.json`](experiments/annotations/20261008-153213-P01.json) |

Recordings live in `data/recordings/<session>/` (`mac_stream.jsonl`, `summary.json`,
`reconstruction.mp4`).

---

## 2026-10-08

### Setup on the new Mac
- Rebuilt MotionStreamer (iPhone + Watch) with Xcode 27; bundle ID changed to
  `edu.es224.jjl.motionstreamer` (the old one belonged to another team). Free-account signing:
  installs expire 2026-10-15.
- Python environment `code/.venv` (Python 3.9, torch 2.1.2, Open3D 0.17 with a bundled libomp)
  replaces the conda env described in `pipeline/README.md`.
- Network: the iPhone must be on the same Wi-Fi as the Mac (campus Wi-Fi works when both are on
  it); the Mac could see the Watch in Xcode only on a non-isolated network.

### Recording the reference session
- Watch moved to the right wrist; the app's unlabeled Left/Right switch sets both the Watch
  wrist and the phone pocket side.
- **App bug found:** pressing Stop during a calibration countdown leaves the countdown timer set,
  so every later Calibrate tap is ignored until the app is relaunched (sessions
  `20261008-152953`, `-153027`, `-153037` have no calibrate events). Workaround: force-quit the
  app. One-line fix (`calibrationTimer = nil` in `StreamController.stop()`) not yet applied.
- `20261008-153213-P01` recorded after relaunching: all three devices calibrated "ok", coverage
  ≥ 92 %, live viewer at 30 fps. Chosen as the reference recording.

### Choosing a comparison model
Checked which published models could run on head + one wrist + thigh data:

| Model | Pretrained weights | Fits our devices | Decision |
|---|---|---|---|
| IMUPoser (CHI 2023) | No (train on AMASS + DIP-IMU) | Yes | Not now: needs dataset registration and days of training |
| 3SIP (2026) | No | Head + both wrists | No |
| BaroPoser (UIST 2025) | No ("coming soon") | Phone + Watch + barometer | No |
| TransPose / PIP / DynaIP | TransPose yes | Exactly 6 sensors | No |
| **IMUCoCo (UIST 2025)** | **Yes** | Any placement, any number | **E02** |
| DiffusionPoser (CVPR 2024) | Not verified | Any subset of 13 | Possible later |

### E01: MobilePoser device ablation
- Command: `.venv/bin/python experiments/E01_mobileposer_device_ablation/run.py` (session
  `20261008-153213-P01`, all 7 device subsets, calibration shared).
- **The Watch is what moves the arm:** forearm error ≈45° with it, ≈90° without; jumping jacks
  detected 3/3 with it, 0-1/3 without.
- **Squats are robust:** 3/3 in every configuration except Watch-only (2/3), knee peak 100-117°.
- **AirPods improve the head:** head error 26° → 17° when added to phone + Watch. Right head turn
  is under-estimated (−16° vs AirPods −72°) in every configuration with the Watch.
- MobilePoser was trained only on combinations that include the pocket phone, so `rw_h`, `rw`
  and `h` are out-of-distribution (reported, flagged).
- The forearm stays ~42-51° from the Watch even when the Watch is an input, while thigh and head
  reach 5-7° at rest. First attempt to explain it (an "arm hanging down" rest pose for the Watch)
  scored worse, but it was scored against MobilePoser's own output, so it was inconclusive.
  Explained by E02 below.

### E02: MobilePoser vs IMUCoCo
- Set up IMUCoCo (commit `d7dd17c`, three weight files ≈ 225 MB from the authors' site, loaded
  with `weights_only=True`) in the existing `.venv`; no new packages were needed.
- Command: `.venv/bin/python experiments/E02_imucoco_comparison/run.py`.
- **IMUCoCo follows its sensors far more closely:** head yaw RMSE 4° vs 22° (right turn −77° vs
  AirPods −72°; MobilePoser −16°); sensor-bone errors 5-13° vs 17-45° (full device set).
- **MobilePoser fills in the body, IMUCoCo does not:** unsensed left arm rises in MobilePoser's
  jumping jacks (0.81 m) but stays down in IMUCoCo (−0.05 m); without the pocket phone IMUCoCo's
  squats shrink to 72° (MobilePoser 117°).
- **Main finding: the Watch calibration is wrong for the arm.** In the side-by-side video
  IMUCoCo holds the right arm out to the side when it should hang (standing, squats, head turns).
  Resting wrist height right after calibration, 18.2-19.5 s (hanging arm ≈ −0.05 m): no Watch
  −0.09 m (MP) / +0.01 m (CoCo); with the Watch +0.29 m (MP, both arms) / +0.48 m (CoCo, right arm). Calibration sets every
  bone to identity while standing; for the forearm identity is the SMPL T-pose (arm horizontal),
  so the Watch reports "arm out" while it hangs. MobilePoser's prior pulls it partway back;
  IMUCoCo copies it. This also explains E01's ~45° forearm offset. It affects the live viewer
  and every rendered video so far (arms slightly raised at rest).
- Added a "standing_still" window (18.2-19.5 s) to the annotation and a resting-wrist-height
  metric; re-ran E01 and E02 (E02 without re-rendering videos).

### Open items
- Apply the MotionStreamer calibration-timer fix (needs the iPhone cabled for a reinstall).
- **Fix the Watch calibration convention** (T-pose calibration for the Watch, or apply the
  hanging-arm rest rotation), verify with resting wrist height ≈ −0.05 m, then rerun E01 and E02.
- More reference recordings (different days, left-side devices) before drawing conclusions from
  one session.
- No optical ground truth yet; all metrics are relative to the sensors and the annotated routine.

---

## 2026-10-13

### Literature update: state of the art for head + wrist + pocket
- Searched for 2025-2026 work and compared published numbers; write-up:
  [`docs/research/model-comparison.md`](docs/research/model-comparison.md).
- **No new model can run on our recordings.** ArmPoser (Watch-only arm, calibration-free, SUI
  2026) has a placeholder repo; "One Sensor, Whole Body" (AirPods-only, ACM MM workshop 2026) has
  code but no weights or data; BaroPoser, IMUPoser, 3SIP and Progressive Inertial Poser publish
  no weights. MobilePoser and IMUCoCo (E02) remain the only runnable state of the art.
- Only published head-to-head on our exact device set (IMUCoCo paper, wrist + pocket + ear):
  IMUCoCo 27.6 deg vs MobilePoser 31.8 deg global angular error. Consistent in direction with E02.
- The MobilePoser paper specifies a **T-pose calibration**; our pipeline calibrates standing with
  arms down. This supports the E02 finding that the Watch calibration convention is wrong for the arm.
- No experiments were run today.

## 2026-10-14

### E02 videos for every device combination
- Added `experiments/E02_imucoco_comparison/make_videos.py`: renders both models' saved E02
  outputs (no model re-run) for all 7 combinations and composes side-by-side videos labelled with
  time and activity. Outputs in `E02_imucoco_comparison/results/20261008-153213-P01/videos/`:
  `compare_<combo>.mp4` (7 files) and `grid_all.mp4`; all 1,336 frames verified.
- Visual check at the bottom of a squat (52.3 s): MobilePoser squats in every combination except
  Watch-only; IMUCoCo squats less deeply and raises the Watch arm in every combination with the
  Watch (the calibration issue from E02). Outputs still use the uncorrected Watch calibration.

### E02 model-sensor agreement + trajectory figures
- Added `E02_imucoco_comparison/plot_agreement.py` (first named plot_consistency.py; renamed so
  "consistency" means stream quality, E03); wrote `agreement_trajectories_rw_rp_h.png` and
  `agreement_trajectories_rw_h.png` in the E02
  results folder (from saved outputs, no model re-run).
- Model-sensor agreement, mean over the 7 combinations (sensor as input / held out, deg):
  MobilePoser head 20 / 29, thigh 16 / 27, forearm 46 / 93; IMUCoCo head 5 / 26, thigh 12 / 33,
  forearm 9 / 93. When a sensor is held out both models are similarly far from it; IMUCoCo's
  advantage is in copying the inputs it is given.

### E03: data consistency of each sensor stream
- Command: `.venv/bin/python experiments/E03_stream_quality/run.py` (session
  `20261008-153213-P01`). Figure `E03_stream_quality/results/20261008-153213-P01/stream_quality.png`
  shows rate, missingness, delay and motion trajectories in one image.
- Calibration end → Stop: iPhone 33.5 Hz (60 requested), 99.3 %, 10 missing, 1 gap (329 ms);
  Watch 66.4 Hz (60), 99.7 %, 5 missing, no gap > 100 ms, delay 341 ms; AirPods 50 Hz (25),
  95.7 %, 5 missing, 14 gaps > 100 ms.
- The AirPods are the least consistent stream: gaps without missing indices mean the AirPods
  themselves pause or deliver late, not that packets are lost on Wi-Fi.
- Open question: after the jumping jacks the Watch tilt stays 75-88 deg from its calibration pose
  at moments when the arm was expected to hang (gravity-referenced, so not drift). Either the
  forearm was bent or the Watch shifted on the wrist; confirm with the participant or video.

### E02 per-frame error scatter: MobilePoser vs IMUCoCo
- Added `E02_imucoco_comparison/plot_error_scatter.py`; wrote `error_scatter_rw_rp_h.png` and
  `error_scatter_all.png` (each frame: MobilePoser angle from the sensor vs IMUCoCo's).
- Sensor given: IMUCoCo closer in 87-99 % of frames, weak correlation between models (r 0.23-0.45
  for head and forearm with all devices).
- Sensor held out: roughly even (IMUCoCo closer in 41-68 %) and strongly correlated (r 0.50-0.95);
  both models miss the same frames. Exception: thigh with Watch only, IMUCoCo 43° vs MobilePoser 16°.
- Supports the E02 reading: IMUCoCo's advantage is copying the sensors it gets, not predicting
  unsensed parts.

### E02 errors vs device signals
- Added `E02_imucoco_comparison/plot_error_vs_signals.py` (and kept per-device rotation rate in
  `common/session.py`); wrote `error_vs_signals.png` / `.json`.
- Thigh disagreement rises with rotation from standing for both models (ρ 0.52-0.74): squat depth is
  under-estimated, matching the knee-raise compression noted in pipeline/README.md.
- Forearm patterns (Watch given: MobilePoser better far from the calibration pose; Watch held out:
  worst when the arm is still) are consistent with the Watch calibration convention error.
- No relation with sample age (gaps rare in this session), so stream quality did not drive errors here.

### E02 relative drift, both models on a common baseline
- Added `E02_imucoco_comparison/plot_drift.py`; wrote `drift.png` / `drift.json`. Both models are
  zeroed on the standing-still window (18.2-19.5 s) so constant offsets cancel.
- Translation (in-place routine, all devices): MobilePoser 1.08 m at routine end (1.6 m/min),
  IMUCoCo 0.19 m (max 0.56 m). IMUCoCo drifts less when the pocket phone is present, far more
  without it (Watch only 2.5 m).
- Orientation drift where devices return to the reference pose: head 9.7 vs 4.5 deg/min, thigh 7.5
  vs 6.6 deg/min (MobilePoser vs IMUCoCo). Forearm not measurable: the Watch never returns to its
  calibration pose (E03 open question).

## 2026-10-17

### Device check T6, first runs (stage 0b)

- **Smoke test `20261017-170818-P01` (2 min):** found three bugs, all fixed: the Watch's high-rate
  stream started before its workout (CMError 109), the Watch opened its own `-W` session, and the
  Watch's buttons failed silently.
- **Sitting run `20261017-173115-P01` (22 min, phone in pocket):** ingest PASS; phone 100 %, AirPods
  99.99 % (one 0.12 s gap), AirPods 50 Hz unchanged around 47 spoken phrases, Watch high-rate
  797 / 199 Hz, Watch clock fit 16 ms RMS. **Not a valid T6:** the app never went to the background
  (no `app_background` event), so the phone was never locked, and it was charging (battery 90 → 95 %).
  `device_check.py` now fails T6 unless the app is in the background ≥ 80 % of the run.
- **Next:** rerun T6 unplugged, locked with the side button.
