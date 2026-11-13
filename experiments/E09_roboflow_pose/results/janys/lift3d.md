# E09 janys: right arm in 3D, E07/E08 metrics, Roboflow vs IMU methods

600 frames (20 s window); medians against OpenCap (E07's `score`). Front/back ambiguous (ray meets the sphere twice) for the elbow or wrist in 99% of frames.

## Swings

| Method | Elbow ° | Shoulder elev. ° | Forearm incl. ° | Upper-arm dir. ° | Forearm dir. ° | Elbow cm | Wrist cm |
|---|---|---|---|---|---|---|---|
| OpenCap's own 3D keypoints (floor) | 8 | 7 | 6 | 10 | 14 | 4 | 7 |
| OpenCap's pixels lifted, smooth path (lifting ceiling) | 19 | 11 | 8 | 23 | 27 | 10 | 17 |
| OpenCap's pixels lifted, best pick | 11 | 8 | 6 | 13 | 15 | 6 | 9 |
| Roboflow lifted to 3D (smooth path) | 38 | 30 | 16 | 56 | 76 | 23 | 32 |
| Roboflow lifted, best front/back pick (upper bound) | 30 | 26 | 16 | 37 | 39 | 16 | 20 |
| Geometric, qmt heading, rest 18° (chest+upper arm+Watch) | 14 | 24 | 23 | 92 | 62 | 36 | 57 |
| OpenSense IK, 4 sensors | 30 | 18 | 21 | 88 | 74 | 34 | 58 |
| Constraints, Watch only | 40 | 53 | 19 | 82 | 33 | 33 | 37 |
| WearMoCap, Watch | 31 | 24 | 16 | 42 | 45 | 18 | 31 |
| MobilePoser, Watch+phone+AirPods | 35 | 67 | 22 | 92 | 37 | 36 | 40 |
| IMUCoCo, Watch+phone+AirPods | 18 | 25 | 11 | 41 | 28 | 17 | 22 |
| Ours GRU, Watch, other player only | 28 | 39 | 12 | 47 | 26 | 20 | 22 |
| Ours GRU, all sensors, + own half of the block | 10 | 9 | 9 | 17 | 14 | 7 | 10 |

## Whole window

| Method | Elbow ° | Shoulder elev. ° | Forearm incl. ° | Upper-arm dir. ° | Forearm dir. ° | Elbow cm | Wrist cm |
|---|---|---|---|---|---|---|---|
| OpenCap's own 3D keypoints (floor) | 10 | 3 | 7 | 6 | 13 | 3 | 7 |
| OpenCap's pixels lifted, smooth path (lifting ceiling) | 12 | 8 | 9 | 12 | 17 | 5 | 8 |
| OpenCap's pixels lifted, best pick | 10 | 7 | 8 | 10 | 14 | 4 | 7 |
| Roboflow lifted to 3D (smooth path) | 15 | 28 | 13 | 39 | 40 | 17 | 15 |
| Roboflow lifted, best front/back pick (upper bound) | 11 | 17 | 9 | 29 | 27 | 12 | 11 |
| Geometric, qmt heading, rest 18° (chest+upper arm+Watch) | 6 | 11 | 21 | 39 | 71 | 16 | 39 |
| OpenSense IK, 4 sensors | 19 | 11 | 18 | 39 | 79 | 17 | 42 |
| Constraints, Watch only | 32 | 13 | 28 | 32 | 49 | 14 | 30 |
| WearMoCap, Watch | 22 | 29 | 18 | 37 | 33 | 16 | 16 |
| MobilePoser, Watch+phone+AirPods | 21 | 15 | 25 | 27 | 36 | 12 | 18 |
| IMUCoCo, Watch+phone+AirPods | 16 | 9 | 22 | 23 | 33 | 10 | 18 |
| Ours GRU, Watch, other player only | 16 | 12 | 13 | 17 | 21 | 7 | 11 |
| Ours GRU, all sensors, + own half of the block | 6 | 5 | 4 | 8 | 8 | 4 | 5 |
