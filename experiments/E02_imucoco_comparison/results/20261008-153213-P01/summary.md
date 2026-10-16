# E02 results: 20261008-153213-P01

Same calibrated inputs for both models. Bone error: model bone vs the sensor on it (deg, mean).
MobilePoser 'trained' = the device combination is one MobilePoser was trained on.

## Bone orientation vs sensors

| Devices | MP trained | head: MP / CoCo | right_pocket: MP / CoCo | right_wrist: MP / CoCo |
|---|---|---|---|---|
| `rw_rp_h` | yes | 17.3 / 5.1 | 21.1 / 12.6 | 45.3 / 9.2 |
| `rp_h` | yes | 23.7 / 4.6 | 15.1 / 12.5 | 88.1 / 93.1 |
| `rw_h` | no | 17.3 / 5.0 | 26.1 / 24.6 | 44.2 / 9.2 |
| `rw_rp` | yes | 26.1 / 20.6 | 15.3 / 11.5 | 50.8 / 9.8 |
| `h` | no | 22.4 / 4.5 | 26.3 / 24.4 | 96.4 / 92.8 |
| `rp` | yes | 28.7 / 20.6 | 13.9 / 11.4 | 93.6 / 93.2 |
| `rw` | no | 31.4 / 36.2 | 27.5 / 50.5 | 42.2 / 9.3 |

## Activities (MobilePoser / IMUCoCo)

| Devices | Rest right wrist (m, hanging = -0.05) | Rest left wrist (m) | JJ reps (of 3) | JJ right wrist peak (m) | JJ left wrist at peak (m) | Squat reps (of 3) | Squat knee peak (deg) | Look L (AirPods 49) | Look R (AirPods -72) | Head yaw RMSE (deg) |
|---|---|---|---|---|---|---|---|---|---|---|
| `rw_rp_h` | 0.29 / 0.48 | 0.29 / -0.02 | 3 / 4 | 0.82 / 0.79 | 0.81 / -0.05 | 3 / 3 | 112.2 / 102.3 | 42.2 / 49.0 | -16.3 / -77.4 | 22.2 / 4.1 |
| `rp_h` | -0.09 / 0.01 | -0.09 / 0.0 | 1 / 0 | 0.43 / None | 0.34 / None | 3 / 3 | 108.4 / 105.0 | 7.6 / 49.1 | -45.7 / -76.5 | 21.9 / 3.8 |
| `rw_h` | 0.31 / 0.48 | 0.3 / -0.02 | 3 / 4 | 0.86 / 0.79 | 0.86 / -0.05 | 3 / 3 | 117.1 / 72.0 | 34.1 / 47.3 | 2.9 / -73.9 | 31.4 / 3.9 |
| `rw_rp` | 0.32 / 0.48 | 0.33 / -0.01 | 4 / 4 | 0.69 / 0.79 | 0.69 / -0.05 | 3 / 3 | 100.4 / 96.8 | 26.3 / 8.8 | -17.9 / -6.5 | 23.7 / 33.5 |
| `h` | -0.1 / 0.02 | -0.09 / 0.0 | 1 / 0 | 0.4 / None | 0.41 / None | 3 / 2 | 116.0 / 75.1 | 36.8 / 47.6 | -48.9 / -74.8 | 14.4 / 3.6 |
| `rp` | -0.04 / 0.02 | -0.04 / 0.0 | 0 / 0 | None / None | None / None | 3 / 3 | 100.6 / 100.0 | -21.7 / 10.6 | -56.8 / -4.3 | 44.4 / 34.1 |
| `rw` | 0.39 / 0.46 | 0.37 / 0.3 | 4 / 4 | 0.7 / 0.8 | 0.71 / 0.4 | 2 / 0 | 81.9 / None | 16.6 / 84.8 | -132.5 / 47.0 | 54.6 / 78.3 |
