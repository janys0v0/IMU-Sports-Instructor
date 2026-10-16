# E01: MobilePoser device ablation

**Question.** How much does each consumer device (pocket phone, Watch, AirPods) contribute to
MobilePoser's reconstruction? In particular: what do the AirPods add beyond the Watch, and what
does the pocket phone (the only sensor near the pelvis/legs) add? (Research notes, "Proposed
evaluation", configurations 1-4.)

**Method.**
- Session: the reference routine `20261008-153213-P01` (phone right pocket, Watch right wrist,
  AirPods; slow jumping jacks, tennis swings, squats, look left/right). Labels:
  `../annotations/20261008-153213-P01.json`.
- Calibrate once with all devices (`common/session.py`, same as the live viewer), then run
  MobilePoser offline on every non-empty subset of {right_wrist, right_pocket, head}: 7 runs.
  Devices left out get zero input, MobilePoser's own masking.
- **MobilePoser was trained only on combinations that include a pocket phone**
  (`mobileposer/config.py`, `amass.combos`). `rw_h`, `rw` and `h` are outside its training and
  are reported but flagged "untrained".
- Metrics (`common/metrics.py`): bone-vs-sensor orientation error for every sensor-bearing bone,
  repetition counts, peak wrist height (jumping jacks), peak knee flexion (squats), head yaw vs
  AirPods (head turns).

**Run.** From the repo root: `.venv/bin/python -m experiments.E01_mobileposer_device_ablation.run [SESSION] [--no-video]`
(about 1 minute; the video adds about 1.5 minutes).

**Outputs** in `results/<session>/`: `metrics.json`, `summary.md`, `signals.png` (wrist
height, knee flexion, head yaw for every configuration), `orientation_error.png`,
`videos/<combo>.mp4` and `videos/comparison.mp4` (the four trained combinations side by side).

## Results: 20261008-153213-P01 (2026-10-08)

Full tables: [`results/20261008-153213-P01/summary.md`](results/20261008-153213-P01/summary.md).

| Devices | Trained | Forearm err | Thigh err | Head err | JJ reps (3) | JJ wrist peak | Squats (3) | Knee peak | Head yaw RMSE |
|---|---|---|---|---|---|---|---|---|---|
| `rw_rp_h` all | yes | 45° | 21° | 17° | 3 | 0.82 m | 3 | 112° | 22° |
| `rw_rp` | yes | 51° | 15° | 26° | 4 | 0.69 m | 3 | 100° | 24° |
| `rp_h` | yes | 88° | 15° | 24° | 1 | 0.43 m | 3 | 108° | 22° |
| `rp` | yes | 94° | 14° | 29° | 0 | n/a | 3 | 101° | 44° |
| `rw_h` | no | 44° | 26° | 17° | 3 | 0.86 m | 3 | 117° | 31° |
| `rw` | no | 42° | 28° | 31° | 4 | 0.70 m | 2 | 82° | 55° |
| `h` | no | 96° | 26° | 22° | 1 | 0.40 m | 3 | 116° | 14° |

**Findings.**
1. **The Watch is what makes the arm move.** Without it the forearm error roughly doubles
   (≈45° → ≈90°) and jumping jacks disappear (0-1 of 3 detected, wrist peak ≤ 0.43 m).
2. **Squats are robust.** Every configuration except Watch-only finds all 3 squats; even
   AirPods-only does (the head drops). Squat depth varies 100-117° across configurations.
3. **The AirPods mainly fix the head and heading.** Adding them to phone + Watch lowers the head
   error 26° → 17°. Head-turn tracking is still under-turned to the right (model −16° vs
   AirPods −72°) whenever the Watch is included; AirPods-only tracks yaw best (RMSE 14°).
4. **Untrained combinations still produce plausible output** (`rw_h` is close to the full set),
   but `rw` alone loses the legs (2 squats, 82°) and the head (RMSE 55°).
5. **The Watch calibration raises the arms at rest (explained by E02).** The forearm error
   never drops below ~42°, even with the Watch, while the thigh and head reach 5-7° standing.
   Standing still right after calibration (18.2-19.5 s), both wrists sit at +0.29 m above the
   pelvis with the Watch and −0.09 m without it (hanging arms ≈ −0.05 m). Calibration treats every bone as
   identity while standing; for the forearm, identity is the SMPL T-pose (arm horizontal), so the
   Watch tells the model the arm is out to the side. MobilePoser's prior pulls it partway back
   (and lifts both arms symmetrically). E02 shows IMUCoCo, which follows its inputs closely,
   holding the right arm out at +0.48 m. The 45° "error" here is therefore mostly MobilePoser
   *disagreeing with a wrong input*, not tracking badly. Fix candidates: calibrate the Watch in a
   T-pose, or apply the hanging-arm rest rotation to the Watch (follow-up experiment).
   (An earlier check of the rest rotation scored it against MobilePoser's output, which the same
   input had already distorted, so it was inconclusive.)
