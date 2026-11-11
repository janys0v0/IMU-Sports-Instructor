# E04 on 20261019-000116-P01

Video `Movie on 10-19-26 at 12.00 AM.mov` (mirrored: True), 2202 frames with a body; alignment offset -0.85 s (Watch/phone agree: True).
IMU minus video, degrees. Left-side angles have no sensor on that limb.

## Watch calibrated in the standing pose

Lag left after alignment (best angle correlation, ±1 s search): {'r_shoulder': 0.06, 'r_elbow': 0.16}. Mirror check (right-shoulder r, same vs other side): {'same_side': 0.13, 'other_side': 0.197}.

| Angle | Frames | Bias | RMSE | MAE | r |
|---|---|---|---|---|---|
| Right elbow flexion (Watch arm) | 1083 | +2.6 | 34.3 | 25.1 | 0.481 |
| Left elbow flexion (no sensor) | 1083 | -4.2 | 36.1 | 27.1 | 0.237 |
| Right knee flexion (phone leg) | 1083 | -5.2 | 19.3 | 13.5 | 0.647 |
| Left knee flexion (no sensor) | 1083 | -4.4 | 19.9 | 13.8 | 0.64 |
| Right shoulder elevation (Watch arm) | 1083 | -8.1 | 27.1 | 18.5 | 0.13 |
| Left shoulder elevation (no sensor) | 1083 | -16.5 | 27.1 | 18.3 | 0.097 |

RMSE per activity (degrees):

| Activity | r_elbow | l_elbow | r_knee | l_knee | r_shoulder | l_shoulder |
|---|---|---|---|---|---|---|
| standing_calibration | 14 | 11 | 14 | 11 | 36 | 32 |
| arms_out_calibration | 32 | 37 | 3 | 4 | 50 | 46 |
| knee_lifts | 28 | 23 | 19 | 17 | 8 | 12 |
| jumping_jacks | 53 | 25 | 26 | 22 | 48 | 64 |
| walking | 18 | 21 | 21 | 20 | 11 | 17 |
| squats | 19 | 16 | 17 | 20 | 7 | 6 |
| ready_position | 43 | 70 | 21 | 24 | 29 | 13 |
| shadow_strokes | 43 | 40 | 17 | 18 | 25 | 23 |

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
