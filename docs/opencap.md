# OpenCap ground truth (deferred)

**Status:** deferred until ground-truth comparison starts ([`decisions.md`](decisions.md)). The app
keeps the Trial button and sync gesture (design §9) so recordings are ready for this.

## 1. Recording with OpenCap

OpenCap (class kit) is **2 iPhone 12 Pros on tripods ≥ 8 ft apart + a checkerboard**, run
from the OpenCap web app on a laptop. It needs **good light, a plain high-contrast background
and stable internet**; kinematics come back from the cloud **hours to a day later**.

| Topic | Plan |
|---|---|
| **Where** | Ground truth only exists **inside the camera volume**. Record IMU sessions as long as you like, but embed **short OpenCap trials** (30-120 s each) in them. Pilot indoors (lab, white wall) before trying a court. |
| **Separate phones** | The two OpenCap iPhones are cameras only; the IMU iPhone stays in the pocket. Charge all four devices; the OpenCap phones also need to stay online. |
| **Session order** | OpenCap checkerboard → OpenCap **neutral pose** → **IMU calibration (standing + arms-out pose) immediately after, facing the same way** → trials. Repeat the IMU calibration before every OpenCap trial block. |
| **Trial names** | One naming scheme in both systems: `<IMU session>_T03_squats`. The app's Trial button records the same name, the Unix time and a note. |
| **Visual slate** *(new)* | At trial start, the app shows a full-screen slate (session ID, trial #, Unix time to ms, a flashing square) toward a camera for 2 s. It gives frame-accurate sync in the video and a readable label. |
| **Sync** | Slate + "3 hops" gesture → coarse alignment (± 1 frame from the slate); then refine by cross-correlating IMU vertical acceleration with OpenCap pelvis height. Log the residual offset per trial. |
| **Subject data** | Height and mass (OpenCap asks for them; reuse them to scale the SMPL body), handedness, shoe and pocket type. |
| **Download and archive** | Per OpenCap session: videos, marker trajectories, OpenSim model and joint kinematics, session metadata. Keep them in `recordings/<session>/opencap/`, untouched. |

## 2. Merging and comparison on the Mac

```
 IMU chunks ─▶ ingest_field.py ─▶ stream.jsonl ──┐
                                                  ├─▶ align (slate + hops) ─▶ E04_opencap_validation
 OpenCap download ─▶ opencap/ (markers, joint angles) ┘
```

| Step | Plan |
|---|---|
| Common timeline | Resample both to 30 Hz on the IMU phone clock, after the sync offset |
| **Calibration check first** | Compare OpenCap forearm / thigh / head segment orientations with the calibrated Watch / phone / AirPods orientations. This tests the calibration directly and settles the E02 forearm question. |
| Comparable quantities | OpenSim joint angles (knee, hip, shoulder elevation, trunk, head) vs the same angles computed from SMPL; joint positions after a per-trial root alignment |
| Metrics | The papers' metrics (angular error, joint position error, jitter), per activity and per device combination: reruns E01/E02 against real ground truth |
| Limits to state | OpenCap has its own error (markerless video), so this is model vs OpenCap, not vs truth |
