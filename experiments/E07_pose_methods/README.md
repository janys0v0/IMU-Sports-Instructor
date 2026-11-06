# E07: Arm pose during tennis swings, method by method, against OpenCap

**Question:** which way of turning wearable IMU data into arm angles works best for the swinging
arm: plain geometry from segment orientations (the OpenSense idea), OpenSense itself, physical
joint constraints, published learned models, or models we train on our own data?

**Data:** the 10/28 tennis blocks with every sensor (`janys` 8.1 min, `tom` 12.6 min; OpenCap on
79 % / 70 % of frames, 128 swings) and, for training the Apple-only models, every Calibrate
segment OpenCap covers (26.8 / 12.0 min). Sensors: iPhone (right pocket), Apple Watch (right
wrist), AirPods; commercial chest (2F5A), right upper arm (1D03) and wrist (D0E5) sensors.
Ground truth: OpenCap (two phone videos, OpenSim model), on our clock as in E06.

**What is scored** (`evaluate.py`), all in the trunk frame and model-independent: elbow flexion;
shoulder elevation; forearm inclination (how far the forearm points up, heading-free); forearm
and upper-arm direction (full 3D, heading-dependent). Median absolute error over the block and
over swings (±0.5 s around each peak of the Watch's 200 Hz rotation speed).

## Methods

| Family | Method (file) | Sensors | Learning |
|---|---|---|---|
| Geometric | segment orientations straight from the sensors (`geometric.py`); headings made consistent without magnetometers (`align.py`: trunk pulled to the phone's heading, upper arm by the elbow-hinge constraint against the Watch); qmt's published heading correction (`qmt_heading.py`, Laidig et al.) | chest + upper arm + Watch | none |
| OpenSense | OpenSim 4.6 IMU inverse kinematics on OpenCap's own scaled model, joint limits (`opensense.py`, `opensense_ik.py`) | chest + upper arm + Watch + phone; fewer | none |
| Constraint | Watch only: elbow hinge + twist leave 2 unknowns; joint limits, "arm hangs" effort, smoothness, Viterbi (`constraint.py`, ArmTrak idea without its HMM) | Watch | none |
| Published | WearMoCap (IROS 2023, pretrained Watch LSTM; `wearmocap.py`), MobilePoser (UIST 2024), IMUCoCo (UIST 2025, also with the upper-arm and chest sensors placed on the mesh) (`learned_published.py`) | Watch (+phone, AirPods, ...) | pretrained elsewhere |
| Ours | ridge regression and a bidirectional GRU on heading-free features (`learned_own.py`); trained on the other player only, or also on the test player's own other minutes | Watch; Watch+phone; all | 10/28 data |

Not runnable: ArmPoser (Northwestern, SUI 2026) has released no code or weights yet; the
6-sensor models (DIP, TransPose, PIP, PNP, DynaIP, TIP) need sensors on both wrists and knees.
Survey and links: the research notes in the report.

## Results (swings; mean of the two players, from `results/summary.md`)

| Method | Elbow | Shoulder elev. | Forearm incl. | Forearm dir. |
|---|---|---|---|---|
| Geometric, qmt heading, hanging elbow = 18° | **11** | 16 | 18 | 52 |
| OpenSense IK, 4 sensors | 26 | 15 | 24 | 65 |
| Constraints, Watch only | 28 | 35 | 15 | 38 |
| WearMoCap, Watch | 27 | 20 | 12 | 35 |
| MobilePoser, Watch+phone+AirPods | 27 | 39 | 22 | 40 |
| IMUCoCo, Watch+phone+AirPods | 30 | 26 | 12 | 33 |
| Ours GRU, Watch, other player only | 21 | 25 | 15 | **26** |
| Ours GRU, all sensors, + own half of the block | **9** | **7** | **6** | **13** |

- **Shoulder elevation and the elbow need a sensor on the upper arm, or the player's own data.**
  With chest + upper arm + Watch, pure geometry gets elevation within 15° in swings (10° over the
  block) and, with one fixed rest angle, the elbow within 11° (7° over the block). Every
  published model and every Watch-only method is 20-40° off on elevation during swings.
- **Heading is the weak point of everything model-free.** The court's magnetic field is too
  disturbed for the commercial sensors' magnetometers (VQF 9-axis drifts more than 6-axis), and
  without them heading drifts 15-20°/min. Constraint-based alignment fixes the elbow (qmt: elbow
  r 0.86-0.87 with OpenCap) but not the trunk-relative direction of the arm (forearm direction
  44-60° off). Body "forward" from the pocket phone's screen was wrong by ~110° for Tom; the
  thigh's mean lean is a better cue but not reliable.
- **All model-free methods read the elbow 17-19° straighter than OpenCap**, for both players: they
  take the hanging arm at Calibrate as straight, OpenCap sees it bent. One fixed 18° rest angle
  removes it.
- **Pretrained models do not transfer well to tennis.** WearMoCap (Watch only) is the best of
  them on the forearm; MobilePoser and IMUCoCo are 25-40° off on elevation in swings; adding the
  commercial upper-arm and chest sensors to IMUCoCo did not help (placement on the mesh is not a
  calibration).
- **Our trained models, other player only,** beat the published ones on direction (GRU forearm
  26°) but not on the elbow (21°); with all sensors they fail across players (elevation 56°):
  20 minutes from two people cannot teach a 9-sensor model to generalise.
- **With the player's own data the error halves** (all-sensor GRU: elbow 9°, elevation 7°,
  forearm 13° in swings). Caveat: training and test are minutes apart in the same session; this
  is the best case, not a new-player number.

**Limits:** two players, one session; OpenCap's own error (~15°, and it follows the wrong person
at times) bounds every number; the commercial sensors are only on the right arm and chest; the
personal splits are within one session.

**Next:** a fixed rest-angle calibration in the pipeline; a calibration move that fixes heading
(arm raised forward) for the geometric route; record more players with the upper-arm sensor for
a cross-player model; ArmPoser when it is released.

```bash
.venv/bin/python -m experiments.E07_pose_methods.data           # blocks (all sensors)
.venv/bin/python -m experiments.E07_pose_methods.data --full    # Apple-only, every covered segment
.venv/bin/python -m experiments.E07_pose_methods.align
.venv/bin/python -m experiments.E07_pose_methods.geometric
.venv/bin/python -m experiments.E07_pose_methods.qmt_heading
.venv/bin/python -m experiments.E07_pose_methods.constraint
.venv/bin/python -m experiments.E07_pose_methods.wearmocap      # needs third_party/wearmocap
.venv/bin/python -m experiments.E07_pose_methods.opensense      # needs the OpenSim micromamba env
.venv/bin/python -m experiments.E07_pose_methods.learned_published
.venv/bin/python -m experiments.E07_pose_methods.learned_own ridge gru [--all-sensors]
.venv/bin/python -m experiments.E07_pose_methods.evaluate
.venv/bin/python -m experiments.E07_pose_methods.figures
.venv/bin/python -m experiments.E07_pose_methods.video tom --methods a,b,... [--start S --seconds N]
```
