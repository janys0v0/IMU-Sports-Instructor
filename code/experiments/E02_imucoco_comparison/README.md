# E02: MobilePoser vs IMUCoCo

**Question.** On our own consumer-device recordings, how does MobilePoser (UIST 2024) compare
with a newer model that accepts arbitrary sensor placements, IMUCoCo (Zhou et al., UIST 2025)?
IMUCoCo was chosen because it is the only comparable model with downloadable pretrained weights
that accepts head + one wrist + thigh (checked 2026-10-08: IMUPoser, 3SIP and BaroPoser publish
no weights; TransPose/PIP need six fixed sensors). See EXPERIMENT_LOG.md.

**Method.**
- Session: reference routine `20261008-153213-P01`, labels in `../annotations/`.
- **Identical inputs:** both models get the same calibrated body-frame orientation and
  acceleration (`common/session.py`). MobilePoser runs at 30 Hz; IMUCoCo at 60 Hz, its training
  rate, then every other frame is kept so both outputs share the same 30 Hz time grid.
- **Identical placements:** each device is attached to IMUCoCo's body mesh at the vertex
  MobilePoser's virtual sensors use (`mobileposer/process.py` `vi_mask`: right wrist 5424,
  right thigh 4362, head 411).
- Every non-empty subset of {right_wrist, right_pocket, head} (7 configurations) for both models.
- Same metrics as E01 (`common/metrics.py`).

**IMUCoCo setup** (done 2026-10-08; repeat on a new machine):
1. `git clone --depth 1 https://github.com/cmusmashlab/IMUCoCo.git code/IMUCoCo`
   (tested at commit `d7dd17c`).
2. Download the three weight files from the IMUCoCo README into `code/IMUCoCo/saved_checkpoints/`:
   `imucoco_best.pth` (90 MB), `poser_dtp_best.pth` (134 MB), `all_error_loss_map.pth` (0.7 MB),
   from `https://synergylabs.org/haozhe/<file>`.
3. `ln -s ../../MobilePoser/mobileposer/smpl/basicmodel_m.pkl code/IMUCoCo/smpl/SMPL_MALE.pkl`
   (same SMPL male model MobilePoser uses).
4. No extra packages: the model code needs only torch, numpy and scipy, which the project
   `.venv` (torch 2.1.2) already has. IMUCoCo's full `requirements.txt` is for its viewer,
   training and live demo, which this experiment does not use.

Weights are loaded with `torch.load(..., weights_only=True)` (tensors only).

**Differences from IMUCoCo's own live demo**, all intentional:
- The demo calibrates in a **T-pose**; our recordings calibrate standing with arms down. Both
  models therefore get the same "identity while standing" bone convention. This favours neither
  model, but IMUCoCo was not designed for it.
- The demo feeds the phone's raw `userAcceleration` (device frame, in g) as if it were world-frame
  m/s². This adapter feeds body-frame m/s², which matches IMUCoCo's training data
  (`data_generation.py`: finite differences × 3600 at 60 fps).
- Offline: the whole recording is fed frame by frame through the online model, with no viewer.

**Run.** From `project/code`: `.venv/bin/python experiments/E02_imucoco_comparison/run.py [SESSION] [--configs rw_rp_h,rw_h] [--no-video]`.
IMUCoCo takes about 4-5 minutes per configuration on a laptop CPU (about 30 minutes for all 7).

**Outputs** in `results/<session>/`: `metrics.json`, `summary.md`, `signals_<combo>.png` (both
models over time), `outputs/<model>_<combo>.npz` (poses, joints, translation),
`videos/rw_rp_h.mp4` and `videos/rw_h.mp4` (MobilePoser | IMUCoCo side by side).

**Agreement + trajectory figure:** `.venv/bin/python experiments/E02_imucoco_comparison/plot_agreement.py [SESSION] [--combo rw_rp_h]`
writes `agreement_trajectories_<combo>.png`: wrist heights, knee flexion and head yaw over time;
model-vs-sensor angle over time for each sensor-bearing bone; the right wrist's front-view path
per activity; and mean model-sensor agreement with each sensor as an input vs held out across all 7
combinations. From saved outputs, about 30 s.

**Per-frame error scatter:** `.venv/bin/python experiments/E02_imucoco_comparison/plot_error_scatter.py [SESSION]`
plots MobilePoser's model-vs-sensor angle (x) against IMUCoCo's (y) for every frame and every
sensor-bearing bone, coloured by activity: `error_scatter_rw_rp_h.png` (full device set) and
`error_scatter_all.png` (all 7 combinations). Below the diagonal = IMUCoCo closer to the sensor.

**Errors vs device signals:** `.venv/bin/python experiments/E02_imucoco_comparison/plot_error_vs_signals.py [SESSION]`
plots each bone's model-vs-sensor angle against its own device's rotation rate, acceleration,
rotation from the calibration pose and sample age, for both models with the sensor given and
held out: `error_vs_signals.png` + `error_vs_signals.json` (Spearman ρ per panel).

**Relative drift:** `.venv/bin/python experiments/E02_imucoco_comparison/plot_drift.py [SESSION]`
zeroes both models on the same standing-still window, then measures horizontal root drift (the
routine is done in place) and orientation drift where each device returns to its reference pose:
`drift.png` + `drift.json`.

**Videos for every combination:** `.venv/bin/python experiments/E02_imucoco_comparison/make_videos.py [SESSION]`
re-renders from `outputs/` without re-running the models (about 15 minutes) and writes
`videos/compare_<combo>.mp4` (MobilePoser | IMUCoCo for one combination, 960×550),
`videos/grid_all.mp4` (rows = models, columns = all 7 combinations; red * = combination
MobilePoser was not trained on, 1950×590) and the per-model clips in `videos/single/`. Every
frame shows the time after Start and the annotated activity.

## Results: 20261008-153213-P01 (2026-10-08)

Full tables: [`results/20261008-153213-P01/summary.md`](results/20261008-153213-P01/summary.md).
Videos: `results/20261008-153213-P01/videos/rw_rp_h.mp4` and `rw_h.mp4` (MobilePoser left, IMUCoCo right).

| Devices | Model | Forearm / thigh / head err | Rest wrist R / L, 18.2-19.5 s (hanging ≈ −0.05 m) | JJ (3) R / L wrist peak | Squats (3), knee peak | Head yaw RMSE |
|---|---|---|---|---|---|---|
| `rw_rp_h` | MobilePoser | 45° / 21° / 17° | +0.29 / +0.29 m | 3, 0.82 / 0.81 m | 3, 112° | 22° |
| `rw_rp_h` | IMUCoCo | 9° / 13° / 5° | **+0.48** / −0.02 m | 4, 0.79 / **−0.05** m | 3, 102° | **4°** |
| `rw_h` | MobilePoser (untrained combo) | 44° / 26° / 17° | +0.31 / +0.30 m | 3, 0.86 / 0.86 m | 3, 117° | 31° |
| `rw_h` | IMUCoCo | 9° / 25° / 5° | +0.48 / −0.02 m | 4, 0.79 / −0.05 m | 3, **72°** | 4° |
| `rp_h` | MobilePoser | 88° / 15° / 24° | −0.09 / −0.09 m | 1 | 3, 108° | 22° |
| `rp_h` | IMUCoCo | 93° / 13° / 5° | +0.01 / 0.00 m | 0 | 3, 105° | 4° |

**Findings.**
1. **IMUCoCo follows its sensors much more closely.** Head yaw RMSE 4° vs 22° (it gets the right
   turn, −77° vs AirPods −72°, where MobilePoser gives −16°); sensor-bone errors 5-13° vs 17-45°.
2. **Following the sensors exposes the Watch calibration problem.** With the Watch, IMUCoCo holds
   the right arm out (rest wrist +0.48 m; arm up during squats and out during head turns in the
   video). The calibration says "forearm = identity" while the arm hangs, and identity is the
   T-pose. MobilePoser's prior reduces it (+0.29 m) but lifts both arms. So IMUCoCo's 9° forearm
   "error" means it copies a wrong input; it is not evidence of a better arm.
3. **MobilePoser fills in the body; IMUCoCo does not.** The left arm (no sensor) rises with the
   right in MobilePoser's jumping jacks (correct here) but stays down in IMUCoCo (−0.05 m).
   Without the pocket phone (`rw_h`), IMUCoCo's squats shrink to 72° while MobilePoser keeps 117°.
4. **Both count squats reliably** whenever the phone or AirPods are present; IMUCoCo counts 4 arm
   raises in the jumping jacks (it includes the partial first raise).
5. **Single devices.** Watch only (`rw`) loses the legs and head for both models (0-2 squats,
   head yaw RMSE 55° / 78°). AirPods only (`h`) still tracks head yaw (14° / 4°) and finds squats
   (3 / 2 of 3) from the head dropping. See summary.md.

**Takeaway.** For directly instrumented signals (head yaw, the Watch arm's motion) IMUCoCo is
more faithful; for plausible whole-body output from few sensors MobilePoser is better. Neither
comparison is fair to the Watch until its calibration convention is fixed; rerun E01/E02 after
that fix.

**Per-frame scatter (2026-10-14, `error_scatter_*.png`).**
- **Sensor given to the models:** IMUCoCo is closer in 87-99 % of frames for every bone (full set:
  head 97 %, thigh 87 %, forearm 99 %). The two models' angles are weakly correlated on head and
  forearm (r 0.23-0.45): IMUCoCo stays near the sensor whatever MobilePoser does.
- **Sensor held out:** the models are close to even (IMUCoCo closer in 41-68 % of frames) and
  strongly correlated (r 0.50-0.95), i.e. they fail on the same frames. Exception: thigh with
  Watch only, where IMUCoCo is much worse (median 43° vs 16°; closer in only 16 % of frames).
- **Held-out forearm during squats:** IMUCoCo ~100-120° from the Watch vs MobilePoser 50-100°.
  IMUCoCo keeps the unsensed arm hanging while the Watch reports it forward; MobilePoser's
  prior raises the arms.

**Errors vs device signals (2026-10-14, `error_vs_signals.png`; routine frames, n = 1239).**
- **Thigh: disagreement grows with how far the thigh is from standing** (Spearman ρ 0.52-0.74 for
  both models, given or held out): both under-rotate deep squats.
- **Head:** MobilePoser's disagreement grows with rotation rate and rotation from calibration
  (ρ ≈ 0.33); IMUCoCo given the AirPods stays flat (ρ −0.02 vs rotation) but grows with
  acceleration (ρ 0.58).
- **Forearm, Watch given:** IMUCoCo grows slowly with swing speed (≈ 7° → 15°, ρ 0.34). MobilePoser
  agrees *better* the farther the arm is from the calibration pose (ρ −0.45).
- **Forearm, Watch held out:** disagreement is largest when the arm is still (≈ 110°) and falls with
  speed (ρ −0.2 to −0.34). Both forearm patterns are what the Watch calibration error predicts:
  near the calibration pose the reference says "arm horizontal" while the models hang the arm.
- **Sample age:** no relation (ρ ≈ 0). Gaps were too rare in this recording to drive errors.

**Relative drift (2026-10-14, `drift.png`; both models zeroed on standing still, 18.2-19.5 s).**
- **Translation (routine done in place, all devices):** MobilePoser drifts 1.08 m by the end of the
  routine (1.6 m/min, steadily toward the subject's left); IMUCoCo ends 0.19 m from the start
  (0.56 m at most, during the squats). By combination, IMUCoCo drifts less whenever the pocket
  phone is present (0.19-0.50 m vs 0.81-1.08 m with Watch and/or AirPods; phone alone 0.22 vs
  0.16 m) and much more without it (Watch alone 2.5 m, AirPods alone 1.1 m, Watch + AirPods 1.2 m).
- **Orientation, read where the device returns to its reference pose:** head drift 9.7°/min
  (MobilePoser) vs 4.5°/min (IMUCoCo), residual 12° vs 2° late in the routine; thigh 7.5 vs
  6.6°/min, residual 9° vs 5°. The Watch never returns within 20° of its calibration pose after
  calibration (see E03 finding 5), so forearm drift cannot be separated from pose error here.
- MobilePoser's forearm residual stays ~39° on average even after offset removal, so its forearm
  disagreement is motion-dependent, not a constant offset.
