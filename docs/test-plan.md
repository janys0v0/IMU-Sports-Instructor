# Test plan

**Goal:** find every bug possible on the Mac and in the simulators, so device time goes only to
what needs hardware. Covers [`design.md`](design.md) and the Mac pipeline; OpenCap is out of scope.
Which tests gate which build stage: [`dev-plan.md`](dev-plan.md). Today the app has no tests and
calls Core Motion, WatchConnectivity, timers and files directly, so §0 comes first.

## 0. Make the app testable (prerequisite)

Move all logic out of the app targets into a **Swift package, `MotionStreamerCore`**, that builds
on macOS, iOS and watchOS. The app targets become thin shells. Every outside dependency goes behind
a small protocol with a real and a fake version:

| Seam (protocol) | Real (on device) | Fake (in tests) |
|---|---|---|
| `MotionSource` | Core Motion (phone, Watch), headphone motion (AirPods) | **Replay** of a real recording · **synthetic** generator (sine, still, jumps, gaps, frozen, saturated) |
| `Clock` | system uptime / wall clock | manual clock: tests move time forward instantly (a 60-min session runs in seconds) |
| `FileStore` | files + `fsync` | in-memory store that can **fail on command**: disk full, write error, `fsync` error, crash after N bytes |
| `WatchLink` | WatchConnectivity | in-memory link that can **drop, delay, duplicate, reorder** messages and files |
| `Voice` | `AVSpeechSynthesizer` | **recorder** that logs each phrase with start/finish times (no audio) |
| `Haptics`, `Battery`, `Thermal`, `AudioRoute`, `LowPower` | system APIs | settable values |

With these, the same core code runs in three places: `swift test` on the Mac (fastest), the
iOS + watchOS simulators, and the devices.

**Test data:**
- **35 real recordings** in `code/recordings/` (`mac_stream.jsonl` each), replayed through `MotionSource`. Key fixtures:
  - `20261008-153213-P01`: reference routine, all 3 devices.
  - `20261008-153037-P01`: no calibrate events (the timer bug).
  - `20261008-152437-P01`: AirPods start after the first calibration.
  - `20261008-150130-P01`: 4 min, AirPods with 1 s gaps.
- A **synthetic generator** for cases the recordings don't contain (long sessions, rare faults, exact known drift).

## 1. Test levels

| Level | Where | Runs | Time |
|---|---|---|---|
| **L1 Unit** | Mac, `swift test` + `pytest` | every change | < 1 min |
| **L2 Component** | Mac, core package with fakes wired together | every change | ~2 min |
| **L3 Replay + fault injection** | Mac, real recordings + scripted faults, fake clock | every change | ~5 min |
| **L4 Simulator end-to-end** | Paired iPhone + Watch simulators, UI tests, replayed motion | daily / before merging | ~15 min |
| **L5 Endurance** | Mac + simulators, time-compressed 60-120 min sessions | before each device round | ~20 min |
| **L6 Mac pipeline** | `pytest`: ingest, compatibility, experiments | every change to Python | ~3 min |
| **L7 Device** | Real devices: T1-T21 (§4) | stage 0b and stage 9 | hours |

One command runs L1-L3 and L6: `tools/run_tests.sh` (to add). Record results in `EXPERIMENT_LOG.md` before each device round.

## 2. Test cases

IDs are stable so failures can be referenced. "Pass" is what must be true.

### R: Recorder (design §2)

| ID | Test | Pass |
|---|---|---|
| R1 | Write 3 min of replayed data | 3 closed chunks + 1 open; every packet in exactly one chunk; sample indices continuous across chunk boundaries |
| R2 | `fsync` cadence | One `fsync` per second while recording, one at each chunk close |
| R3 | Chunk close | SHA-256 in the journal matches the file; file renamed `.open` → `.jsonl`; never written again |
| R4 | Disk full mid-chunk | Chunk closed, `write_error` event, new chunk attempted, 🔴 alert spoken; **no silent loss** |
| R5 | `fsync` fails | Same as R4 |
| R6 | Free space below 2 GB at Start | Start blocked with the reason |
| R7 | File protection attribute | `.completeUntilFirstUserAuthentication` on every file |
| R8 | Packet format | Every line parses with today's `live/motion_io.py` unchanged |

### J: Journal and recovery (design §2, §4)

| ID | Test | Pass |
|---|---|---|
| J1 | Every state change | One journal line each (open, chunk_closed, health every 60 s, close) |
| J2 | Rebuild `manifest.json` from the journal | Matches the live manifest |
| J3 | **Crash at a random byte** (property test, 1,000 random crash points) | Recovered data = everything that was `fsync`ed; the `.open` chunk is trimmed to its last full line |
| J4 | Resume after crash | Same session ID, segment + 1, chunk numbers continue, indices restart at 0 |
| J5 | Torn last journal line | Ignored with a warning; everything before it is kept |
| J6 | Clock jump / reboot (`boot_to_unix` changes) | New segment, logged |

### W: Watch storage and transfer (design §2, §3)

| ID | Test | Pass |
|---|---|---|
| W1 | Watch writes chunks with the phone unreachable for 10 min | All Watch data on Watch "disk"; preview gap logged |
| W2 | Transfer with 20 % of files dropped, delayed, duplicated, reordered | Phone ends with every chunk exactly once, SHA verified; "Watch: 60 / 60 chunks" |
| W3 | Corrupted file in transit | Phone rejects it and requests it again |
| W4 | Ack lost | Watch re-sends; phone treats the duplicate as already received |
| W5 | Watch never deletes before Mac verification | Files remain after acks |
| W6 | "Resend session" button | All chunks sent again, duplicates harmless |
| W7 | Watch workout ends (fake HealthKit state) | Phone asks the Watch to relaunch; gap logged; 🔴 spoken |
| W8 | High-rate stream (synthetic 800 Hz + 200 Hz) for 60 min, fake clock | `watch_hf/` chunks complete, indices continuous, ~100 MB/h; **not sent during play**, transferred only after the session |
| W9 | High-rate stream fails to start / stops mid-session | 🔴 at Go/No-Go / spoken 🔴 mid-session; 60 Hz stream unaffected |
| W10 | Binary high-rate chunk format (design §2) | Header line + fixed-size records; crash at random bytes → chunk trimmed to its last whole record; Swift writer → Python loader round-trips every value exactly; SHA-256 and journal as for JSON chunks |

### S: Sample accounting and quality (design §6, §8)

| ID | Test | Pass |
|---|---|---|
| S1 | Index gaps, duplicates, backwards timestamps (synthetic) | Counted exactly; duplicates dropped on the Mac, kept raw |
| S2 | **Replay the 4 key recordings** | Rate, coverage, missing samples and gaps match E03's numbers for those sessions |
| S3 | Status dots | Each threshold in `quality_thresholds.json` flips the dot at exactly its value |
| S4 | **Contract test:** same fixture through Swift and Python checks | Identical PASS/WARN/FAIL and numbers (thresholds file shared) |

### C: Calibration (design §7)

| ID | Test | Pass |
|---|---|---|
| C1 | **Timer bug regression:** Stop during the countdown, Start, Calibrate | Calibration runs (it fails today) |
| C2 | Still standing + arms-out (synthetic, all devices) | ✅ pass; windows start 0.3 s after "now" finishes speaking |
| C3 | Moving during a hold | "You moved. Hold still." spoken once, hold restarts; after 2 failed retries the final message |
| C4 | Arms not level after 6 s | C8 prompt spoken, then proceeds when level |
| C5 | Each fail reason (phone not upright, AirPods missing, Watch silent, arms not level) | Correct reason phrase in the result |
| C6 | Reminder | Spoken once the reminder interval (default 10 min) passes without calibration and after each trigger event; repeats every 2 min |
| C7 | Replay `20261008-153213-P01` calibration window | On-phone check agrees with `live/calibration.py` (same pass/fail, rotation within 0.5°) |
| C8 | Mac multi-calibration blend with **injected known drift** (linear yaw drift 8°/min) | Blended result removes the drift to within 1° |
| C9 | Piecewise mode across a segment break | Uses the last calibration before each frame |
| C10 | Reminder interval is a setting | Changing it changes when the spoken reminder fires; T20's drift-check poses are logged as `drift_check` events, not as calibrations |

### V: Voice (design §7)

| ID | Test | Pass |
|---|---|---|
| V1 | **Script lint:** `voice_prompts.json` | Every calibration step and every 🔴 / redo alert has a phrase; ≤ 12 words; no banned words ("N-pose", "T-pose", "chunk", "sample") |
| V2 | Order and timing (fake clock + voice recorder) | Exact phrase sequence C1-C11 for a clean run; hold starts after "now" *finishes* |
| V3 | Every prompt logged | `prompt` events with start and finish time, matching the voice recorder |
| V4 | Priority | 🔴 interrupts calibration speech; 🟡 waits until it ends |
| V5 | Output fallback (fake audio route) | AirPods → Watch voice → phone speaker; `voice_unavailable` logged when none |
| V6 | Repeat button | Replays the last prompt; logged |
| V7 | Speech while recording AirPods motion, with the audio-level sensor on | Audio session uses the **built-in microphone**, `.allowBluetoothA2DP`, never `.allowBluetooth` (AirPods stay out of call mode); no change in AirPods sample rate or gaps (simulated route only here; confirm on device, T19) |
| V8 | Audibility check at Go/No-Go | No tap in 10 s → "can't hear" path |
| V9 | Listen-through | Generate an audio file of the whole script with the real synthesizer on the Mac; a team member listens for clarity and pacing |

### A: Watchdog and alerts (design §8)

Each row of the design's scenario tables becomes a scripted fault on a replayed recording:

| ID | Fault injected | Pass |
|---|---|---|
| A1 | AirPods stop sending for 1 s / disconnect event | 🔴 "The AirPods disconnected" within 3 s; on reconnect, recalibration prompt |
| A2 | AirPods route switched away | 🔴 within 3 s |
| A3 | Watch link silent 3 s (data still written locally) | 🟡 "preview paused" only; no 🔴 |
| A4 | Rate drops to 70 % for 40 s | 🟡 then 🔴 at 30 s; cause shown (thermal / low power) |
| A5 | Low Power Mode on before Start / mid-session | Start blocked / 🔴 spoken |
| A6 | Thermal state serious | 🟡 spoken; preview plots paused |
| A7 | Frozen sensor (values constant 5 s while another device moves) | Restart attempted; 🔴 if it stays frozen |
| A8 | Phone "dropped" (free fall, impact, flat and still 5 s) | 🔴; **no false alarm** during the jumping jacks of the reference recording |
| A9 | Battery 20 % / 10 % | 🟡 / 🔴 at the right levels |
| A10 | Debounce and escalation | < 2 s problems never alert; at most 1 alert per problem per minute; 🟡 > 30 s becomes 🔴 |
| A11 | Trial check | A trial with a 5 s AirPods gap → 🔁 "Redo trial N" with the reason |
| A12 | Court-exit check | Missing 60 Hz Watch chunks → "Redo" list; all present → "Safe to leave" |
| A13 | Court-exit check with high-rate chunks still on the Watch | "Safe to leave" if the Watch journal shows every high-rate chunk closed and checksummed; not safe if one is still open |

### P: Phone preview (design §6)

| ID | Test | Pass |
|---|---|---|
| P1 | Review screen reads **only closed chunks on disk** | Data in memory but not on disk never appears |
| P2 | Downsampling to ≤ 500 points | Peaks preserved (max/min per bucket); plot matches the full-rate curve |
| P3 | Load time for one chunk | < 50 ms on the Mac (budget for device) |
| P4 | Gaps and calibration marks on the timeline | Positions match the journal |
| P5 | Snapshot tests of each screen | Images unchanged unless intended |

### I: Mac ingest and pipeline (design §10; Python, `pytest`)

| ID | Test | Pass |
|---|---|---|
| I1 | Flip 1 byte in a chunk (as T8) | Ingest FAILs that chunk by name |
| I2 | Missing chunk / extra chunk / renamed chunk | Reported; never silently merged |
| I3 | Segments after a crash | Merged in order, keyed by (segment, index) |
| I4 | Clock fit with injected offset 2.5 s and drift 50 ppm | Recovered within 1 ms and 1 ppm |
| I5 | **Backward compatibility:** merged `stream.jsonl` | Loads in `motion_io.py`; E01-E03 on a replayed reference session reproduce today's results exactly |
| I6 | Today's 35 recordings | All still load; E03 runs on each without errors |
| I7 | `ingest_report.json` | PASS/FAIL agrees with S4 contract fixtures |
| I8 | High-rate data: (a) chunks still on the Watch, (b) all arrived | (a) `watch_hf: PENDING`, not FAIL, and the session can't be marked verified; (b) binary loader reads every chunk, indices continuous, PASS |

### X: Extra sensors (design §9)

New packet types; today's 14-value motion samples are unchanged.

| ID | Test | Pass |
|---|---|---|
| X1 | Barometer packets (synthetic `CMAltimeter`, ~1 Hz) | Pressure + relative altitude logged with sensor timestamps; gaps counted like motion |
| X2 | Magnetometer field + accuracy | Logged per device; low accuracy feeds the "compass disturbed" check (design §8) |
| X3 | Audio level and onset times | Only level and onset times stored, **no raw audio** in any file; input route is the built-in microphone |
| X4 | Packet compatibility | Recordings with X1-X3 packets (and optional UWB distance) still load in `motion_io.py` and pass I5-I6; missing optional UWB is not an error |

### E: End-to-end in the simulators (L4)

Simulators have **no motion sensors and no AirPods**, so they run on replayed motion.
**Workout mirroring is not supported in simulators** (Apple DTS, see [`device-research.md`](device-research.md)): E1-E2 run with mirroring off, and mirroring is checked on devices only.
The Watch app's high-rate stream (`CMBatchedSensorManager`) also needs real hardware; simulators use the synthetic generator.

| ID | Test | Pass |
|---|---|---|
| E1 | Paired iPhone + Watch simulators: Setup → Go/No-Go → Start → Calibrate → 3 trials → Stop | UI tests (XCUITest) complete; spoken phrases logged in order |
| E2 | Kill the phone app mid-session, relaunch, Resume | Session recovered (J4) through the real UI |
| E3 | Watch → phone chunk transfer over real WatchConnectivity in the simulator | All chunks arrive. **If file transfer isn't supported in the simulator, cover W1-W6 with the fake link only and mark W for device testing.** |
| E4 | HealthKit workout start/end on the Watch simulator | W7 behaviour through the real UI (verify the simulator supports workout sessions) |
| E5 | Review screen with a 10-min replayed session | P1-P4 through the real UI |

### L: Endurance (L5)

| ID | Test | Pass |
|---|---|---|
| L1 | 60-min and 120-min sessions with the fake clock | Chunk count = minutes; memory flat; no open-file leak; journal size as expected |
| L2 | 60-min replay in the simulators (real time on a spare machine, or 10× speed) | No crash; CPU and memory flat in Instruments |
| L3 | 120 random faults over a 60-min session (all A-faults, random times) | Every fault logged with its cause; zero samples lost on disk except those the fault itself prevented |

## 3. Exit criteria before any device test

- L1-L6 all green on two consecutive runs.
- Core package line coverage ≥ 85 %; recorder, journal and recovery ≥ 95 %.
- J3 (1,000 random crashes) and L3 (fault storm): **zero silent data loss.**
- V1 lint clean, and V9 listen-through signed off by both team members.
- S4 / I7 contract fixtures: Swift and Python agree on every fixture.

## 4. Device tests (L7)

Run only after L1-L6 pass, on the current build (free Apple ID builds expire after 7 days).
**Launch from the Home screen with Xcode detached** for anything involving the background.
When: **0b** = early device check, **9** = stage 9 device round, **F** = after the first field session.

| ID | Do this | Pass | When |
|---|---|---|---|
| T1 | Force-quit the phone app at 5 min, relaunch, Resume | 1 segment break; data intact; Watch complete | 9 |
| T2 | Walk 3 min away from the phone wearing the Watch | Watch data complete; preview gap logged | 9 |
| T3 | Take the AirPods out for 30 s | Gap bracketed by disconnect / connect events | 9 |
| T4 | Hard power-off of the phone mid-session | ≤ 1 s lost; open chunk recovered | 9 |
| T5 | Phone locked in pocket mode, 20 min | No gap | 9 |
| T6 | Phone locked in a pocket with the chosen keep-alive (design §5), 20 min, plus speech every 30 s and the Watch high-rate stream | Phone and AirPods ≥ 95 % while locked; AirPods rate unchanged around speech; Watch ≈ 800 + 200 samples/s; battery % noted | **0b**, again in 9 |
| T7 | Full 60 min tennis rehearsal | Ingest PASS; phone and Watch > 99 %, AirPods > 95 %; battery, heat and accelerometer saturation noted | 9 |
| T8 | Flip 1 byte in a copied chunk | Ingest FAILs that chunk | 9 |
| T9 | After T1 and T3, open the review screen | Gaps shown with their causes | 9 |
| T10 | Calibrate while swaying | "Calibration didn't work: you moved" | 9 |
| T11 | Stand still, calibrate twice 10 min apart | Drift on the phone matches the Mac report | 9 |
| T12 | Low Power Mode on before Start, then mid-session | Start blocked; mid-session 🔴, rate drop logged | 9 |
| T13 | Press the Watch crown to end the workout | Watch app relaunched, workout restarted, gap logged | 9 |
| T14 | Switch the AirPods to a Mac mid-session | 🔴 within 3 s | 9 |
| T15 | Drop the phone on grass while moving the Watch | 🔴 "phone fell out"; no false alarm during jumps | 9 |
| T16 | Fill the phone's disk to < 500 MB free | Go/No-Go blocks; mid-session 🔴, no silent loss | 9 |
| T17 | Run a trial with the AirPods out for 5 s | Trial check says Redo with the reason | 9 |
| T18 | Full spoken calibration on a court with wind and play nearby | Every phrase understood first time; audibility check passes | 9 |
| T19 | Speak through the AirPods for 5 min with the audio-level sensor on | AirPods stay out of call mode; motion rate and gaps unchanged | 9 (first look in 0b via T6) |
| T21 | Transfer the high-rate chunks after a 60 min session, devices side by side | All arrive, SHA verified; time taken recorded | 9 |
| T20 | **How long calibration holds:** calibrate once, play, and every 5 min stand in the calibration pose for 5 s without recalibrating; 2 days | Interval = time until any device exceeds 10°, rounded down to whole minutes; becomes the reminder default (10 min until then) | F |
