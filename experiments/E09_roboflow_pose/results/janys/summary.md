# E09 janys: Roboflow YOLO pose vs OpenCap projected into phone1

599 frames (150 in swings); player found in 98.3%; median torso 82 px.

| Joint | Median px | p90 px | PCK@0.2 torso | Swing median px |
|---|---|---|---|---|
| RShoulder | 6.9 | 16.3 | 92% | 10.3 |
| LShoulder | 6.3 | 15.4 | 92% | 8.6 |
| RElbow | 9.8 | 33.6 | 71% | 26.6 |
| LElbow | 15.3 | 28.7 | 55% | 16.6 |
| RWrist | 13.9 | 40.1 | 60% | 26.9 |
| LWrist | 13.2 | 35.8 | 62% | 18.1 |
| RHip | 9.5 | 15.0 | 94% | 9.8 |
| LHip | 9.6 | 15.5 | 95% | 11.2 |
| RKnee | 19.3 | 27.7 | 26% | 16.7 |
| LKnee | 18.2 | 28.8 | 37% | 21.3 |
| RAnkle | 23.5 | 30.3 | 12% | 23.2 |
| LAnkle | 20.4 | 30.4 | 21% | 21.8 |

All joints: median 13.9 px, PCK@0.2 torso 60%. Right elbow angle (image plane): median error 9.0° (37.8° in swings).
