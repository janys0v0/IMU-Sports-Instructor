# Sparse-IMU reconstruction models for head + wrist + pocket (survey, 2026-10-13)

Extends `MobilePoser and Sparse Consumer IMU Research.md` with work found on 2026-10-13 and
compares models for this project's data points: **AirPods (head), one Apple Watch (wrist), one
iPhone (thigh pocket)**. Our own head-to-head runs are in `EXPERIMENT_LOG.md` (E01, E02).

> Numbers are as reported in each paper, read from the arXiv HTML on 2026-10-13. They use
> different metrics, datasets and sensor sets, so compare **within a table, never across tables**.
> Check the paper before citing.

## 1. What can run on our recordings today

| Model | Venue | Fits head + wrist + pocket | Pretrained weights | Run here |
|---|---|---|---|---|
| MobilePoser | UIST 2024 | Yes (trained combos all include the pocket phone) | Yes | Yes: live pipeline, E01 |
| IMUCoCo | UIST 2025 | Yes (any placement, any count) | Yes | Yes: E02 |
| IMUPoser | CHI 2023 | Yes | No (train on AMASS + DIP-IMU) | No |
| BaroPoser | UIST 2025 | Wrist + pocket + barometers only; no head | No | No |
| ArmPoser | SUI 2026 | Watch only (arm only) | No ("coming soon" repo) | No |
| One Sensor, Whole Body | HUMA @ ACM MM 2026 | AirPods only (+ insoles) | No (code yes; data "to be released") | No |
| Progressive Inertial Poser | arXiv 2025 | Head + **both** wrists | No | No |
| 3SIP | Computers & Graphics 2026 | Head + both wrists | No | No |
| TransPose / PIP / PNP / DynaIP / GlobalPose | 2021-2025 | No: six fixed research IMUs | Some | No |
| DiffusionPoser | CVPR 2024 | Any subset of 13 locations | Not verified | No |

**So the only state-of-the-art models runnable on our data are MobilePoser and IMUCoCo**, which
E02 already compares. Everything else below is a comparison of published numbers.

## 2. Published comparisons closest to our devices

### Wrist + thigh pocket + ear (our exact set): IMUCoCo paper
Custom 12-participant dataset, Apple Watches as IMUs, OptiTrack ground truth. Global angular
error (degrees; root, wrists, fingers, toes excluded).

| Model | Wrist + pocket + ear |
|---|---|
| MobilePoser | 31.8° |
| **IMUCoCo** | **27.6°** (p < .001) |

IMUCoCo holds 28.6-29.3° when one device moves (wrist→upper arm, pocket→lower leg, ear→torso).
This is the only published head-to-head on our exact device set, and it is from the IMUCoCo
authors. Our E02 agrees in direction for sensed bones and head yaw, but found IMUCoCo does not
fill in unsensed limbs.

### Wrist + thigh pocket (no head): BaroPoser paper
Left wrist + right pocket, online. SIP error (°) / angular error (°) / joint position (cm) / mesh (cm).

| Model | DIP-IMU | IMUPoser dataset | TotalCapture | Real phone + watch |
|---|---|---|---|---|
| IMUPoser | 27.2 / 23.1 / 10.0 / 12.3 | 18.2 / 20.4 / 8.9 / 11.6 | 17.4 / 18.8 / 8.9 / 10.8 | 28.5 / 26.5 / 12.2 / 14.9 |
| MobilePoser | 26.9 / 22.4 / 9.3 / 11.3 | 17.5 / 19.5 / 8.6 / 11.0 | 17.2 / 18.6 / 8.8 / 10.5 | 28.0 / 25.7 / 12.0 / 14.5 |
| **BaroPoser** | **24.4 / 21.3 / 8.6 / 10.4** | **13.2 / 16.2 / 6.8 / 9.0** | **14.5 / 16.2 / 7.4 / 8.9** | **24.8 / 23.5 / 10.7 / 13.0** |

BaroPoser needs barometers on both devices (heights are synthesized for the public datasets) and
a fixed left-wrist/right-pocket layout. Our Phase 0 MobilePoser numbers on the IMUPoser dataset
(`lw_rp`: 18.7° / 7.4 cm / 9.6 cm, offline) are in the same range as its MobilePoser row.

### Any 1-3 consumer devices: MobilePoser paper
Mesh vertex error (MPJVE, cm), fine-tuned on DIP-IMU.

| Model | IMUs | DIP-IMU | TotalCapture |
|---|---|---|---|
| IMUPoser | 1-3 consumer | 12.1 | 15.4 |
| **MobilePoser** | 1-3 consumer | **10.6** | **12.6** |
| TransPose | 6 research | 7.1 | 7.4 |
| PIP | 6 research | 5.9 | 6.5 |

MobilePoser reports 24% / 14% / 9% lower error than IMUPoser with 1 / 2 / 3 devices. Six-sensor
research systems remain about twice as accurate as any consumer-device system.

### One wrist (Watch arm only): ArmPoser paper
Median wrist + elbow position error (cm), shoulder-aligned.

| Model | TotalCapture | DIP-IMU | IMUPoser | ArmPoser data | Calibration |
|---|---|---|---|---|---|
| IMUPoser | 10.6 | 8.7 | 8.1 | 10.0 | Chest + T-pose |
| MobilePoser | 9.6 | 8.5 | 7.9 | 9.6 | Chest + T-pose |
| **ArmPoser** | **9.2** | **8.0** | **7.6** | **7.7** | **None** |

Arm only (clavicle to wrist), no body, no heading. Same lab as MobilePoser. Relevant because our
E02 found the Watch calibration is the weak point of our pipeline.

### Head only (AirPods): One Sensor, Whole Body
One subject, pseudo-ground-truth from RGB-D; rigid-aligned joint error (mm), lower body.

| Input | IMUPoser-style net | MobilePoser-style net | Mean-pose prior |
|---|---|---|---|
| Head only | 79-93 | 86-94 | 105.5 |
| Head + insoles | 96-107 | 87-99 | |

A single AirPods stream beats the mean pose by ~25% for the lower body and gives foot contact at
0.81 macro-F1; adding consumer insoles did not help. Wrists are barely recoverable from the head
(R² 0.30). A feasibility pilot, not a benchmark.

### Head + both wrists: Progressive Inertial Poser
Rotation error (°) / joint position (cm) / mesh (cm), all methods re-adapted to head + wrists.

| Model | AMASS | TotalCapture |
|---|---|---|
| IMUPoser | 17.4 / 9.5 / 10.3 | 19.4 / 11.3 / 12.2 |
| AGRoL (diffusion) | 14.5 / 9.5 / 10.1 | 19.2 / 10.0 / 11.0 |
| TransPose (3-IMU) | 14.2 / 8.7 / 8.9 | 18.0 / 9.8 / 10.3 |
| AvatarPoser | 12.7 / 7.5 / 7.6 | 16.7 / 8.5 / 9.0 |
| **ProgIP** | **11.4 / 7.1 / 7.0** | **16.2 / 8.1 / 8.5** |

Needs two wrists and research IMUs; cannot tell sitting from standing. An upper bound for
"head + wrists, no pocket phone".

### Six research IMUs (context): IMUCoCo paper, TotalCapture, global angular error
TransPose 16.1°, PIP 14.4°, DiffusionPoser 14.4°, IMUCoCo 14.0°, **PNP 10.4°**. With sensors
removed, IMUCoCo degrades more slowly than DiffusionPoser (head only: 32.0° vs 39.2°).

## 3. Other new work found (not pose reconstruction from our devices)

- **AnyMo** (arXiv 2605.22715, 2026): placement-agnostic IMU encoder aligned to an LLM for
  activity recognition, retrieval and captioning. No pose output. Relevant to an activity-first design.
- **Group Inertial Poser** (ICCV 2025): multi-person pose and translation from IMUs + UWB ranging.
- **Physics-based global motion** (Yi, Pan, Xu, SIGGRAPH 2025; arXiv 2505.05010): multi-contact
  physics for six-IMU translation in 3D terrain.
- **DiffCap** (arXiv 2508.06139, 2025): diffusion model fusing sparse IMUs with one camera.
- **Mocap Everyone Everywhere** (CVPR 2024): two smartwatches + a head-mounted camera.
- **WearMoCap** (2024): Watch + pocket phone for arm and hip tracking in robot control.
- **Transformer IMU Calibrator** on IMUPoser consumer data: orientation error 23.6° → 19.0°
  with dynamic calibration (right-pocket case slightly worse).

## 4. Takeaways for this project

1. **For our exact sensors, the state of the art is IMUCoCo and MobilePoser**, and both run here.
   Published (27.6° vs 31.8°) and our own E02 results favour IMUCoCo for sensor fidelity;
   MobilePoser is better at plausible unsensed limbs and is the only one with trained
   consumer-device combinations and a live pipeline.
2. **Accuracy ceiling:** every consumer-device system sits near 9-13 cm mesh error and 16-28°
   angular error, about twice the error of six-IMU systems. Joint-level biomechanics claims are
   not supported by any of these papers.
3. **Calibration is the active research front** (ArmPoser calibration-free, TIC dynamic
   calibration). MobilePoser's paper specifies a **T-pose**; our pipeline calibrates standing
   with arms down, which E02 showed mis-poses the Watch arm. Fix that before further comparisons.
4. **Device value, per the literature and E01:** pocket phone anchors legs and translation; the
   Watch gives its own arm only; AirPods give head, heading and (new result) some lower-body and
   foot-contact information by themselves.
5. **To watch:** ArmPoser code release (calibration-free Watch arm), BaroPoser code (adds iPhone/
   Watch barometers, which our app does not record yet), the earbud paper's data release.

## Sources

- MobilePoser: https://arxiv.org/abs/2504.12492
- IMUPoser: https://arxiv.org/abs/2304.12518
- IMUCoCo: https://arxiv.org/abs/2508.01894
- BaroPoser: https://arxiv.org/abs/2508.03313
- ArmPoser: https://arxiv.org/abs/2609.08806 · https://github.com/SPICExLAB/ArmPoser
- One Sensor, Whole Body: https://arxiv.org/abs/2609.34978 · https://github.com/ZhilinGuo/one-sensor-whole-body
- Progressive Inertial Poser: https://arxiv.org/abs/2505.05336
- AnyMo: https://arxiv.org/abs/2605.22715
- Transformer IMU Calibrator: https://arxiv.org/abs/2506.10580
- Physics-based global motion: https://arxiv.org/abs/2505.05010
- DiffCap: https://arxiv.org/abs/2508.06139
- DynaIP: https://arxiv.org/abs/2312.02196
- Mocap Everyone Everywhere: https://openaccess.thecvf.com/content/CVPR2024/html/Lee_Mocap_Everyone_Everywhere_Lightweight_Motion_Capture_With_Smartwatches_and_a_CVPR_2024_paper
