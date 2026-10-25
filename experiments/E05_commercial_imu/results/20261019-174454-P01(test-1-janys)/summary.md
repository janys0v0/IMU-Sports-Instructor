# E05: 20261019-174454-P01(test-1-janys) vs generic_20261019T1751_20261019T1753_imu.csv

Overlap 111 s. Rotation-speed correlation of every pair (best lag within ±5 s):

| commercial | iPhone (thigh pocket) | AirPods (head) | Watch (wrist) | best match |
|---|---|---|---|---|
| msense_1D03 | 0.56 | 0.51 | 0.83 | watch |
| msense_2A33 | 0.63 | 0.40 | 0.55 | phone |
| msense_D0E5 | 0.56 | 0.48 | 0.97 | watch |

Matched pairs, after the fixed rotation between the two sensors' axes:

| commercial → ours | lag s | gyro RMSE °/s | axis corr | p99 rotation speed °/s (ours / theirs) | acc magnitude corr | acc RMSE m/s² |
|---|---|---|---|---|---|---|
| msense_1D03 → watch | +0.16 | 175.4 | 0.53, 0.70, 0.72 | 694 / 531 | 0.66 | 7.17 |
| msense_2A33 → phone | +0.26 | 142.5 | 0.14, 0.56, 0.14 | 391 / 548 | 0.52 | 4.5 |
| msense_D0E5 → watch | +0.16 | 78.7 | 0.89, 0.95, 0.97 | 694 / 601 | 0.93 | 3.18 |
