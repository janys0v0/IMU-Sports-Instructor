# Method details

One document per arm-pose method tested in E07 (10/28) and E08 (Janys 11/05), detailed enough to
rebuild each from scratch. Every value is taken from the code, with `path:line` references.
Diagrams are Mermaid; they render on GitHub and in VS Code.

Start with [`shared_pipeline.md`](shared_pipeline.md) (recording, clocks, the 30 Hz grid, swings, the
trunk frame, scoring) and [`opencap_ground_truth.md`](opencap_ground_truth.md) (the reference every
method is scored against).

| Method | Doc | Source | Training |
|---|---|---|---|
| Ridge regression | [`ridge_regression.md`](ridge_regression.md) | ours | trained on our 10/28 and 11/05 data |
| Bidirectional GRU | [`bidirectional_gru.md`](bidirectional_gru.md) | ours | trained on our 10/28 and 11/05 data |
| Geometric (segment orientations, heading alignment, qmt heading correction, Apple-only variants) | [`geometric.md`](geometric.md) | ours; qmt and VQF libraries (Laidig et al.) | none |
| Joint constraints (Watch only, Viterbi) | [`joint_constraints.md`](joint_constraints.md) | ours, after ArmTrak | none |
| OpenSense IMU inverse kinematics | [`opensense_ik.md`](opensense_ik.md) | OpenSim 4.6 (Al Borno et al. 2022) | none |
| WearMoCap | [`wearmocap.md`](wearmocap.md) | published (IROS 2023) | pretrained by the authors |
| MobilePoser | [`mobileposer.md`](mobileposer.md) | published (UIST 2024) | pretrained by the authors |
| IMUCoCo | [`imucoco.md`](imucoco.md) | published (UIST 2025) | pretrained by the authors |
| OpenCap (ground truth) | [`opencap_ground_truth.md`](opencap_ground_truth.md) | published (Uhlrich et al. 2023) | pretrained 2D pose and marker models |

## Known code issues found while writing these docs

Not yet fixed. The docs describe the code as it is.

- `GRU.predict` (`experiments/E07_pose_methods/learned_own.py`) never calls `net.eval()`, so dropout
  (0.2) stays on at test time and predictions are slightly random. Every GRU score in E07/E08
  includes this noise.
- `context()` in the same file ignores its `seg` argument: the ±0.5 s ridge context window runs
  across segment boundaries.
- `wearmocap.py` calls `body_basis` without the per-segment key, so on 11/05 WearMoCap uses the
  phone-screen forward rule, not the thigh rule the other methods use.
- `qmt` and `vqf` are installed in `.venv` but not pinned in `requirements.txt`; WearMoCap is not
  pinned in `tools/setup_third_party.sh`.
