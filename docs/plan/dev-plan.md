# Development plan

How [`design.md`](design.md) gets built: stages in order, each ending with **testable goals**
(tests from [`test-plan.md`](test-plan.md) plus one demo a person can see). A stage is done only
when its gate passes on two consecutive runs; then the next stage starts.

## Status

<!-- Update at the start and end of every work session (see CONTRIBUTING.md, "Development loop"). -->

| | |
|---|---|
| **Current stage** | 8 — Trial button + extra sensors (stages 0-7 done; stage 6's gate waits for device test T6) |
| **Next action** | Trial button on the Watch with the trial check and court-exit check in the app (stage 8, task 1) |
| **Blocked on** | Devices: stage 0b check (= T6) closes stage 6's gate and the keep-alive decision · People: V9 listen-through |
| **Open decision** | iPhone keep-alive method, decided after stage 0b ([`decisions.md`](decisions.md#open)) |
| **Last updated** | 2026-10-16 |

## Overview

| Stage | Build | Already built | Gate | Est. working days | Where it runs |
|---|---|---|---|---|---|
| 0 | Test harness + timer bug fix | Python replay + fake packets | G0 | 2-3 | Mac |
| 0b | Early device check: AirPods in the background (~1 hour) | — | — | 0.5 | Devices |
| 1 | Phone recorder | ◐ single-file copy, sample indices, events | G1 | 2 | Mac |
| 2 | Watch recording + transfer (incl. high-rate) | ◐ workout, auto-launch, 10 s retry buffer | G2 | 3-4 | Mac + simulators |
| 3 | Mac ingest script | ◐ coverage PASS/FAIL, exact gaps, clock mapping | G3 | 1-2 | Mac |
| 4 | Phone preview | ◐ live per-stream rate, coverage, missing | G4 | 2 | Mac + simulators |
| 5 | Spoken calibration | ◐ countdown + buzz calibration, Mac calibration | G5 | 3 | Mac + simulators |
| 6 | Keeping the app alive | ◐ pocket mode (fallback) | G6 | 1 | Simulators + **first device test** |
| 7 | Watchdog + alerts | ◐ AirPods check screen, connect/disconnect events | G7 | 3 | Mac + simulators |
| 8 | Trial button + extra sensors | ◐ Trial marker on the phone | G8 | 2 | Mac + simulators |
| 9 | Endurance + device tests | 35 real recordings to replay | G9 | 3-4 | Simulators + devices |
| 10 | Calibration interval | — | G10 | 2 (two court days) | Devices |

◐ = partly built (details below). **Total: about 22-29 working days (4-6 weeks).** Estimates
assume one person coding with Claude; device stages depend on court and weather.

## What already exists

The app already records all three devices and has been used for 35 sessions. These parts are
**reused, not rebuilt**: stage 0 moves them into the testable package, and later stages extend them.

| Feature | Where | Status | Used in stage |
|---|---|---|---|
| Phone + Watch + AirPods motion, 14-value packets with `seq` / `first_index` | `Shared/MotionFormat.swift`, `iOS/StreamController.swift` | ✅ works, 35 recordings | 1 (format kept, R8) |
| On-phone copy of each session (`stream.jsonl` + `manifest.json`) | `iOS/SessionRecorder.swift` | ◐ one file, no `fsync`, manifest only at Stop | 1 (replaced by chunks + journal) |
| Watch workout session keeps the Watch app running | `Watch/WatchStreamer.swift` | ✅ | 2 |
| Phone starts the Watch app (`startWatchApp`) and sends start/stop | `iOS/StreamController.swift` | ✅ | 2, 7 (relaunch on workout end) |
| Watch → phone batches with a 10 s retry buffer, dropped-sample count | `Watch/WatchStreamer.swift` | ◐ data lost after 10 s | 2 (becomes preview only) |
| Clock-sync pings phone ↔ Watch every 5 s | `iOS/StreamController.swift` | ✅ | 3 (clock fit) |
| Events: start, stop, calibrate, marker, Watch and AirPods status | `iOS/StreamController.swift` | ✅ | 1-8 |
| Live per-stream rate, nominal rate, coverage, missing, last-packet age | `StreamCounter` in `iOS/StreamController.swift`, `iOS/ContentView.swift` | ◐ no dots or thresholds | 4 (live strip) |
| Calibrate button: 10 s countdown, 3 s hold, buzzes | `iOS/StreamController.swift` | ◐ screen + buzz only; **Stop-during-countdown bug** | 0 (bug), 5 (spoken flow) |
| Trial marker button | `iOS/ContentView.swift` | ◐ phone only, no trial check | 8 (Watch button, trial check) |
| Pocket mode (proximity sensor) + auto-lock off | `iOS/ContentView.swift`, `iOS/StreamController.swift` | ✅ | 6 (fallback) |
| AirPods check: connection, rate, live head angles | `iOS/HeadphoneMonitor.swift` | ✅ | 7 (Go/No-Go) |
| Setup: participant, activity, wrist, pocket screen direction | `iOS/ContentView.swift` | ✅ | 7 (settings check) |
| Mac receiver: per-stream coverage, `summary.json`, PASS/FAIL | `pipeline/live/receiver.py` | ◐ live UDP only, no checksums | 3 |
| Exact missing samples (by index), gaps > 100 ms, delay, clock mapping | `experiments/common/stream_quality.py` (E03) | ✅ | 3 (reused in ingest), S2 baseline |
| Recording loader, 30 Hz resampling with gap marks | `pipeline/preprocessing/motion_io.py`, `pipeline/preprocessing/resample.py` | ✅ | 3 (merged stream must load here) |
| Standing calibration + checks on the Mac | `pipeline/preprocessing/calibration.py` | ◐ one calibration only, no arms-out pose | 5 |
| Replay a recording over UDP; synthetic packets | `pipeline/live/send_recording.py`, `pipeline/live/fake_phone.py` | ✅ | 0 (basis for replay fakes) |

## Human testing: what blocks and what waits

Online research ([`device-research.md`](../research/device-research.md)) answered most device questions.

| When | Human tests | Blocking? |
|---|---|---|
| **Stage 0b (early)** | One ~1-hour device check: phone + AirPods motion with the phone locked (background location keep-alive), speech through the AirPods, Watch high-rate stream, battery | **Yes**, for stage 6: AirPods motion in the background is undocumented |
| Within stages 1, 2, 4, 8 | Simulator demos (5-15 min each) | Only for that stage's gate |
| Within stage 5 | V9 listen-through of the spoken script on the Mac (10 min) | Only for G5 |
| **Stage 9 (end)** | All device tests T1-T19, T21, in one or two court sessions | No: everything before is simulated |
| After the first field session | T20 (how long calibration holds); 10-min default until then | No |

- **Run every background test launched from the Home screen with Xcode detached.** With the
  debugger attached, iOS never suspends the app, so the test passes falsely.
- **Workout mirroring can't be simulated** (Apple DTS); any mirroring checks are device-only.
- Free Apple ID builds expire after 7 days: plan device rounds right after a rebuild.

## How to work through a stage

Follow the development loop in [`CONTRIBUTING.md`](../../CONTRIBUTING.md#development-loop): read
**Status** → implement on `feat/stage-N-<name>` (tests first) → `tools/check.sh` → update Status →
push. Merge when the stage's gate passes twice in a row.

---

## Stage 0: Test harness + timer bug fix

**Goal:** all later logic can be tested on the Mac in seconds, using real recordings and fakes.

**Already there:** Python replay (`send_recording.py`) and synthetic packets (`fake_phone.py`); the Swift side has no tests yet.

**Tasks**
1. Create the Swift package `MotionStreamerCore` (macOS, iOS, watchOS) inside `apps/MotionStreamer/`.
2. Add the protocols and fakes: `MotionSource`, `Clock`, `FileStore`, `WatchLink`, `Voice`, plus settable `Battery`, `Thermal`, `AudioRoute`, `LowPower` (test-plan §0).
3. Write the replay `MotionSource`: plays a `mac_stream.jsonl` recording through the fake clock.
4. Add `tests/` (pytest) and `tools/run_tests.sh` (runs `swift test` + `pytest`).
5. Move the existing logic (`StreamCounter`, packet encoding, calibration timer) into the package behind the protocols; link the package into both app targets in `project.yml`. The app still records exactly as before.
6. Fix the calibration-timer bug (`calibrationTimer = nil` in `StreamController.stop()`), with test C1.

**Testable goals (G0)**
- [x] `swift build` succeeds for macOS, iOS simulator and watchOS simulator.
- [x] Replaying the 4 key recordings (test-plan §0) yields the same sample counts as the files.
- [x] A 60-min fake-clock replay finishes in under 10 s.
- [x] `tools/run_tests.sh` exits 0 and runs in GitHub Actions on every PR.
- [x] **C1** passes: Stop during the countdown, Start, Calibrate → calibration runs.
- [x] **No change in behaviour:** every packet of the reference recording, rebuilt by the moved encoder, has identical keys and values (JSON key order was never fixed).
- [x] **Demo:** run `tools/run_tests.sh` and see a summary line listing every test that passed.

## Stage 0b: Early device check (~1 hour, blocking for stage 6)

**Goal:** answer the one question research couldn't: do the AirPods keep streaming while the phone
app is locked in a pocket and kept awake in the background? Also confirm the research findings on
our own devices (test T6 in [`test-plan.md`](test-plan.md) §4).

**Tasks**
1. Throwaway branch `spike/background-check`; nothing is merged.
2. Phone app: background location at 3 km accuracy + phone motion + AirPods motion, counts logged to a file. Speak a short phrase through the AirPods every 30 s.
3. Watch app: workout + `CMBatchedSensorManager` (800 / 200 Hz), counts logged.
4. Launch from the Home screen (**Xcode detached**), lock the phone, pocket it, walk for 20 min.

**Testable goals**
- [ ] Phone and AirPods: ≥ 95 % of expected samples while locked.
- [ ] AirPods rate unchanged in the seconds around each spoken phrase.
- [ ] Watch: ≈ 800 accelerometer and 200 motion samples per second.
- [ ] Battery % used per device in 20 min, written down.
- [ ] Result in `EXPERIMENT_LOG.md`, and the keep-alive decision recorded in [`decisions.md`](decisions.md) and design §5. If AirPods stop in the background: pocket mode (app in the foreground, screen off) for sessions that need them.

## Stage 1: Phone recorder

**Goal:** the phone saves everything to disk in 60 s chunks and survives crashes, with no Mac.

**Already there:** the session copy (`SessionRecorder`), sample indices and events. Replace the single file with chunks + journal; keep the packet format.

**Tasks**
1. Chunk writer: write per packet, `fsync` every 1 s, rotate every 60 s, SHA-256, rename `.open` → `.jsonl` (design §2).
2. Append-only `journal.jsonl` and a `manifest.json` rebuilt from it.
3. File protection `.completeUntilFirstUserAuthentication`; 2 GB free-space check at Start.
4. Record-only mode: the Mac IP becomes optional; UDP only when set.
5. Health events every 60 s (battery, thermal, Low Power, AirPods, Watch reachable).
6. Crash recovery on launch: trim the open chunk, Resume as a new segment (design §4).

**Testable goals (G1)**
- [x] **R1-R8:** chunking, `fsync` cadence, checksums, disk-full and `fsync` failures, packet format unchanged.
- [x] **J1-J6:** journal lines, manifest rebuild, **1,000 random crash points with zero loss of `fsync`ed data**, resume, torn journal line, clock jump.
- [x] **S1-S3:** sample accounting; replays match E03's numbers; status-dot thresholds.
- [x] **Demo:** in the iOS simulator, start a replayed session with no Mac IP, kill the app at 2 min, relaunch, tap Resume. The session folder shows 2 segments and no lost chunk.

## Stage 2: Watch recording + transfer

**Goal:** the Watch saves its own data and delivers every chunk to the phone exactly once.

**Already there:** the workout session, auto-launch from the phone, batching and the 10 s retry buffer (kept as the live preview).

**Tasks**
1. Watch chunk writer + journal (same code as stage 1, Watch target).
2. Send each 60 Hz chunk with `transferFile` as it closes; the phone verifies SHA-256 and acks (design §3).
3. High-rate stream: `CMBatchedSensorManager` into binary `watch_hf/` chunks (design §2), sent after the session.
4. Phone status: "Watch: N / M chunks" and "High-rate: N / M sent"; Watch "Resend session" button.
5. Watch workout-ended handling: the phone relaunches the Watch app.

**Testable goals (G2)**
- [x] **W1-W10** with the fake link: phone unreachable for 10 min, 20 % dropped/duplicated/reordered files, corruption, lost acks, no early deletes, resend, workout end, high-rate 60 min, high-rate failure, binary format and torn-chunk trimming.
- [x] **E3-E4** marked for device testing (stage 9): real WatchConnectivity file transfer and HealthKit workouts need a paired Watch; the fake link covers the logic.
- [x] **Demo (simulated):** test W1 blocks the link for 10 min; after it returns every closed chunk arrives with a matching SHA (on devices: T2).

## Stage 3: Mac ingest script

**Goal:** one command on the Mac says whether a session is complete, and why if not.

**Already there:** coverage PASS/FAIL (`pipeline/live/receiver.py`), exact missing samples, gaps and clock mapping (`stream_quality.py`). Reuse them; add checksums, segments and the report.

**Tasks**
1. `pipeline/ingest/ingest_field.py <session_dir>`: checksum every chunk, check all journalled chunks exist.
2. Gaps per device per segment, each with its cause from events.
3. Clock fit to Unix time (incl. Watch sync pings) and drift report.
4. Binary high-rate loader (`numpy`); `watch_hf: PENDING` when chunks are still on the Watch.
5. Write `ingest_report.json` (PASS / FAIL / PENDING) and a merged `stream.jsonl`.
6. `Shared/quality_thresholds.json` read by both Swift and Python.

**Testable goals (G3)**
- [x] **I1-I8:** corrupt byte, missing/extra chunks, segments, clock fit (1 ms, 1 ppm), backward compatibility, all 35 recordings load, report agrees with contract fixtures, PENDING handling.
- [x] **S4:** Swift and Python give identical PASS/WARN/FAIL on every contract fixture.
- [x] **Demo:** `ingest_field.py` on the session the app wrote in the simulator (stage 1 demo): one flipped byte → FAIL naming `phone/000001.jsonl`; restored → WARN (the replayed recording has real gaps), merged stream loads. E03's numbers come out identical on a re-chunked reference session (I5).

## Stage 4: Phone preview

**Goal:** you can see on the phone that data was saved correctly.

**Already there:** live rate, coverage, missing and last-packet age per stream. Add the dots and thresholds; the review screen and session card are new.

**Tasks**
1. Live strip: add 🟢🟡🔴 per stream from `quality_thresholds.json` to the existing status numbers (design §6).
2. Review screen reading **closed chunks from disk**: whole-session timeline + last-60 s plots (Swift Charts, ≤ 500 points).
3. Session check card after Stop: PASS / WARN / FAIL from the shared thresholds.

**Testable goals (G4)**
- [x] **P1-P5:** disk-only reads, peak-preserving downsampling, < 50 ms per chunk load, gap and calibration marks match the journal, snapshot tests.
- [x] **E5:** review screen through the real UI in the iOS simulator, with the longest available recording (5.2 min, replayed): 5 saved chunks read from disk and plotted.
- [x] **Demo:** the reference recording with a 5 s AirPods gap cut in: the thigh-angle plot shows the 3 squats and the gap shows in the timeline (test `ReviewDemoTests`).

## Stage 5: Spoken calibration

**Goal:** a person with the phone in a pocket can calibrate by voice from the Watch, and the Mac uses every calibration.

**Already there:** the countdown-and-hold calibration with `calibrate` events (bug fixed in stage 0), and the standing calibration in `pipeline/preprocessing/calibration.py`. Speech, the arms-out pose, Watch start and multi-calibration are new.

**Tasks**
1. `Shared/voice_prompts.json` with the script C1-C12 and alert phrases (design §7).
2. Calibration flow driven by speech-finished callbacks; holds start 0.3 s after "now".
3. On-phone checks: still, phone upright, arms level, all devices present, drift since last.
4. Audio session: built-in mic, `.allowBluetoothA2DP`, never `.allowBluetooth`; `audio` background mode.
5. Reminders at the interval setting (default 10 min).
6. `pipeline/preprocessing/calibration.py`: many calibrations, arms-out step, slerp blend between neighbours.

**Testable goals (G5)**
- [x] **C1-C10:** timer regression, clean run, moving, arms not level, each fail reason, reminders, agreement with `calibration.py` within 0.5°, blend removes 8°/min drift to within 1°, piecewise across segments, interval setting.
- [x] **V1-V8:** script lint, phrase order and timing, prompts logged, priority, output fallback, repeat, mic route, audibility check.
- [ ] **V9 (people):** listen-through of `data/voice/voice_sample.m4a` (made by `tools/make_voice_sample.py`) signed off by both of you. Not blocking the code stages; wording changes go in `voice_prompts.json`.
- [ ] **Demo (people):** play `data/voice/voice_sample.m4a` on the Mac speaker and follow the calibration standing up, without looking at a screen.

## Stage 6: Keeping the app alive

**Goal:** recording continues with the phone locked in a pocket for a full hour.

**Already there:** pocket mode with the proximity sensor and auto-lock off; it becomes the fallback.

**Tasks** (keep-alive from design §5, decided after stage 0b)
1. Background location keep-alive (3 km accuracy, `location` background mode, When In Use permission).
2. Optional: workout mirroring, started only after the Watch session is prepared (works around the iOS 26 mirroring bug).
3. Switch to the existing pocket mode automatically if the app is about to be suspended or AirPods stop.
4. Watch: add `audio` to `WKBackgroundModes`; use `handleActiveWorkoutRecovery()` after a Watch crash.
5. App lifecycle events logged and followed by `fsync`.

**Testable goals (G6)**
- [x] Simulated parts: the keep-alive policy (4 tests) and E2 (kill and Resume through the real UI, stage 1 demo); E1's full flow runs in stage 8.
- [ ] **Device test T6** (Xcode detached): 20 min, phone locked in a pocket → phone and AirPods continuous (or the fallback is recorded as primary).
- [ ] **Demo:** walk for 20 min with the phone locked; the review screen afterwards shows no gap.

## Stage 7: Watchdog + alerts

**Goal:** problems are found within seconds, fixed automatically where possible, and spoken otherwise.

**Already there:** the AirPods check screen (connection, rate, head angles) and AirPods / Watch status events. Reuse the check screen inside Go/No-Go.

**Tasks**
1. Go/No-Go screen: devices, rates, battery for planned minutes, disk, Low Power, signing days left, audibility check.
2. Per-second watchdog with the scenario tables (design §8): detect → log → auto-fix → alert.
3. Spoken alerts with debounce (2 s), escalation (30 s) and Watch acknowledge.
4. Trial check after each trial; court-exit check (60 Hz chunks on phone, high-rate closed on Watch).

**Testable goals (G7)**
- [x] **A1-A13:** every fault in the scenario tables produces the right event, fix and alert; no false "phone dropped" during jumping jacks; debounce and escalation; trial check; court-exit check with and without high-rate chunks still on the Watch.
- [x] **Demo:** the reference recording replayed second by second with the AirPods cut from 20-28 s: "Stop. The AirPods disconnected." at 22 s, "The AirPods are back." at 29 s (`WatchdogDemoTests`).

## Stage 8: Trial button + extra sensors

**Goal:** trials are marked and checked; barometer, magnetometer and audio level are recorded.

**Already there:** the phone's Trial marker button and `marker` events. Move it to the Watch; the sensors are new.

**Tasks**
1. Trial button on the Watch (large, one tap), sending the existing `marker` event; add the sync gesture detector.
2. New packet types: barometer (~1 Hz), magnetometer field + accuracy, audio level + onsets (no raw audio), optional UWB distance.
3. `motion_io.py` and `ingest_field.py` accept the new packets without breaking old recordings.

**Testable goals (G8)**
- [ ] **A11-A13** again, now with real trials.
- [ ] **X1-X4:** barometer, magnetometer, audio level with no raw audio stored, old recordings still load.
- [ ] **E1:** full simulator flow Setup → Go/No-Go → Start → Calibrate → 3 trials → Stop.
- [ ] **Demo:** run E1 and open the session check card: 3 trials ✅ and the barometer trace on the review screen.

## Stage 9: Endurance + device tests

**Goal:** the whole system holds up for 60+ minutes on real devices.

**Tasks**
1. Endurance runs in the simulators (L1-L3).
2. Check every exit criterion in test-plan §3 (coverage ≥ 85 %, recorder/journal ≥ 95 %).
3. Device tests T1-T19 and T21 (test-plan §4), on a court where needed.

**Testable goals (G9)**
- [ ] **L1-L3:** 60 and 120 min sessions with flat memory; 120 random faults with zero silent loss.
- [ ] test-plan §3 exit criteria all met.
- [ ] **T1-T19, T21** pass on devices; results logged in `EXPERIMENT_LOG.md`.
- [ ] **Demo:** the full 60-min tennis rehearsal (T7) ingests as **PASS** on the Mac the same day.

## Stage 10: Calibration interval

**Goal:** a measured, not guessed, recalibration interval.

**Tasks**
1. Device test T20 on 2 days: calibrate once, play, stand in the calibration pose every 5 min without recalibrating.
2. Compute per-device drift at each check.

**Testable goals (G10)**
- [ ] T20 run on 2 days and logged.
- [ ] Interval = time until any device exceeds 10°, rounded down to whole minutes; set as the reminder default.
- [ ] **Demo:** a drift-over-time plot per device, with the chosen interval marked.

**After stage 10: first real field session.**
