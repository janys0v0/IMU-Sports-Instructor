---
title: MobilePoser and Sparse Consumer IMU Research
aliases:
  - AirPods and Apple Watch Pose Tracking Research
  - Sparse Consumer IMU Literature Review
tags:
  - es224
  - research-notes
  - biomechanics
  - imu
  - motion-capture
  - wearable-computing
status: research-index
created: 2026-09-30
---

# MobilePoser and sparse consumer IMU research

> [!warning] Private research notes
> Source index and study notes for the project described in [[ES 224_Project Proposal.pdf]]. This is not submission-ready course text. Verify every claim against the linked paper before citing it, and follow the course policy on generative-AI use.

## Project question

Can AirPods and one Apple Watch provide enough information to recognize activities and deliver useful posture or technique feedback without a camera?

The practical answer from the literature is:

- **Activity recognition, repetition counting, phase timing, and directly observed head/wrist metrics are feasible.**
- **Exercise-specific error detection may be feasible when the target error has a repeatable head or wrist signature and is validated separately.**
- **General full-body reconstruction is possible only as an approximate, prior-driven estimate.** Head plus one wrist does not directly observe the pelvis, spine, knees, feet, opposite arm, external equipment, or contact forces.
- **The most defensible product should recognize the activity first and report a small set of observable or experimentally validated signals.** A generated skeleton can be useful internally or visually, but should not be presented as direct joint measurement.

## Research lineage

```text
Sparse research IMUs
SIP (2017) -> DIP (2018) -> TransPose (2021) -> PIP (2022)
                                              |
Consumer devices                              +-> DynaIP / DiffusionPoser / GlobalPose
Pose-on-the-Go (2021) -> IMUPoser (2023) -> MobilePoser (2024)
                                                  |
                                                  +-> BaroPoser / IMUCoCo / MARIO

Activity-first product path
SAMoSA -> WatchHAR -> TransfHAR -> exercise-specific feedback
```

## Directly relevant consumer-device studies

### IMUPoser — Mollyn et al., CHI 2023

**Question.** Can devices people already carry—phones, watches, and earbuds—produce an approximate full-body pose when the available device subset changes?

**Method.** IMUPoser accepts any subset of supported consumer-device locations and uses orientation and acceleration histories to regress SMPL body pose. Its real-device dataset used iPhone 11 Pro phones, Apple Watch Series 6 watches, AirPods Pro, and Vicon ground truth from 10 participants. AirPods produced a single fused six-degree-of-freedom head estimate rather than separate estimates for the two ears. The experiment configured AirPods at 25 Hz.

**Results.** Averaged across the evaluated device combinations and datasets, one device produced a mean per-joint vertex error of 16.27 cm, two devices 13.9 cm, and three devices 11.1 cm. These are aggregate results across combinations, not a specific guarantee for AirPods plus one Watch. Instrumented regions were more accurate than uninstrumented regions. Head orientation was substantially better when earbuds were present, while independently moving uninstrumented limbs were a major failure case.

**Importance to this project.** This is the closest published demonstration of the proposed Apple-device ecosystem. It establishes feasibility for approximate motion understanding, but its errors are too large to treat unobserved joint positions as precise biomechanical measurements.

**Citation.** Mollyn, V., Arakawa, R., Goel, M., Harrison, C., & Ahuja, K. (2023). IMUPoser: Full-body pose estimation using IMUs in phones, watches, and earbuds. In *Proceedings of the 2023 CHI Conference on Human Factors in Computing Systems* (Article 529, pp. 1–12). ACM. [DOI](https://doi.org/10.1145/3544548.3581392) · [arXiv](https://arxiv.org/abs/2304.12518) · [code](https://github.com/FIGLAB/IMUPoser)

### MobilePoser — Xu et al., UIST 2024

**Question.** Can sparse IMUs in phones, watches, and earbuds recover both full-body pose and global translation in real time on consumer hardware?

**Method.** MobilePoser masks unavailable devices, estimates joint positions and rotations with a multistage network, estimates translation using foot-contact probabilities and learned velocity, and then applies a physics optimizer. The authors report real-time operation at 60 fps on an iPhone 15 Pro.

**Improvement over IMUPoser.** It adds global translation, stronger temporal consistency, and physical refinement. It is therefore a better architectural reference for a deployable system.

**Limitation for this project.** The phone/pocket observation is especially useful because it is near the body root. Removing it leaves only head and one wrist, so MobilePoser's complete-system accuracy should not be interpreted as proof of accurate lower-body posture from AirPods and a Watch alone.

**Citation.** Xu, V., Gao, C., Hoffmann, H., & Ahuja, K. (2024). MobilePoser: Real-time full-body pose estimation and 3D human translation from IMUs in mobile consumer devices. In *Proceedings of the 37th Annual ACM Symposium on User Interface Software and Technology* (Article 70, pp. 1–11). ACM. [DOI](https://doi.org/10.1145/3654777.3676461) · [project](https://spice-lab.org/projects/MobilePoser/) · [code](https://github.com/SPICExLAB/MobilePoser)

### Three-Sensor Inertial Poser (3SIP) — Guo and Zhao, 2026

**Question.** How much full-body motion can be generated from only three IMUs on the head and two wrists?

**Contribution.** The placement is close to a headphone plus two-watch/controller configuration and is therefore an important upper-bound reference for the proposed system.

**Limitations.** Three-sensor reconstruction remains ambiguous, especially for the lower body, global translation, and foot contact. The proposed project has only one wrist sensor, so it is more under-constrained than 3SIP.

**Citation.** Guo, Z., & Zhao, J. (2026). Three-Sensor Inertial Poser (3SIP): Full-body motion generation using only three inertial measurement units. *Computers & Graphics, 136*, 104585. [DOI](https://doi.org/10.1016/j.cag.2026.104585) · [code](https://github.com/vrlab561/3SIP-release)

### IMUCoCo — Zhou et al., UIST 2025

**Question.** Can one model accept a variable number of IMUs placed at arbitrary continuous coordinates on the body rather than only at a fixed list of joints?

**Method.** IMUCoCo encodes the sensor's T-pose coordinate and body region, maps its motion signal into joint-aligned features, and passes those features to downstream pose-estimation or activity-recognition models. It trains extensively with synthetic virtual IMUs over a body mesh.

**Results and interpretation.** On the conventional six-IMU TotalCapture configuration, the paper reports 14.0 degrees global angular error versus 14.4 degrees for DiffusionPoser. Its larger advantage appears when sensors are removed or rearranged. The main contribution is placement generalization, not a dramatic improvement in standard six-sensor accuracy.

**Importance to this project.** Useful if Watch or earbud position varies across users. It does not by itself solve heading drift, attachment movement, automatic placement identification, or unobservability of lower-body posture.

**Citation.** Zhou, H., Arakawa, R., Agarwal, Y., & Goel, M. (2025). IMUCoCo: Enabling flexible on-body IMU placement for human pose estimation and activity recognition. In *Proceedings of the 38th Annual ACM Symposium on User Interface Software and Technology* (pp. 1–16). ACM. [DOI](https://doi.org/10.1145/3746059.3747695) · [arXiv](https://arxiv.org/abs/2508.01894) · [code](https://github.com/cmusmashlab/IMUCoCo)

## SPICE Lab work related to MobilePoser

### Pose-on-the-Go — Ahuja et al., CHI 2021

An early predecessor that fused smartphone front/rear cameras, depth sensing, touch, and IMU data, then used inverse kinematics to fill unobserved joints. It established the lab's consumer-sensor approach but is not camera-free. [Project](https://spice-lab.org/projects/Pose-on-the-Go/) · [DOI](https://doi.org/10.1145/3411764.3445582)

### WatchHAR — Yeon et al., ICMI 2025

Runs activity recognition completely on a smartwatch using one-second windows of six-axis IMU and audio. The paper reports more than 90% accuracy over 25-plus activity classes, with approximately 9.3 ms event-detection and 11.8 ms multimodal-classification processing times. This supports an activity-first architecture that does not require full-body pose as an intermediate product output. [Project](https://spice-lab.org/projects/WatchHAR/)

### TransfHAR — Bradshaw et al., UIST 2026

Uses self-supervised pretraining on coarse wrist activities and few-shot adaptation to fine-grained new actions. It reports 86.7% balanced accuracy across participants with five examples per class and 90.4% after a one-minute recording per class. This is relevant to personalized coaching: learn a general wrist representation, then adapt to a user's exercises or technique patterns with little labeled data. [Project](https://spice-lab.org/projects/TransfHAR/)

### MARIO — Li et al., CVPR Findings 2026

Uses an IMU-inferred human-pose prior to constrain inertial odometry. The paper reports reducing positional drift by up to 36% on Nymeria and up to 42% when adding a magnetometer, barometer, and secondary IMU. MARIO is aimed at camera-free localization and AR-glasses sensing, not directly at full-body posture, but it is the lab's closest follow-up on MobilePoser's translation and drift problem. [Project](https://spice-lab.org/projects/MARIO/) · [arXiv](https://arxiv.org/abs/2606.02996)

### SurfaceXR — Xu et al., IEEE VR/TVCG 2026

Fuses smartwatch IMU micro-vibrations with headset hand tracking for contact and gesture recognition. Its main lesson is that IMU and vision are complementary: vision supplies spatial position while the IMU captures rapid local motion and contact events. [Project](https://spice-lab.org/projects/SurfaceXR/) · [DOI](https://doi.org/10.1109/TVCG.2026.3679136)

## Foundational sparse-IMU pose work

### Sparse Inertial Poser (SIP) — von Marcard et al., 2017

Demonstrated full-body pose estimation from six IMUs by optimizing a statistical body model against orientation and acceleration over multiple frames. It established the six-sensor sparse-IMU configuration but was computationally expensive and offline. [Paper](https://arxiv.org/abs/1703.08014) · [DOI](https://doi.org/10.1111/cgf.13131)

### Deep Inertial Poser (DIP) — Huang et al., SIGGRAPH Asia 2018

Made six-IMU reconstruction learning-based and real-time using temporal neural priors and synthetic training data. It introduced DIP-IMU: 10 subjects, 17 IMUs, 64 sequences, and about 330,000 time instants. DIP-IMU became a major benchmark for later work. [Paper](https://arxiv.org/abs/1810.04703) · [DOI](https://doi.org/10.1145/3272127.3275108)

### TransPose — Yi et al., SIGGRAPH 2021

Added real-time global translation estimation to six-IMU pose capture. A multistage network estimates leaf joints, full joints, and pose; supporting-foot and learned-velocity estimates are fused for translation. Contact assumptions are less reliable for seated, airborne, climbing, or unusual sports motions. [Paper](https://arxiv.org/abs/2105.04605) · [DOI](https://doi.org/10.1145/3450626.3459786)

### Physical Inertial Poser (PIP) — Yi et al., CVPR 2022

Combines a learned kinematics estimator with a physics optimizer to reduce jitter, foot sliding, and physically implausible motion. It also estimates joint torques and ground-reaction forces from six IMUs. These are model-based estimates, not direct force-plate measurements. [Paper](https://openaccess.thecvf.com/content/CVPR2022/html/Yi_Physical_Inertial_Poser_PIP_Physics-Aware_Real-Time_Human_Motion_Tracking_From_CVPR_2022_paper.html)

### DynaIP — Zhang et al., CVPR 2024

Uses part-specific motion models, pseudo-velocity regression, and multiple real IMU datasets to improve dynamic-motion generalization. It reports a 19% pose-error reduction on DIP-IMU relative to prior methods. IMUCoCo adopts DynaIP as part of its downstream pose estimator. [Paper](https://openaccess.thecvf.com/content/CVPR2024/html/Zhang_Dynamic_Inertial_Poser_DynaIP_Part-Based_Motion_Dynamics_Learning_for_Enhanced_CVPR_2024_paper.html)

### DiffusionPoser — Van Wouwe et al., CVPR 2024

Uses one autoregressive diffusion model for arbitrary subsets of IMUs and pressure insoles selected from 13 predefined locations. It can generate plausible motion for unobserved degrees of freedom, but plausible generation is not equivalent to biomechanical measurement. [Paper](https://openaccess.thecvf.com/content/CVPR2024/html/Van_Wouwe_DiffusionPoser_Real-time_Human_Motion_Reconstruction_From_Arbitrary_Sparse_Sensors_Using_CVPR_2024_paper.html)

## Work addressing specific MobilePoser limitations

### Dynamic calibration: Transformer IMU Calibrator — Zuo et al., SIGGRAPH/TOG 2025

Estimates changing world-frame alignment and sensor-to-body offsets from short windows of diverse motion. It relaxes the assumption that a T-pose/heading calibration remains constant for an entire session and introduces a trigger that waits for sufficiently informative motion. The work received a SIGGRAPH 2025 Best Paper Award. This is directly relevant to long workouts and changing Watch placement. [Paper](https://arxiv.org/abs/2506.10580) · [DOI](https://doi.org/10.1145/3730937) · [code](https://github.com/ZuoCX1996/TIC)

### Uneven terrain and vertical translation: BaroPoser — Zhang et al., UIST 2025

Combines IMU and barometric data from a smartphone and smartwatch. Relative pressure-derived height changes help estimate pose and vertical translation on stairs, slopes, and uneven terrain. It is a direct consumer-device extension of MobilePoser, but it requires a phone near the thigh/pocket and a barometric signal. [Paper](https://arxiv.org/abs/2508.03313) · [code](https://github.com/zhanglbthu/BaroPoser)

### Global motion and contacts: GlobalPose — Yi et al., SIGGRAPH/TOG 2025

Uses multi-contact physics to improve six-IMU translation in unconstrained 3D environments and jointly estimates contact, contact forces, joint torques, and proxy surfaces. It is physically more ambitious than MobilePoser but relies on six IMUs. [Project](https://xinyu-yi.github.io/GlobalPose/)

### Absolute distance constraints: UMotion and UltraPoser

**UMotion** combines IMUs with UWB ranging and uncertainty-aware filtering, adding absolute inter-sensor distances that help constrain drift and pose ambiguity. [CVPR 2025 paper](https://openaccess.thecvf.com/content/CVPR2025/html/Liu_UMotion_Uncertainty-driven_Human_Motion_Estimation_from_Inertial_and_Ultra-wideband_Units_CVPR_2025_paper.html)

**UltraPoser** adds ultrasound sensing between consumer wearables to recover spatial relationships and unsensed limb motion. This direction is promising because absolute range does not accumulate IMU integration drift, but current AirPods and Apple Watch APIs do not expose this as a general ranging system. [UIST 2025 paper](https://yadongli.com/assets/pdf/UltraPoser.pdf)

### Camera correction: Total Capture and monocular RGB–IMU fusion

**Total Capture** introduced a synchronized multiview-video, IMU, and motion-capture dataset and demonstrated that video and inertial streams can resolve one another's ambiguities. [BMVC 2017 paper](https://bmva-archive.org.uk/bmvc/2017/papers/paper014/index.html)

**Fusing Monocular Images and Sparse IMU Signals for Real-Time Human Motion Capture** combines a single RGB camera with sparse IMUs and reasons in both camera and body-root coordinates. This is a strong reference if the project allows occasional video calibration or uses a camera only as experimental ground truth. [Paper](https://arxiv.org/abs/2309.00310)

## Project implications

### Measurements that are directly defensible

- Head orientation, rotation rate, gravity-relative tilt, and linear acceleration from AirPods.
- Dominant-wrist orientation, rotation rate, and acceleration from Apple Watch.
- Timing between head and wrist events.
- Repetition and phase duration.
- Within-user consistency and deviation from a recorded baseline.

### Inferences requiring exercise-specific validation

- Exercise or stroke identity.
- Repetition count and movement phase.
- Fatigue-related change in a repeated motion signature.
- Technique deviations that reliably alter head–wrist timing or orientation.
- Coarse full-body pose used as a latent representation or visualization.

### Claims that should not be made from AirPods plus one Watch alone

- Exact knee, hip, ankle, spine, or opposite-arm position.
- Knee valgus, squat depth, foot placement, or load distribution unless separately instrumented.
- Racquet-face or ball trajectory.
- Ground-reaction forces or internal joint loading.
- Laboratory-grade global translation or joint-by-joint biomechanics.

## Proposed evaluation

Compare four sensor configurations against camera or optical motion-capture ground truth:

1. Watch only.
2. AirPods only.
3. AirPods plus Watch.
4. AirPods plus Watch plus a pelvis/phone IMU.

Report:

- Activity-classification macro F1.
- Rep-count mean absolute error.
- Movement-phase boundary error in milliseconds.
- Sensitivity, specificity, and false-feedback rate for each technique deviation.
- Direct head/wrist orientation and angular-velocity errors.
- Full-body joint error only as a secondary diagnostic.
- Cross-user and personalized-model performance.
- Performance under fatigue and across multiple sessions.
- Calibration stability, device synchronization, battery use, and missing-data behavior.

The critical ablation is configuration 3 versus configuration 1: **how much incremental information do AirPods add beyond the Watch?** Configuration 4 measures the value of adding a root/pelvis observation.

## Bottom line

The literature supports building an AirPods + Apple Watch prototype for activity recognition, repetition/phase tracking, personalized deviation detection, and coaching tied directly to head and wrist motion. It does not support treating two consumer sensing locations as a precise full-body biomechanics laboratory. The research opportunity is to identify the smallest set of exercise-specific feedback signals that remain accurate, useful, and low-friction under this sensing constraint.
