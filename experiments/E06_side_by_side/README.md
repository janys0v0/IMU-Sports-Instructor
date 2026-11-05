# E06: Apple devices vs commercial IMUs, reconstructed side by side

**Question:** given the same tennis play, how does the full-body reconstruction from the iPhone,
Watch and AirPods compare with one from the commercial IMUs, and with OpenCap (video ground truth)?

**Data (2026-10-28):** our sessions `20261028-104120-P01+…-W(tennis-janys)` and
`20261028-113121-P01(tennis-tom)+…` (both merged with the Watch's own data), and the logger
exports from the shared Drive folder `es224/20261028Janys Tom` in `data/external/20261028/`
(not in git): `IMU1`–`IMU5`, each with 4 msense sensors at ~200 Hz, magnetometer files and
events. OpenCap results (2026-10-29, `aligned_hrnet3/<trial>/opencap_gt.npz`: 20 markers, 14
segment rotations and rotation rates, 59.94 fps, per trial `janys`, `tom`, `tom3`) and the team's
camera overlay videos (`overlay_<trial>.mp4`, phone3 footage with ball tracking and a 3D skeleton
panel) are in `data/external/20261028/aligned_hrnet3/`. Phone1's own clips (`IMG_0032` Janys,
`IMG_0033` Tom, 1080p 59.94 fps, on a stand by the net) are in `data/external/20261028/phone1/`
with 960×540 copies (`avconvert -p Preset960x540`) for rendering. Reported placements (`trial_info.json`):
D0E5 wrist, 2F5A trunk, 1D03 upper arm, 6955 and 01F7 racket butt.

**Method** (`run.py`, `commercial.py`, `sync.py`, `camera.py`, `make_video.py`):
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
   commercial = `msense_D0E5` (worn with the Watch) in the wrist slot + `msense_2F5A` (trunk) in
   the pocket slot. MobilePoser has no trunk input; the trunk stands in for the thigh.
5. **OpenCap on our clock:** its time is seconds into the session's videos; it is placed by
   cross-correlating its right forearm rotation speed with the Watch over the whole session (FFT),
   then checked minute by minute: offset steady within ±0.07 s wherever there is motion.
6. **Phone1 on our clock and OpenCap on phone1:** the clip's sound (ball hits) is matched to the
   commercial logger's timestamped audio (onset envelopes, FFT; peak z 19.6 Janys, 15.5 Tom), then
   shifted by the logger's offset from our clock. Phone1 is not one of OpenCap's two calibrated
   cameras (its view and zoom differ), so `camera.py` fits its 3×4 projection by DLT + RANSAC from
   OpenCap's markers and the player's feet and head top in phone1 frames (moving blob against the
   median frame): one camera for both sessions, median error 7.2 px on 269 of 390 points
   (`results/phone1_camera.json`). The rest are blob mistakes (the net swaying, a second person).
7. **Video:** meshes with the root fixed (posture, not travel); phone1 with OpenCap's skeleton
   projected onto it, cropped to follow the player; rolling 10 s
   charts of rotation speed for every sensor with OpenCap's segment rotation speed in black as the
   reference, swings from the commercial logger and Calibrate holds.

```bash
.venv/bin/python -m experiments.E06_side_by_side.run "data/recordings/field/<session>" data/external/20261028/IMU1/<log>_imu.csv --label janys-IMU1
A=$PWD/data/external/20261028/aligned_hrnet3   # absolute: the script changes directory
P=$PWD/data/external/20261028/phone1
.venv/bin/python -m experiments.E06_side_by_side.camera   # fits phone1 (both sessions), ~3 min
.venv/bin/python -m experiments.E06_side_by_side.make_video janys-IMU1 --opencap-dir $A/janys --phone1 $P/janys_IMG_0032_540.mov [--seconds 20 --start-s 60]
.venv/bin/python -m experiments.E06_side_by_side.make_video tom-IMU4 --opencap-dir $A/tom --phone1 $P/tom_IMG_0033_540.mov
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
- **Against OpenCap (rotation speed, Pearson r over the block):**

  | OpenCap segment vs sensor | Janys | Tom |
  |---|---|---|
  | forearm vs Apple Watch | 0.57 | 0.68 |
  | forearm vs commercial wrist D0E5 | 0.58 | 0.67 |
  | right thigh vs iPhone | 0.46 | 0.49 |
  | right thigh vs commercial 2F5A | 0.43 | 0.37 |
  | trunk vs commercial 2F5A | 0.45 | 0.37 |
  | upper arm vs commercial 1D03 | 0.66 | 0.65 |

  The Watch matches OpenCap as well as the commercial wrist sensor; the iPhone matches its thigh a
  little better than the commercial trunk sensor. OpenCap is the noisier signal of the three (video
  rotation rates reach r ≈ 0.6–0.7 against any sensor, while the two wrist IMUs agree at 0.95–0.98),
  so joint angles, not rotation speed, are the fairer test of the reconstructions.
- **Commercial data quality:** `msense_01F7` (the racket, by its speed and because the logger's swing
  detector runs on it) repeats one gyro reading for up to seconds at a time: 17 % of its samples in
  the Janys block (left blank in the charts). The two sensors used for the reconstruction have
  0.2–0.9 % such samples. One sensor in Tom's log has no magnetometer data.
- **OpenCap follows the wrong person at times:** e.g. Janys trial t ≈ 1400 s its skeleton is on Tom,
  standing next to her; the phone1 panel shows this directly.

**Limits:** placements other than the wrist sensor are inferred from motion; the waist sensor in
the pocket slot is a model mismatch; Tom's pocket setting reads "screen faces leg" (on 10/19 it was
outward), so his thigh heading should be checked against OpenCap; the IMU5 block's wrist sensor
rebooted at 12:00 and its clock jumped 1.9 s, so that block is not used.

**Next:** joint-angle error of each reconstruction against OpenCap's inverse kinematics (`ik`, 33
angles), per stroke; the `tom3` trial (11:47–12:04) once its IMU block is usable.
