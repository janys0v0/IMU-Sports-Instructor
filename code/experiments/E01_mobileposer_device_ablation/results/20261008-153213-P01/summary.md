# E01 results: 20261008-153213-P01

Model: MobilePoser (pretrained weights, offline). Calibration done once with all devices.
Orientation error: angle between the model's bone and the sensor on it, over the whole session.

| Devices given to the model | Trained combo | head bone err (deg) | right_pocket bone err (deg) | right_wrist bone err (deg) |
|---|---|---|---|---|
| `rw_rp_h` | yes | 17.3 | 21.1 | 45.3 |
| `rp_h` | yes | 23.7 | 15.1 | 88.1 |
| `rw_h` | **no** | 17.3 | 26.1 | 44.2 |
| `rw_rp` | yes | 26.1 | 15.3 | 50.8 |
| `h` | **no** | 22.4 | 26.3 | 96.4 |
| `rp` | yes | 28.7 | 13.9 | 93.6 |
| `rw` | **no** | 31.4 | 27.5 | 42.2 |

## Activities

| Devices | Rest wrist R / L (m, hanging = -0.05) | JJ reps | JJ wrist peak (m) | Squat reps | Squat knee peak (deg) | Look L model/AirPods | Look R model/AirPods | Head yaw RMSE (deg) |
|---|---|---|---|---|---|---|---|---|
| `rw_rp_h` | 0.29 / 0.29 | 3 / 3 | 0.82 | 3 / 3 | 112.2 | 42.2 / 49.1 | -16.3 / -71.7 | 22.2 |
| `rp_h` | -0.09 / -0.09 | 1 / 3 | 0.43 | 3 / 3 | 108.4 | 7.6 / 49.1 | -45.7 / -71.7 | 21.9 |
| `rw_h` | 0.31 / 0.3 | 3 / 3 | 0.86 | 3 / 3 | 117.1 | 34.1 / 49.1 | 2.9 / -71.7 | 31.4 |
| `rw_rp` | 0.32 / 0.33 | 4 / 3 | 0.69 | 3 / 3 | 100.4 | 26.3 / 49.1 | -17.9 / -71.7 | 23.7 |
| `h` | -0.1 / -0.09 | 1 / 3 | 0.4 | 3 / 3 | 116.0 | 36.8 / 49.1 | -48.9 / -71.7 | 14.4 |
| `rp` | -0.04 / -0.04 | 0 / 3 | None | 3 / 3 | 100.6 | -21.7 / 49.1 | -56.8 / -71.7 | 44.4 |
| `rw` | 0.39 / 0.37 | 4 / 3 | 0.7 | 2 / 3 | 81.9 | 16.6 / 49.1 | -132.5 / -71.7 | 54.6 |
