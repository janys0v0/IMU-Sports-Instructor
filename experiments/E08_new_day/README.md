# E08: Do models trained on one day work on another day?

**Question:** E07's own models (ridge, bidirectional GRU) reached elbow 10° and shoulder elevation
8° in swings when trained with the player's own minutes, but those minutes came from the same
session. Trained on 10/28, how do they do on Janys's 11/05 session?

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
   - Tom 10/28 (a new player as well as a new day);
   - Janys + Tom 10/28 plus the other half of 11/05 (two folds in time, 10 s gap).

## Results

Janys, swings, median error in degrees. Full table: `results/summary.md`; figures in `figures/`.

| Model | Trained on | Elbow | Elevation | Forearm dir. |
|---|---|---|---|---|
| GRU, Watch | 10/28 same day (E07) | 10 | 8 | 13 |
| GRU, Watch | Janys 10/28 → 11/05 | 14 | 10 | 22 |
| GRU, Watch | Janys + Tom 10/28 → 11/05 | 14 | 10 | 22 |
| GRU, Watch | Tom 10/28 → 11/05 | 24 | 34 | 35 |
| GRU, Watch | Janys + Tom 10/28 + half of 11/05 | 11 | 8 | 17 |
| Ridge, Watch+phone | 10/28 same day (E07) | 16 | 15 | 18 |
| Ridge, Watch+phone | Janys + Tom 10/28 → 11/05 | 17 | 14 | 29 |

- **A new day for the same player costs a few degrees, not the model.**
  - The Watch-only GRU goes from 10° to 14° on the elbow and from 8° to 10° on elevation.
  - Over all minutes, not just swings, it is elbow 9° and elevation 6°.
  - Ridge barely changes on the angles. Forearm direction suffers more: it is the one target that
    depends on how the trunk is oriented relative to the arm.
- **A new player is still the problem.** Trained on Tom alone, every model is 23–27° off on the
  elbow and 31–44° on elevation in Janys's swings. That's the same as E07's cross-player result.
- **Half a session from the test day closes most of the gap:** GRU elbow 11°, elevation 8°. That
  is back at the same-day level.
- **The phone and AirPods add nothing on a new day**, as in E07; the Watch carries the arm.
- **No drift over the 67 min session.** Error per segment stays flat (`figures/error_over_session.png`).
- **The error spikes are probably ground-truth errors.** All models jump together on five
  segments (a_s012, b_s040, b_s041, c_s000, c_s005). jtchen's README says OpenCap first tracked
  another person on b_s040 and c_s000. They are kept in the scores, as on 10/28.

**Limits:**
- One player (Janys), one new day.
- The 11/05 OpenCap differs from 10/28's: 3 cameras instead of 2, 30 fps instead of 60, and
  segments of about 25 s. Some of the gap may come from that change rather than the day.
- The "half of 11/05" split is within one session, like E07's personal split.
- No commercial upper-arm or chest sensors on 11/05 (one msense, 2DA6), so E07's all-sensor and
  geometric methods can't be tested here.

```bash
~/micromamba-envs/opensim/bin/python experiments/E08_new_day/opencap_gt.py   # OpenCap -> body rotations
.venv/bin/python -m experiments.E08_new_day.align                            # clip -> unix per recording
.venv/bin/python -m experiments.E08_new_day.data                             # results/janys/dataset.npz
.venv/bin/python -m experiments.E08_new_day.run ridge gru                    # results/scores.json (~1 h, CPU)
.venv/bin/python -m experiments.E08_new_day.figures
```
