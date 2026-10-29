# E06: Apple devices vs commercial IMUs, reconstructed side by side

**Question:** given the same tennis play, how does the full-body reconstruction from the iPhone,
Watch and AirPods compare with one from the commercial IMUs? A third panel is reserved for
OpenCap (ground truth from the two phone videos) once it is processed.

**Data (2026-10-28):** our sessions `20261028-104120-P01+…-W(tennis-janys)` and
`20261028-113121-P01(tennis-tom)+…` (both merged with the Watch's own data), and the logger
exports from the shared Drive folder `es224/20261028Janys Tom` in `data/external/20261028/`
(not in git): `IMU1`–`IMU5`, each with 4 msense sensors at ~200 Hz, magnetometer files and
events. The OpenCap zip there has only Janys's neutral (calibration) trial; the tennis videos
(`phone1`, `phone2`, `phone3`, `action_cam`) have not been through OpenCap yet.

**Method** (`run.py`, `commercial.py`, `make_video.py`):
1. **Commercial orientation:** Madgwick filter (gyro + gravity) per sensor, restarted at each
   Calibrate hold with the gyro bias measured there. The magnetometer's axes are the gyro's
   (y, x, −z); after a hard-iron correction it sets one constant heading turn to magnetic north
   from the 30 s after the hold (the same frame as the Apple devices). It is not used beyond that:
   the field near the court is disturbed and the log drops field samples.
2. **Clock:** the logger's time is shifted onto ours by cross-correlating rotation speed of the
   wrist sensor against the Watch (both blocks: logger +0.36 s, r 0.98 Janys, 0.95 Tom).
3. **Same calibration for both:** the app's Calibrate holds inside the commercial block, and the
   body heading from the phone's calibration (the person facing the landmark).
4. **Inputs:** Apple = iPhone (right pocket) + Watch (right wrist) [+ AirPods for Janys];
   commercial = `msense_D0E5` (worn with the Watch) in the wrist slot + `msense_2F5A` (waist) in
   the pocket slot. MobilePoser has no pelvis input; the waist stands in for the thigh.
5. **Video:** meshes with the root fixed (posture, not travel), OpenCap slot, and rolling 10 s
   charts of rotation speed for every sensor, swings from the commercial logger and Calibrate holds.

```bash
.venv/bin/python -m experiments.E06_side_by_side.run "data/recordings/field/<session>" data/external/20261028/IMU1/<log>_imu.csv --label janys-IMU1
.venv/bin/python -m experiments.E06_side_by_side.make_video janys-IMU1 [--seconds 40] [--opencap opencap.mp4]
```

## Results (2026-10-28)

| Block | Time | Inputs (Apple / commercial) | Wrist rotation speed match |
|---|---|---|---|
| `janys-IMU1` | 11:02:00–11:10:10 (8.1 min, 2 segments) | `rw_rp_h` / `rw_rp` | r 0.98 |
| `tom-IMU4` | 11:33:42–11:46:22 (12.6 min, 2 segments) | `rw_rp` / `rw_rp` | r 0.95 |

Median angle between the two reconstructions, per joint (local rotation):

| | root | hips | knees | spine | neck | head | shoulders | elbows |
|---|---|---|---|---|---|---|---|---|
| Janys | 38° | 11–15° | 16° | 10° | 13° | 16° | 17° | 29° |
| Tom | 24° | 11–12° | 13° | 9° | 14° | 13° | 20–21° | 42–47° |

- The legs, spine and head agree within ~10–16°; the elbows differ most (29–47°): one wrist sensor
  does not fix how the arm is bent, so each system's model guesses differently. The root differs by
  24–38° because the commercial pocket input is really at the pelvis.
- **Which one is right is open until OpenCap:** these are differences, not errors.
- **Commercial data quality:** `msense_01F7` (the racket, by its speed and because the logger's swing
  detector runs on it) repeats one gyro reading for up to seconds at a time: 17 % of its samples in
  the Janys block (left blank in the charts). The two sensors used for the reconstruction have
  0.2–0.9 % such samples. One sensor in Tom's log has no magnetometer data.

**Limits:** placements other than the wrist sensor are inferred from motion; the waist sensor in
the pocket slot is a model mismatch; Tom's pocket setting reads "screen faces leg" (on 10/19 it was
outward), so his thigh heading should be checked once OpenCap is in; the IMU5 block's wrist sensor
rebooted at 12:00 and its clock jumped 1.9 s, so that block is not used.

**Next:** run OpenCap on the phone1 + phone2 tennis videos, render its result in time, and pass it
with `--opencap` to fill the third panel; then measure each system's joint-angle error against it.
