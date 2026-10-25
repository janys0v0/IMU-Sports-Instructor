# E05: our IMUs vs commercial IMUs in the same trials

**Question:** how closely do the iPhone, Watch and AirPods streams match commercial IMUs worn in the
same trials?

**Data:** the two 10/19 sessions and the logger exports from the shared Drive folder
`es224/20261019_test_run` (copied to `data/external/20261019_test_run/`, not in git): three
`msense_*` sensors at 200 Hz and the logging phone's own IMU (`phone_internal`, ~118 Hz). The
folder does not say where each sensor was worn, so placement is inferred (below). No OpenCap
results exist yet (only raw phone videos and an `opensim.log` for 10/24), so there is no
ground-truth comparison here.

**Method** (`run.py`):
1. One clock: the logger's local wall-clock time vs our device time + `boot_to_unix`, on a 50 Hz grid.
2. Fine offset per pair from the cross-correlation of rotation speed |ω| (mount-independent), ±5 s.
3. Placement: each commercial sensor is matched to the device of ours it moves most like.
4. Agreement per pair after the fixed rotation between the two sensors' axes (Kabsch on gyro
   vectors): gyro RMSE, per-axis correlation, p99 rotation speed, acceleration magnitude.

```bash
.venv/bin/python -m experiments.E05_commercial_imu.run "data/recordings/field/<session>" data/external/20261019_test_run/<export>_imu.csv
```

## Results (2026-10-25)

| Session (overlap) | Pair | |ω| corr | axis corr | gyro RMSE °/s | p99 °/s ours / theirs | acc mag corr |
|---|---|---|---|---|---|---|
| test-2-tom (209 s) | msense_D0E5 ↔ Watch | 0.95 | 0.88, 0.93, 0.93 | 67 | 708 / 674 | 0.85 |
| | msense_2A33 ↔ iPhone | 0.89 | 0.79, 0.78, 0.76 | 48 | 263 / 261 | 0.63 |
| | msense_1D03 ↔ Watch | 0.85 | 0.52, 0.77, 0.51 | 133 | 708 / 497 | 0.66 |
| | phone_internal ↔ iPhone | 0.75 | 0.52, 0.55, 0.32 | 75 | 263 / 296 | 0.65 |
| test-1-janys (111 s) | msense_D0E5 ↔ Watch | 0.97 | 0.89, 0.95, 0.97 | 79 | 694 / 601 | 0.93 |
| | msense_2A33 ↔ iPhone | 0.63 | 0.14, 0.56, 0.14 | 143 | 391 / 548 | 0.52 |
| | msense_1D03 ↔ Watch | 0.83 | 0.53, 0.70, 0.72 | 175 | 694 / 531 | 0.66 |

- **Watch ≈ msense_D0E5 (same forearm):** r 0.95–0.97, per-axis 0.88–0.97, RMSE ~10 % of peak
  rotation speed. The Watch's 60 Hz stream keeps up with a 200 Hz sensor at up to ~700 °/s.
- **iPhone ≈ msense_2A33 (thigh) in Tom's session** (r 0.89, axis 0.76–0.79); in Janys's session
  the match is weak (0.63, axis 0.14–0.56): that sensor was probably worn elsewhere there.
- **msense_1D03** follows the Watch arm but slower (p99 ~500 vs ~700 °/s): likely the upper arm or
  the other wrist. **AirPods** in Tom's session match nothing: they were Janys's, not worn by Tom.
- The logger clock differed from ours by −0.66 s (Tom) and +0.16 s (Janys); `phone_internal` has
  its own offset (+0.88 s). Each needs its own alignment.

**Limits:** placements are inferred, not recorded; our Watch stream here is the 60 Hz one (the
200 Hz high-rate stream would match the commercial rate); acceleration differs more than rotation
because the sensors sit at different points on the limb.

**Next:** record each sensor's placement; run OpenCap on the 10/24 videos for joint-angle ground truth.
