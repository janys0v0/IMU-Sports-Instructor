# Data collection plan: addendum to FIELD_RECORDING_DESIGN.md

> **Status (2026-10-14):** plan only, nothing implemented. Most of the data collection plan is
> already in [`FIELD_RECORDING_DESIGN.md`](FIELD_RECORDING_DESIGN.md). This addendum adds what
> it does not cover: the **extra sensors** named in the project proposal and **study logistics**.
> **OpenCap ground truth and merging (§2A-B) are deferred:** not part of data collection for now.
> Testing before devices: [`TEST_PLAN.md`](TEST_PLAN.md).

## 1. What is already planned (FIELD_RECORDING_DESIGN.md)

| Need | Where | In short |
|---|---|---|
| Save in segments, never lose the session | §2, §4 | 60 s chunk files, `fsync` every 1 s, append-only journal, SHA-256 per chunk |
| Long sessions with the phone in a pocket | §5, §7 | Watch writes its own chunks and sends each one as it closes; workout mirroring keeps the phone app alive |
| Crash recovery | §6 | Resume on relaunch; segments keyed by (segment, sample index) |
| **See each IMU's curves on the phone** | §8 | Live status strip, review screen plotting the last 60 s per device **from disk**, end-of-session PASS/WARN/FAIL card |
| Keep checking quality during recording | §8, §10 | Status dots, a per-second watchdog, spoken alerts (haptics as backup), per-trial keep/redo check, court-exit check |
| Calibration that holds | §9 | Standing pose + arms-out pose started from the Watch, **every step spoken** (fixes the E02 arm issue); recalibrate at the interval measured in T20 (default 10 min until then) |
| Spoken alerts | §10 | Every 🔴 problem and trial redo announced in plain words; haptics as backup |
| Design review | §17 | Feasibility, usability, what was missing |
| Copy, verify, back up | §11 | `ingest_field.py`, then back up, then clear the devices |
| Trials and sync | §12 | Trial button + "3 hops, 3 nods" gesture (OpenCap parts deferred) |
| High-rate Watch stream | §13 | 800 Hz acceleration + 200 Hz motion, always on, binary chunks, transferred after the session |
| Failure tests | §15 | T1-T21 before the first field day (T20 last) |

Today's app has none of this yet (the only on-device copy is one `stream.jsonl` per session).
Fix the calibration-timer bug first (EXPERIMENT_LOG, 2026-10-08).

## 2. Additions

### A. OpenCap ground truth: *deferred*

> Not part of data collection for now. Kept here so the plan is ready when comparison starts.

OpenCap (class kit) is **2 iPhone 12 Pros on tripods ≥ 8 ft apart + a checkerboard**, run
from the OpenCap web app on a laptop. It needs **good light, a plain high-contrast background
and stable internet**; kinematics come back from the cloud **hours to a day later**.

| Topic | Plan |
|---|---|
| **Where** | Ground truth only exists **inside the camera volume**. Record IMU sessions as long as you like, but embed **short OpenCap trials** (30-120 s each) in them. Pilot indoors (lab, white wall) before trying a court. |
| **Separate phones** | The two OpenCap iPhones are cameras only; the IMU iPhone stays in the pocket. Charge all four devices; the OpenCap phones also need to stay online. |
| **Session order** | OpenCap checkerboard → OpenCap **neutral pose** → **IMU calibration (standing + arms-out pose) immediately after, facing the same way** → trials. Repeat the IMU calibration before every OpenCap trial block. |
| **Trial names** | One naming scheme in both systems: `<IMU session>_T03_squats`. The app's "OpenCap trial" button records the same name, the Unix time and a note. |
| **Visual slate** *(new)* | At trial start, the app shows a full-screen slate (session ID, trial #, Unix time to ms, a flashing square) toward a camera for 2 s. It gives frame-accurate sync in the video and a readable label. |
| **Sync** | Slate + "3 hops" gesture → coarse alignment (± 1 frame from the slate); then refine by cross-correlating IMU vertical acceleration with OpenCap pelvis height. Log the residual offset per trial. |
| **Subject data** | Height and mass (OpenCap asks for them; reuse them to scale the SMPL body), handedness, shoe and pocket type. |
| **Download and archive** | Per OpenCap session: videos, marker trajectories, OpenSim model and joint kinematics, session metadata. Keep them in `recordings/<session>/opencap/`, untouched. |

### B. Merging and comparison (Mac): *deferred*

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

### C. Extra sensors the proposal names

The proposal's hypothesis is that "light, pressure, magnetometer, and audio cues" reduce drift.
Log them from the start so they exist when the models need them.

| Sensor | Plan | Note |
|---|---|---|
| Barometer (phone + Watch) | `CMAltimeter` relative altitude + pressure, about 1 Hz | Height and squat depth (BaroPoser) |
| Magnetometer (phone + Watch) | Calibrated field + accuracy from device motion | Heading drift and court-fence disturbance |
| Audio (phone) | **Level and onset times only, no raw audio.** Phone's **built-in microphone only**, never the AirPods mic (it would switch them to call mode; design §9 voice rules) | Ball strikes, footsteps, sync claps; avoids recording speech |
| Light | Not readable by apps (the ambient light sensor has no public API) | Use the cameras or drop it from the hypothesis |
| Watch ↔ phone UWB distance | Optional, via Nearby Interaction | Drift-free arm-reach constraint |

Use new packet types, so today's 14-value motion samples stay unchanged.

### D. Study logistics and data handling

- **Consent:** participants are only the two of us (decided 2026-10-14), so no consent step now. If anyone else is recorded later (or video once OpenCap returns), get consent first and check whether IRB-style approval is needed.
- **Identifiers:** participant codes (`P01`) in all files; names only on a separate sheet.
- **Metadata per session:** app version, device models and OS, placement photos, subject data (A), weather or room, OpenCap session ID.
- **Pre-session dry run:** a 30 s "test mode" that records, runs the session check and discards. Use it before every session.
- **Closure test:** end every session with the same calibration + sync gesture as the start. It measures drift over the whole session for free.

## 3. Order of work

Follows the design's build order (§16), each step gated on its tests (`TEST_PLAN.md` §5):

1. ⓪ Test harness and simulated tests, then the calibration-timer fix.
2. ① Phone recorder → ② Watch chunks **with the high-rate stream** → ③ ingest → ④ phone preview → ⑤ spoken calibration.
3. ⑥ Keeping the app alive (device test T6 first) → ⑦ watchdog and spoken alerts.
4. ⑧ Trial button + sync **and the extra sensors (C)** as new packet types.
5. Device tests T1-T19 and T21, then T20 (sets the calibration interval), then long sessions.
   OpenCap (A-B) when ground-truth comparison starts.
