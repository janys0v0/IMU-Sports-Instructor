# E08: Arm models trained on Janys + Tom 10/28, tested on Janys 11/05

**Question:** E07's own models (ridge, bidirectional GRU) reached elbow 10° and shoulder elevation
8° in swings when trained with the player's own minutes, but those minutes came from the same
session. Trained on 10/28, how do they do on Janys's 11/05 session? And how do E07's other
methods (frame-based geometry, constraints, OpenSense, published models) do on Janys 11/05?

**Data:**
- **Training:** E07's Apple-only `dataset_full` for 10/28: every Calibrate segment OpenCap covers.
  That is Janys 26.8 min and Tom 12.0 min.
- **Test:** Janys on 11/05, session `20261105-124805-P01` (iPhone in the right pocket, Watch on
  the right wrist, AirPods).
  - 35.8 min with OpenCap, in 97 segments of about 25 s, with 278 swings.
  - Ground truth: jtchen's 3-camera HRNet OpenCap reconstruction (Drive folder
    `es224/20261105 Janys/opencap`), copied to `data/external/20261105/opencap_jtchen`.

**Method:**
1. `opencap_gt.py` (OpenSim env) poses the scaled model with each segment's filtered IK. It writes
   body rotations, positions and rotation rates in the same layout as 10/28's `opencap_gt.npz`,
   one file per recording (r1245, r1309, r1334).
2. `align.py` puts each recording on the unix clock by matching OpenCap's forearm rotation speed
   to the Watch's, as was done for 10/28.
   - The match is unambiguous: peaks 0.20–0.35 against at most 0.08 elsewhere.
   - Segment-by-segment checks agree within one or two frames, with no drift.
3. `data.py` builds the 11/05 test set with E07's own helpers, so inputs and targets are computed
   exactly as on 10/28.
4. `run.py` trains E07's models, unchanged, on four training sets and tests them on 11/05:
   - Janys 10/28;
   - Janys + Tom 10/28;
   - Tom 10/28 (another player and another date);
   - Janys + Tom 10/28 plus the other half of 11/05 (two folds in time, 10 s gap).
5. `frame_methods.py` runs every E07 method that needs only the Apple devices, called exactly as in
   E07. Each OpenCap segment uses the latest Calibrate hold before it (six holds, every 8–10 min).
   - Frame-based: Watch orientation with a fixed trunk, or with the AirPods as trunk.
   - Joint-limit constraints, plain and swing-aware.
   - OpenSense IK with Watch + phone (`opensense_run.py`, OpenSim env).
   - WearMoCap, MobilePoser and IMUCoCo.
   Methods built on the commercial chest and upper-arm sensors can't run: those weren't worn.
6. `evaluate.py` scores every saved method with E07's `score`.
7. **Video** (`camera.py`, `video.py`): the IMG_0021 clip (iPhone behind Janys, 70 min, 60 fps,
   from the Drive folder) next to one arm panel per method and rolling curves, as in E07.
   - jtchen's calibration of this phone wasn't shared, so the clip is synced and its projection
     fitted from the footage itself. Apple Vision 2D keypoints (`vision2d.swift`, first 20 min at
     10 Hz) are matched to OpenCap's markers.
   - Offset: right-wrist speed correlation, peak 0.144 vs at most 0.074 elsewhere. It agrees with
     the clip's recorded start (12:47:14) to under a second.
   - Projection: normalized DLT with RANSAC, median reprojection error 8 px; it holds across all
     three recordings.
   - The clip is stored rotated 180°. Vision has to be told, or the keypoints come out upside down.

## Results

### Every method on 11/05

Janys, swings, median error in degrees; in brackets, the same method on Janys's 10/28 data (E07;
for our models, E07's model of that kind, trained with Janys's own 10/28 minutes). Figures: `figures/methods_swing.png`,
`figures/methods_all.png`.

| Method | Elbow | Elevation | Forearm incl. | Forearm dir. |
|---|---|---|---|---|
| Watch orientation, trunk fixed | – | – | 24 (15) | 65 (44) |
| Watch orientation, AirPods as trunk | – | – | 26 (15) | 69 (46) |
| OpenSense IK, Watch+phone | 29 (27) | 39 (53) | 32 (34) | 62 (70) |
| Joint limits + effort, Watch only | 34 (38) | 47 (55) | 24 (15) | 65 (44) |
| Joint limits, swing-aware, Watch only | 34 (38) | 41 (49) | 24 (15) | 65 (44) |
| WearMoCap (pretrained), Watch | 35 (28) | 26 (23) | 23 (13) | 58 (38) |
| WearMoCap (pretrained), Watch+phone | 34 (28) | 23 (21) | 23 (14) | 70 (52) |
| MobilePoser, Watch+phone+AirPods | 25 (33) | 48 (62) | 36 (23) | 73 (40) |
| MobilePoser, Watch+phone | 24 (33) | 48 (63) | 37 (22) | 76 (39) |
| IMUCoCo, Watch+phone+AirPods | 25 (25) | 32 (22) | 16 (11) | 66 (28) |
| Ridge, Watch+phone (Janys + Tom 10/28) | 17 (16) | 14 (15) | 14 (8) | 29 (18) |
| GRU, Watch (Tom 10/28 only) | 24 (22) | 35 (35) | 15 (12) | 33 (26) |
| GRU, Watch (Janys 10/28) | 14 (10) | 11 (9) | 10 (7) | 23 (13) |
| GRU, Watch (Janys + Tom 10/28) | 13 (10) | 10 (9) | 10 (7) | 21 (13) |
| GRU, Watch (+ half of 11/05) | 12 (10) | 8 (9) | 8 (7) | 17 (13) |

- **Our GRU trained on Janys 10/28 is the best method on Janys 11/05 that uses no 11/05 data.**
  It beats every method that needs no training by 10–20° on elbow and elevation in swings.
- **Most methods without training get worse on 11/05, including on forearm inclination,** which
  needs no heading. Watch with fixed trunk: 24° vs 15°. Two causes, both measured:
  - **The 11/05 ground truth is noisier.** Compared in OpenCap's own ground frame, Watch and
    OpenCap forearm tilt agree to 4° on 10/28 but 7° on 11/05 (swings: 6° vs 10°, r 0.94 vs
    0.86). A few segments are off by 20–70° (b_s000, c_s005, c_s020, ...).
  - **Janys's trunk leaned slightly more on 11/05** (median 21° from vertical vs 19°). The
    frame-based methods assume an upright trunk; the trained models learned typical lean.
  - A clock error is ruled out: shifting the Watch by ±100 ms doesn't change the swing error.
- **Heading is still the weak point.** Forearm direction is 58–76° off for every method without
  training (38–70° on 10/28).
- **Shoulder elevation:** OpenSense, constraints and MobilePoser are slightly better on 11/05 than
  on 10/28 but still 39–48° off in swings. WearMoCap (23–26°) and IMUCoCo (32°) are about as
  before.

Four methods side by side, all Watch + phone (`figures/four_methods.png`, `four_methods.py`):
MobilePoser and OpenSense IK need no training; ridge and GRU are trained on Janys + Tom 10/28.
Swings, elbow / elevation / forearm direction: MobilePoser 24 / 48 / 76, OpenSense 29 / 39 / 62,
ridge 17 / 14 / 29, GRU 15 / 11 / 22.
Elbow / wrist position, swings (cm, shoulder-anchored): MobilePoser 29 / 47, OpenSense 32 / 47,
ridge 11 / 17, GRU 8 / 12; all minutes: 14 / 28, 24 / 35, 6 / 11, 5 / 8. For scale, the papers
report WearMoCap 2.6 cm (wrist and elbow, IROS 2023; ~10 cm Watch-only, 2025) and MobilePoser
11.9 cm (mean joint error, whole body) on their own data.

### Trained models by training set

Janys, swings, median error in degrees. Full table: `results/summary.md`.

| Model | Trained on | Elbow | Elevation | Forearm dir. |
|---|---|---|---|---|
| GRU, Watch | Janys 10/28, tested on Janys 10/28 (E07) | 10 | 9 | 13 |
| GRU, Watch | Janys 10/28 → Janys 11/05 | 14 | 11 | 23 |
| GRU, Watch | Janys + Tom 10/28 → Janys 11/05 | 13 | 10 | 21 |
| GRU, Watch | Tom 10/28 → Janys 11/05 | 24 | 35 | 33 |
| GRU, Watch | Janys + Tom 10/28 + half of Janys 11/05 | 12 | 8 | 17 |
| Ridge, Watch+phone | Janys 10/28, tested on Janys 10/28 (E07) | 16 | 15 | 18 |
| Ridge, Watch+phone | Janys + Tom 10/28 → Janys 11/05 | 17 | 14 | 29 |

- **From Janys 10/28 to Janys 11/05 costs a few degrees, not the model.**
  - The Watch-only GRU goes from 10° to 14° on the elbow and from 9° to 11° on elevation.
  - Over all minutes, not just swings, it is elbow 9° and elevation 6°.
  - Ridge barely changes on the angles. Forearm direction suffers more: it is the one target that
    depends on how the trunk is oriented relative to the arm.
- **Training on another player is still the problem.** Trained on Tom 10/28 alone, every model is 23–27° off on the
  elbow and 31–44° on elevation in Janys's swings. That's the same as E07's cross-player result.
- **Half of Janys 11/05 in training closes most of the gap:** GRU elbow 12°, elevation 8°. That
  is back at the Janys 10/28 level.
- **The phone and AirPods add nothing on Janys 11/05**, as in E07; the Watch carries the arm.
- **No drift over the 67 min session.** Error per segment stays flat (`figures/error_over_session.png`).
- **The error spikes are probably ground-truth errors.** All models jump together on five
  segments (a_s012, b_s040, b_s041, c_s000, c_s005). jtchen's README says OpenCap first tracked
  another person on b_s040 and c_s000. They are kept in the scores, as on 10/28.

### Cross-session tests on 10/28 (`cross.py`)

Each model is trained on some sessions and tested on a whole 10/28 session it never saw: Tom 10/28
(8.9 min with OpenCap) or Janys 10/28 (17.0 min). Watch-only, swings, median error in degrees.
Every variant: `results/cross.md`; figures `figures/cross_swing.png`, `figures/cross_all.png`.

| Tested on | Trained on | GRU elbow | GRU elev. | GRU forearm dir. | Ridge elbow | Ridge elev. |
|---|---|---|---|---|---|---|
| Tom 10/28 | Janys 10/28 | 27 | 26 | 31 | 18 | 24 |
| Tom 10/28 | Janys 10/28 + Janys 11/05 | **19** | **20** | 27 | 15 | 20 |
| Janys 10/28 | Tom 10/28 | 25 | 38 | 27 | 27 | 38 |
| Janys 10/28 | Janys 11/05 | **10** | **9** | 19 | 20 | 20 |
| Janys 10/28 | Janys 11/05 + Tom 10/28 | 10 | 9 | 19 | 22 | 22 |

- **A second day of Janys helps on a new player.** On Tom, the Watch GRU goes from elbow 27° and
  elevation 26° to 19° and 20°. Forearm direction barely changes (31° to 27°).
- **Janys's other day is as good as her same-day minutes.** Trained on Janys 11/05 only, the GRU
  reaches elbow 10° and elevation 9° on Janys 10/28: E07's same-session personal result.
- **Adding Tom to Janys 11/05 changes nothing on Janys** (10° / 9°).
- The phone and AirPods add nothing consistent: the GRU elbow is 6° better to 5° worse with them.
- Caveat: Tom's swing scores are unstable. After fixing the GRU's dropout at test time (11/10) and
  retraining, they moved by up to 6°; Janys's moved by 1° or less. Read differences under ~5° on
  Tom as noise.

**Limits:**
- One test player and date: Janys 11/05.
- The 11/05 OpenCap differs from 10/28's: 3 cameras instead of 2, 30 fps instead of 60, and
  segments of about 25 s. Some of the gap may come from that change rather than the day.
- The "half of 11/05" split is within one session, like E07's personal split.
- No commercial upper-arm or chest sensors on 11/05 (one msense, 2DA6), so E07's all-sensor and
  chest + upper-arm geometric methods (its best model-free result) can't be tested here.
- OpenSense uses Janys's 10/28 scaled model (as in E07), not the 11/05 one.

```bash
~/micromamba-envs/opensim/bin/python experiments/E08_janys_1105/opencap_gt.py   # OpenCap -> body rotations
.venv/bin/python -m experiments.E08_janys_1105.align                            # clip -> unix per recording
.venv/bin/python -m experiments.E08_janys_1105.data                             # results/janys/dataset.npz
.venv/bin/python -m experiments.E08_janys_1105.run ridge gru                    # results/scores.json (~1 h, CPU)
.venv/bin/python -m experiments.E08_janys_1105.frame_methods                    # E07's other methods (~30 min)
.venv/bin/python -m experiments.E08_janys_1105.evaluate                         # results/scores_all.json
.venv/bin/python -m experiments.E08_janys_1105.figures
.venv/bin/python -m experiments.E08_janys_1105.cross ridge gru                  # results/cross.json (~1 h, CPU)
.venv/bin/python -m experiments.E08_janys_1105.cross figures                    # results/cross.md, figures/cross_*.png
.venv/bin/python -m experiments.E08_janys_1105.four_methods                     # figures/four_methods.png
swift experiments/E08_janys_1105/vision2d.swift data/external/20261105/cameras/IMG_0021.MOV \
    data/external/20261105/cameras/IMG_0021_vision_0-1200.json --stride 6 --start 0 --seconds 1200
.venv/bin/python -m experiments.E08_janys_1105.camera                        # results/camera.json
avconvert -s data/external/20261105/cameras/IMG_0021.MOV -o data/external/20261105/cameras/IMG_0021_540.mov -p Preset960x540
.venv/bin/python -m experiments.E08_janys_1105.video [--start S --seconds N] # results/janys/videos/ (not committed)
```
