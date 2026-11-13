# E09 janys: right arm, Roboflow vs IMU methods, against OpenCap in phone1

Medians over the window's frames. px: image error of the elbow and wrist; dir: angle of the 2D upper-arm / forearm segment; angle: image-plane elbow angle; 3D: E07's elbow flexion and forearm direction (IMU only).

## Swings

| Method | Elbow px | Wrist px | Upper-arm dir ° | Forearm dir ° | Elbow angle ° | 3D elbow ° | 3D forearm ° |
|---|---|---|---|---|---|---|---|
| Roboflow YOLO pose (as detected) | 27 | 27 | 30 | 25 | 38 | – | – |
| Roboflow YOLO pose (shoulder-anchored) | 17 | 24 | 30 | 25 | 38 | – | – |
| OpenCap model axes (floor of the construction) | 7 | 9 | 9 | 10 | 13 | 0 | 0 |
| Geometric, qmt heading, rest 18° (chest+upper arm+Watch) | 42 | 71 | 79 | 64 | 20 | 14 | 62 |
| OpenSense IK, 4 sensors | 39 | 74 | 69 | 81 | 15 | 30 | 74 |
| Constraints, Watch only | 42 | 52 | 70 | 17 | 62 | 40 | 33 |
| WearMoCap, Watch | 21 | 38 | 33 | 18 | 26 | 31 | 45 |
| MobilePoser, Watch+phone+AirPods | 38 | 57 | 70 | 41 | 41 | 35 | 37 |
| IMUCoCo, Watch+phone+AirPods | 21 | 26 | 29 | 14 | 18 | 18 | 28 |
| Ours GRU, Watch, other player only | 28 | 30 | 48 | 20 | 47 | 28 | 26 |
| Ours GRU, all sensors, + own half of the block | 12 | 18 | 17 | 12 | 18 | 10 | 14 |

## All

| Method | Elbow px | Wrist px | Upper-arm dir ° | Forearm dir ° | Elbow angle ° | 3D elbow ° | 3D forearm ° |
|---|---|---|---|---|---|---|---|
| Roboflow YOLO pose (as detected) | 10 | 14 | 7 | 10 | 9 | – | – |
| Roboflow YOLO pose (shoulder-anchored) | 9 | 14 | 7 | 10 | 9 | – | – |
| OpenCap model axes (floor of the construction) | 4 | 8 | 4 | 11 | 9 | 0 | 0 |
| Geometric, qmt heading, rest 18° (chest+upper arm+Watch) | 19 | 41 | 23 | 42 | 28 | 6 | 71 |
| OpenSense IK, 4 sensors | 19 | 45 | 23 | 58 | 32 | 19 | 79 |
| Constraints, Watch only | 16 | 30 | 20 | 14 | 20 | 32 | 49 |
| WearMoCap, Watch | 16 | 17 | 20 | 11 | 25 | 22 | 33 |
| MobilePoser, Watch+phone+AirPods | 13 | 24 | 16 | 28 | 16 | 21 | 36 |
| IMUCoCo, Watch+phone+AirPods | 12 | 19 | 15 | 14 | 12 | 16 | 33 |
| Ours GRU, Watch, other player only | 8 | 12 | 10 | 13 | 15 | 16 | 21 |
| Ours GRU, all sensors, + own half of the block | 7 | 12 | 8 | 14 | 12 | 6 | 8 |
