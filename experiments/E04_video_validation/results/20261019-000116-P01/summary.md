# E04 on 20261019-000116-P01

Video `Movie on 10-19-26 at 12.00 AM.mov` (mirrored: True), 2202 frames with a body; alignment offset -0.85 s (Watch/phone agree: True).
IMU minus video, degrees. Left-side angles have no sensor on that limb.

## Watch calibrated in the standing pose

Lag left after alignment (best angle correlation, ±1 s search): {'r_shoulder': -1.0, 'r_elbow': 0.2}. Mirror check (right-shoulder r, same vs other side): {'same_side': -0.312, 'other_side': -0.307}.

| Angle | Frames | Bias | RMSE | MAE | r |
|---|---|---|---|---|---|
| Right elbow flexion (Watch arm) | 1083 | -9.9 | 33.6 | 25.3 | 0.239 |
| Left elbow flexion (no sensor) | 1083 | -15.2 | 34.5 | 25.9 | 0.333 |
| Right knee flexion (phone leg) | 1083 | -1.1 | 19.6 | 14.3 | 0.666 |
| Left knee flexion (no sensor) | 1083 | -3.7 | 18.3 | 12.8 | 0.706 |
| Right shoulder elevation (Watch arm) | 1083 | -13.5 | 29.9 | 20.3 | -0.312 |
| Left shoulder elevation (no sensor) | 1083 | -14.2 | 30.1 | 21.6 | -0.317 |

RMSE per activity (degrees):

| Activity | r_elbow | l_elbow | r_knee | l_knee | r_shoulder | l_shoulder |
|---|---|---|---|---|---|---|
| standing_calibration | 8 | 10 | 15 | 12 | 41 | 44 |
| arms_out_calibration | 9 | 14 | 13 | 12 | 56 | 52 |
| knee_lifts | 21 | 20 | 27 | 15 | 9 | 17 |
| jumping_jacks | 27 | 24 | 21 | 11 | 55 | 59 |
| walking | 21 | 23 | 21 | 21 | 9 | 13 |
| squats | 26 | 17 | 24 | 22 | 9 | 13 |
| ready_position | 60 | 62 | 15 | 16 | 11 | 9 |
| shadow_strokes | 39 | 45 | 14 | 15 | 33 | 31 |

## Watch calibrated in the arms-out pose

Lag left after alignment (best angle correlation, ±1 s search): {'r_shoulder': -0.96, 'r_elbow': -0.94}. Mirror check (right-shoulder r, same vs other side): {'same_side': -0.004, 'other_side': -0.078}.

| Angle | Frames | Bias | RMSE | MAE | r |
|---|---|---|---|---|---|
| Right elbow flexion (Watch arm) | 1083 | +3.1 | 40.8 | 33.5 | -0.079 |
| Left elbow flexion (no sensor) | 1083 | +1.8 | 41.0 | 34.1 | -0.084 |
| Right knee flexion (phone leg) | 1083 | -7.2 | 19.8 | 14.7 | 0.628 |
| Left knee flexion (no sensor) | 1083 | -5.9 | 20.1 | 14.5 | 0.613 |
| Right shoulder elevation (Watch arm) | 1083 | -1.2 | 28.8 | 22.4 | -0.004 |
| Left shoulder elevation (no sensor) | 1083 | -5.4 | 30.1 | 23.1 | -0.035 |

RMSE per activity (degrees):

| Activity | r_elbow | l_elbow | r_knee | l_knee | r_shoulder | l_shoulder |
|---|---|---|---|---|---|---|
| standing_calibration | 26 | 48 | 19 | 15 | 32 | 28 |
| arms_out_calibration | 16 | 12 | 18 | 18 | 13 | 13 |
| knee_lifts | 45 | 41 | 20 | 16 | 13 | 17 |
| jumping_jacks | 18 | 18 | 22 | 24 | 49 | 49 |
| walking | 55 | 45 | 22 | 22 | 13 | 15 |
| squats | 26 | 31 | 21 | 20 | 41 | 47 |
| ready_position | 56 | 46 | 18 | 19 | 26 | 28 |
| shadow_strokes | 41 | 45 | 15 | 16 | 26 | 30 |
