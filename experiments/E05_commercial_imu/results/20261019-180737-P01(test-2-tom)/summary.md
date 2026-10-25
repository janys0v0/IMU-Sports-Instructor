# E05: 20261019-180737-P01(test-2-tom) vs generic_20261019T1810_20261019T1818_imu.csv

Overlap 209 s. Rotation-speed correlation of every pair (best lag within ±5 s):

| commercial | iPhone (thigh pocket) | AirPods (head) | Watch (wrist) | best match |
|---|---|---|---|---|
| msense_1D03 | 0.66 | -0.04 | 0.85 | watch |
| msense_2A33 | 0.89 | -0.01 | 0.60 | phone |
| msense_D0E5 | 0.62 | -0.05 | 0.95 | watch |
| phone_internal | 0.75 | 0.03 | 0.54 | phone |

Matched pairs, after the fixed rotation between the two sensors' axes:

| commercial → ours | lag s | gyro RMSE °/s | axis corr | p99 rotation speed °/s (ours / theirs) | acc magnitude corr | acc RMSE m/s² |
|---|---|---|---|---|---|---|
| msense_1D03 → watch | -0.66 | 133.1 | 0.52, 0.77, 0.51 | 708 / 497 | 0.66 | 6.44 |
| msense_2A33 → phone | -0.60 | 47.6 | 0.79, 0.78, 0.76 | 263 / 261 | 0.63 | 2.33 |
| msense_D0E5 → watch | -0.70 | 66.6 | 0.88, 0.93, 0.93 | 708 / 674 | 0.85 | 4.31 |
| phone_internal → phone | +0.88 | 75.0 | 0.52, 0.55, 0.32 | 263 / 296 | 0.65 | 2.13 |
