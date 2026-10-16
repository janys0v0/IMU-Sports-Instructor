# Development plan

> Step-by-step build of [`FIELD_RECORDING_DESIGN.md`](FIELD_RECORDING_DESIGN.md) §16.
> Each stage ends with **testable goals**: automated tests from [`TEST_PLAN.md`](TEST_PLAN.md)
> plus one **demo** a person can see. A stage is done only when every goal passes on two
> consecutive runs (gates G0-G10). Then the next stage starts.

## Overview

| Stage | Build | Gate | Est. working days | Where it runs |
|---|---|---|---|---|
| 0 | Test harness + timer bug fix | G0 | 2-3 | Mac |
| 0b | Risk spike: background recording (optional, recommended) | — | 1 | Devices |
| 1 | Phone recorder | G1 | 2-3 | Mac |
| 2 | Watch recording + transfer (incl. high-rate) | G2 | 3-4 | Mac + simulators |
| 3 | Mac ingest script | G3 | 2 | Mac |
| 4 | Phone preview | G4 | 2-3 | Mac + simulators |
| 5 | Spoken calibration | G5 | 3-4 | Mac + simulators |
| 6 | Keeping the app alive | G6 | 1-2 | Simulators + **first device test** |
| 7 | Watchdog + alerts | G7 | 3-4 | Mac + simulators |
| 8 | Trial button + extra sensors | G8 | 2-3 | Mac + simulators |
| 9 | Endurance + device tests | G9 | 3-4 | Simulators + devices |
| 10 | Calibration interval | G10 | 2 (two court days) | Devices |

**Total: about 26-35 working days (5-7 weeks).** Estimates assume one person coding with Claude;
device stages depend on court and weather.

## Rules for every stage

1. Branch from `main`: `feat/stage-N-<name>` (e.g. `feat/stage-1-recorder`).
2. Write the stage's tests first, watch them fail, then build until they pass.
3. One command runs all fast tests: `tools/run_tests.sh` (built in stage 0).
4. Open a pull request. Paste the gate result (test IDs + pass) into the description.
5. Squash-merge, then log the gate run in `EXPERIMENT_LOG.md` with the commit hash.

---

## Stage 0: Test harness + timer bug fix

**Goal:** all later logic can be tested on the Mac in seconds, using real recordings and fakes.

**Tasks**
1. Create the Swift package `MotionStreamerCore` (macOS, iOS, watchOS) inside `code/MotionStreamer/`.
2. Add the protocols and fakes: `MotionSource`, `Clock`, `FileStore`, `WatchLink`, `Voice`, plus settable `Battery`, `Thermal`, `AudioRoute`, `LowPower` (TEST_PLAN §0).
3. Write the replay `MotionSource`: plays a `mac_stream.jsonl` recording through the fake clock.
4. Add `code/tests/` (pytest) and `tools/run_tests.sh` (runs `swift test` + `pytest`).
5. Link the package into both app targets in `project.yml`; the app still builds.
6. Fix the calibration-timer bug (`calibrationTimer = nil` in `StreamController.stop()`), with test C1.

**Testable goals (G0)**
- [ ] `swift build` succeeds for macOS, iOS simulator and watchOS simulator.
- [ ] Replaying the 4 key recordings (TEST_PLAN §0) yields the same sample counts as the files.
- [ ] A 60-min fake-clock replay finishes in under 10 s.
- [ ] `tools/run_tests.sh` exits 0 and runs in GitHub Actions on every PR.
- [ ] **C1** passes: Stop during the countdown, Start, Calibrate → calibration runs.
- [ ] **Demo:** run `tools/run_tests.sh` and see a summary line listing every test that passed.

## Stage 0b: Risk spike: background recording (optional, recommended)

**Goal:** find out early whether the phone and AirPods keep recording with the phone app in the
background (design §7). The answer decides how stages 6 and 7 are built.

**Tasks**
1. Throwaway branch `spike/background-mirroring`; nothing is merged.
2. Minimal Watch workout with `startMirroringToCompanionDevice()` and a phone app that logs phone + AirPods motion counts to a file.
3. Lock the phone, pocket it, walk around for 20 min (design T6).

**Testable goals**
- [ ] A written result in `EXPERIMENT_LOG.md`: phone rate, AirPods rate and gaps, foreground vs background.
- [ ] A decision recorded in design §7: **mirroring** or **foreground pocket mode** as the primary method.

## Stage 1: Phone recorder

**Goal:** the phone saves everything to disk in 60 s chunks and survives crashes, with no Mac.

**Tasks**
1. Chunk writer: write per packet, `fsync` every 1 s, rotate every 60 s, SHA-256, rename `.open` → `.jsonl` (design §4).
2. Append-only `journal.jsonl` and a `manifest.json` rebuilt from it.
3. File protection `.completeUntilFirstUserAuthentication`; 2 GB free-space check at Start.
4. Record-only mode: the Mac IP becomes optional; UDP only when set.
5. Health events every 60 s (battery, thermal, Low Power, AirPods, Watch reachable).
6. Crash recovery on launch: trim the open chunk, Resume as a new segment (design §6).

**Testable goals (G1)**
- [ ] **R1-R8:** chunking, `fsync` cadence, checksums, disk-full and `fsync` failures, packet format unchanged.
- [ ] **J1-J6:** journal lines, manifest rebuild, **1,000 random crash points with zero loss of `fsync`ed data**, resume, torn journal line, clock jump.
- [ ] **S1-S3:** sample accounting; replays match E03's numbers; status-dot thresholds.
- [ ] **Demo:** in the iOS simulator, start a replayed session with no Mac IP, kill the app at 2 min, relaunch, tap Resume. The session folder shows 2 segments and no lost chunk.

## Stage 2: Watch recording + transfer

**Goal:** the Watch saves its own data and delivers every chunk to the phone exactly once.

**Tasks**
1. Watch chunk writer + journal (same code as stage 1, Watch target).
2. Send each 60 Hz chunk with `transferFile` as it closes; the phone verifies SHA-256 and acks (design §5).
3. High-rate stream: `CMBatchedSensorManager` into binary `watch_hf/` chunks (design §13), sent after the session.
4. Phone status: "Watch: N / M chunks" and "High-rate: N / M sent"; Watch "Resend session" button.
5. Watch workout-ended handling: the phone relaunches the Watch app.

**Testable goals (G2)**
- [ ] **W1-W10** with the fake link: phone unreachable for 10 min, 20 % dropped/duplicated/reordered files, corruption, lost acks, no early deletes, resend, workout end, high-rate 60 min, high-rate failure, binary format and torn-chunk trimming.
- [ ] **E3-E4** in paired simulators where supported (otherwise marked for device testing).
- [ ] **Demo:** in the simulators, block the link for 3 min mid-session; after it returns the phone shows "Watch: 10 / 10 chunks" and every SHA matches.

## Stage 3: Mac ingest script

**Goal:** one command on the Mac says whether a session is complete, and why if not.

**Tasks**
1. `receiver/ingest_field.py <session_dir>`: checksum every chunk, check all journalled chunks exist.
2. Gaps per device per segment, each with its cause from events.
3. Clock fit to Unix time (incl. Watch sync pings) and drift report.
4. Binary high-rate loader (`numpy`); `watch_hf: PENDING` when chunks are still on the Watch.
5. Write `ingest_report.json` (PASS / FAIL / PENDING) and a merged `stream.jsonl`.
6. `Shared/quality_thresholds.json` read by both Swift and Python.

**Testable goals (G3)**
- [ ] **I1-I8:** corrupt byte, missing/extra chunks, segments, clock fit (1 ms, 1 ppm), backward compatibility, all 35 recordings load, report agrees with contract fixtures, PENDING handling.
- [ ] **S4:** Swift and Python give identical PASS/WARN/FAIL on every contract fixture.
- [ ] **Demo:** run `ingest_field.py` on a simulated session with one corrupted chunk → FAIL naming that chunk; restore it → PASS, and E03 runs on the merged stream.

## Stage 4: Phone preview

**Goal:** you can see on the phone that data was saved correctly.

**Tasks**
1. Live strip: Hz, last-sample age, 🟢🟡🔴 per stream (design §8).
2. Review screen reading **closed chunks from disk**: whole-session timeline + last-60 s plots (Swift Charts, ≤ 500 points).
3. Session check card after Stop: PASS / WARN / FAIL from the shared thresholds.

**Testable goals (G4)**
- [ ] **P1-P5:** disk-only reads, peak-preserving downsampling, < 50 ms per chunk load, gap and calibration marks match the journal, snapshot tests.
- [ ] **E5:** review screen with a 10-min replayed session through the real UI.
- [ ] **Demo:** replay the reference recording; the thigh-angle plot shows the 3 squats, and an injected 5 s AirPods gap appears in the timeline.

## Stage 5: Spoken calibration

**Goal:** a person with the phone in a pocket can calibrate by voice from the Watch, and the Mac uses every calibration.

**Tasks**
1. `Shared/voice_prompts.json` with the script C1-C12 and alert phrases (design §9).
2. Calibration flow driven by speech-finished callbacks; holds start 0.3 s after "now".
3. On-phone checks: still, phone upright, arms level, all devices present, drift since last.
4. Audio session: built-in mic, `.allowBluetoothA2DP`, never `.allowBluetooth`; `audio` background mode.
5. Reminders at the interval setting (default 10 min).
6. `live/calibration.py`: many calibrations, arms-out step, slerp blend between neighbours.

**Testable goals (G5)**
- [ ] **C1-C10:** timer regression, clean run, moving, arms not level, each fail reason, reminders, agreement with `calibration.py` within 0.5°, blend removes 8°/min drift to within 1°, piecewise across segments, interval setting.
- [ ] **V1-V9:** script lint, phrase order and timing, prompts logged, priority, output fallback, repeat, mic route, audibility check, and a **listen-through signed off by both of you**.
- [ ] **Demo:** play the generated audio of a full calibration on the Mac speaker; follow it standing up without looking at a screen.

## Stage 6: Keeping the app alive

**Goal:** recording continues with the phone locked in a pocket for a full hour.

**Tasks**
1. Workout mirroring from the Watch; phone `workoutSessionMirroringStartHandler` (or the stage 0b decision).
2. Foreground pocket mode as the fallback, chosen automatically if mirroring fails.
3. App lifecycle events logged and followed by `fsync`.

**Testable goals (G6)**
- [ ] Simulated parts of **E1-E2** pass.
- [ ] **Device test T6:** 20 min, phone locked in a pocket → phone and AirPods continuous (or the fallback is recorded as primary).
- [ ] **Demo:** walk for 20 min with the phone locked; the review screen afterwards shows no gap.

## Stage 7: Watchdog + alerts

**Goal:** problems are found within seconds, fixed automatically where possible, and spoken otherwise.

**Tasks**
1. Go/No-Go screen: devices, rates, battery for planned minutes, disk, Low Power, signing days left, audibility check.
2. Per-second watchdog with the scenario tables (design §10): detect → log → auto-fix → alert.
3. Spoken alerts with debounce (2 s), escalation (30 s) and Watch acknowledge.
4. Trial check after each trial; court-exit check (60 Hz chunks on phone, high-rate closed on Watch).

**Testable goals (G7)**
- [ ] **A1-A13:** every fault in the scenario tables produces the right event, fix and alert; no false "phone dropped" during jumping jacks; debounce and escalation; trial check; court-exit check with and without high-rate chunks still on the Watch.
- [ ] **Demo:** replay a session with a scripted AirPods disconnect; hear "Stop. The AirPods disconnected." within 3 s, then "The AirPods are back" after reconnect.

## Stage 8: Trial button + extra sensors

**Goal:** trials are marked and checked; barometer, magnetometer and audio level are recorded.

**Tasks**
1. Trial button on the Watch (large, one tap) and the sync gesture detector.
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
2. Check every exit criterion in TEST_PLAN §3 (coverage ≥ 85 %, recorder/journal ≥ 95 %).
3. Device tests T1-T19 and T21 (design §15), on a court where needed.

**Testable goals (G9)**
- [ ] **L1-L3:** 60 and 120 min sessions with flat memory; 120 random faults with zero silent loss.
- [ ] TEST_PLAN §3 exit criteria all met.
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
