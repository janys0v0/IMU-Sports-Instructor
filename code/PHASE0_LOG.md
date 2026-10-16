# Phase 0 — Reproduce published inference: log

## Environment (2026-09-30)
- Machine: arm64, macOS 15.7.1
- MobilePoser commit: 513e76a88ef310e12b51da6d30f44a819e68d331
- Conda env: `mobileposer`, Python 3.9.25
- torch 2.1.2 (MPS available: True; CUDA: no)
- open3d 0.17.0 (needs Homebrew `libomp`)

## Deviations from the README install
1. `chumpy==0.70` installed with `--no-build-isolation` (its setup.py imports pip).
2. `osqp==0.6.3` and `qdldl==0.1.7.post0` skipped (need CMake; used only by the missing physics module). Installed from `requirements-mac.txt`.
3. `pip install -e . --config-settings editable_mode=compat` (default editable mode maps no packages because `mobileposer/` has no `__init__.py`).
4. `config.py`: `paths.raw_imuposer` -> `root_dir / "data/raw/IMUPoser"`. No model code changed.

## Run scripts from `MobilePoser/mobileposer/`
`config.paths.root_dir` is the working directory, so files go in:
- `mobileposer/smpl/basicmodel_m.pkl`
- `mobileposer/checkpoints/weights.pth`
- `mobileposer/data/raw/IMUPoser/P1..P10`

## Checklist
- [x] Clone MobilePoser, Python 3.9 env
- [x] SMPL model (`basicmodel_m.pkl`, loads: 24 joints, 6890 vertices)
- [x] Pretrained weights (`weights.pth`, 26.7 MB, 72 tensors: pose, joints, foot_contact, velocity)
- [x] IMUPoser dataset (1.05 GB zip) + `python process.py --dataset imuposer` -> 133 train / 34 test sequences
- [x] `python evaluate.py --model checkpoints/weights.pth --dataset imuposer` (all 12 combos averaged, ~4 min)
- [x] Per-combo eval: `PYTHONPATH=. python ../../phase0/eval_combo.py --combo lw_rp` (wrapper; no model code changed)
- [x] `GT=1 python example.py --model checkpoints/weights.pth --dataset imuposer --seq-num 5 --combo lw_rp --with-tran`
  - Renders in a temporary open3d window, then writes `a.mp4` (moved to `phase0/imuposer_seq5_lw_rp_pred_vs_gt.mp4`)
- [x] Metrics repeat exactly on a second run (lw_rp)

**Exit criterion met:** plausible SMPL animation and repeatable metrics without changing model code.

## Baseline metrics — IMUPoser test set (P9, P10; 34 sequences), offline inference

| Combo | Devices | Angular err (deg) | Joint pos err (cm) | Mesh err (cm) | Jitter (100 m/s^3) |
|---|---|---|---|---|---|
| all 12 averaged | — | 19.55 | 8.15 | 10.44 | 0.97 |
| `lw_rp` | L watch + R pocket phone | 18.65 | 7.39 | 9.60 | 1.04 |
| `rw_rp` | R watch + R pocket phone | 18.01 | 7.49 | 9.59 | 1.07 |
| `lw_rp_h` | + AirPods | 17.55 | 7.31 | 9.14 | 0.99 |

Translation error (m) after the subject travels 1 / 2 / 3 / 5 / 7 m:
- `lw_rp`: 0.36 / 0.49 / 0.61 / 0.88 / 1.00
- `rw_rp`: 0.35 / 0.49 / 0.56 / 0.82 / 0.89
- `lw_rp_h`: 0.37 / 0.47 / 0.65 / 1.08 / 1.29

Notes:
- AirPods improve pose slightly (mesh 9.60 -> 9.14 cm) but not translation.
- Translation drifts ~30-35% of distance over the first metre; treat root position as approximate.
- `forward_online` on Mac CPU: 13.5 ms/frame (budget at 30 fps: 33 ms).
- Viewer plays at 25 fps (`SMPLViewer` default) though data is 30 fps; cosmetic only.
- Not done: running one sequence through IMUPoser's own code (dropped from the revised plan; IMUPoser data path is already exercised by `process.py`).

## Later changes to MobilePoser model code (2026-10-01)
Both affect root translation only; pose output is unchanged. Marked `ES224:` in `models/net.py`.
1. `reset()` also clears `velocity.rnn_state` and the last foot positions. Before, the velocity RNN state carried over between sequences and between live calibrations.
2. `forward_online`: foot-contact logits go through `.sigmoid()` before `_prob_to_weight`, as `forward_offline` already does. Before, live translation weighted foot contact differently from offline.
