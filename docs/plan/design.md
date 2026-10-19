# Field recording design

**Goal:** record iPhone + Apple Watch + AirPods for about 1 hour on a tennis court, with no Mac and
no Wi-Fi, and never lose more than a few seconds of data.

**Status:** design; not implemented. Build order: [`dev-plan.md`](dev-plan.md). Tests:
[`test-plan.md`](test-plan.md). Decisions and their dates: [`decisions.md`](decisions.md).

## 1. Overview

```
 ┌──────────── ON THE COURT ────────────┐        ┌──────────── LATER, AT THE MAC ────────────┐
 │  Watch ──▶ Watch disk (chunks)       │        │                                           │
 │              │ 60 Hz: as each closes │  USB / │  ingest_field.py                          │
 │              ▼ high-rate: after      │ AirDrop│   ✓ checksums   ✓ gaps + causes           │
 │  iPhone ─▶ phone disk (chunks) ──────┼────────┼─▶ ✓ clock fit   ✓ PASS / FAIL / PENDING   │
 │  AirPods ─▶ (via iPhone)             │        │        │                                  │
 │                                      │        │        ▼                                  │
 │  live view (optional, may drop):     │        │  stream.jsonl ─▶ motion_io.py ─▶ analysis │
 │  Watch ┄┄▶ iPhone ┄┄▶ Mac (UDP)      │        │                                           │
 └──────────────────────────────────────┘        └───────────────────────────────────────────┘
        ━━ durable path      ┄┄ live preview only
```

| # | Rule | Why |
|---|---|---|
| 1 | **Each device saves to its own disk** | Radio links drop; disks don't |
| 2 | **60 s chunk files, never edited after closing** | A crash damages at most one chunk |
| 3 | **Write every packet; `fsync` every 1 s** | App crash: lose 0 s. Power-off: lose ≤ 1 s |
| 4 | **Number every sample** (`first_index`) | Every gap is visible and measurable |
| 5 | **Log every disruption as an event** | Every gap has a recorded cause |
| 6 | **Delete only after the Mac verifies** | No single point of loss |

The packet format (`Shared/MotionFormat.swift`, described in
[`apps/MotionStreamer/README.md`](../../apps/MotionStreamer/README.md#data)) and the Mac loader
(`pipeline/preprocessing/motion_io.py`) stay unchanged: each chunk line is one of today's packets.

**Setting:** solo recording, everything controlled from the Watch with spoken guidance. Watch on
the racket arm, iPhone in the front trouser pocket on the same side (or a fitted armband), AirPods
in. See [`decisions.md`](decisions.md).

## 2. Storage on each device

```
Documents/sessions/20261020-143000-P01/
├── journal.jsonl          source of truth: one line per state change
├── manifest.json          readable summary, rebuilt from the journal
├── phone/                 phone + AirPods + events + sync + extra sensors
│   ├── 000000.jsonl          closed (read-only)
│   └── 000001.jsonl.open     being written
├── watch/                 60 Hz Watch chunks, each sent as soon as it closes (§3)
└── watch_hf/              high-rate Watch chunks (binary), sent after the session
```

**Chunk lifecycle:** open → write each packet → `fsync` every 1 s → at 60 s: `fsync`, close,
SHA-256, rename `.open` → `.jsonl`, journal `chunk_closed`.

- File protection **`.completeUntilFirstUserAuthentication`**, so writes continue while the phone
  is locked. Never `.complete`: it blocks writes when locked.

**Journal lines**

| `j` | When | Key fields |
|---|---|---|
| `session_open` | Start | participant, activity, devices, settings, battery, free disk, `boot_to_unix`, `app_version`, `build_date`, `signing_expires` |
| `chunk_closed` | Each rotation | file, lines, bytes, `sha256`, index range per device |
| `chunk_received` | Watch chunk arrives on the phone | file, `sha256`, verified |
| `health` | Every 60 s | battery (phone, Watch), thermal state, Low Power, AirPods, Watch reachable |
| `segment_open` | Resume after a crash | segment number, reason |
| `correction` | Metadata edited later | field, old, new (never an overwrite) |
| `session_close` | Stop or recovery | `clean: true/false` |

**High-rate Watch stream** (`CMBatchedSensorManager`, always on): 800 Hz acceleration + 200 Hz
device motion, available on our Series 8 during a workout ([`device-research.md`](../research/device-research.md) §3).
Stored as binary because JSON would be ~250 MB/h:

```
watch_hf/NNNNNN.bin
┌──────────────────────────────┬──────────────────────────────────────────────┐
│ header: 1 JSON line + "\n"   │ fixed-size little-endian records             │
│ format, version, session,    │ 1-byte type tag, then                        │
│ segment, first_index per     │ accel  (800 Hz): t f64 · ax ay az f32 = 20 B │
│ stream, boot_to_unix, fields │ motion (200 Hz): t f64 · 13 × f32     = 60 B │
└──────────────────────────────┴──────────────────────────────────────────────┘
```

A torn chunk is trimmed to its last whole record; SHA-256 and journal rules are the same as JSON
chunks. The Mac reads it with a `numpy` loader.

**Size per hour:** phone ~115 MB (phone + AirPods + Watch 60 Hz copy) · Watch ~40 MB (60 Hz) +
~100 MB (high-rate) · phone ~100 MB more once the high-rate copy arrives. **Start requires 2 GB
free on the phone and 2 GB on the Watch.**

## 3. Watch → phone transfer

```
 Watch: CMMotionManager ──▶ chunk writer ──▶ watch/NNNNNN.jsonl ━━ transferFile ━━▶ iPhone: verify SHA-256
                                 ┊                                (queued, retried)      └▶ save, ack (file, sha)
                                 ┊┄┄ sendMessageData: live preview only, may drop
```

- The Watch writes locally whether or not the phone is reachable; today's 10 s buffer becomes
  preview only.
- **60 Hz chunks are sent as each closes**, so the phone's copy is at most ~1-2 min old.
- **High-rate chunks are sent after the session**, not during play (radio time and battery).
  Keep the Watch near the phone with the app open, ideally charging; the phone shows
  "High-rate: N / M sent". Expect several minutes per hour of data.
- At Stop the Watch also sends a snapshot of its journal (`watch_journal.jsonl`) and a summary
  message with its chunk counts, so the phone can show "N / M" and the Mac sees the Watch's side.
- The Watch keeps every chunk until the **Mac has verified** the session. A "Resend session"
  button sends everything again; duplicates are harmless.
- Move each received file out of the WatchConnectivity inbox before the delegate returns (the
  system deletes it afterwards).

## 4. Crash recovery

```
 App launches ─▶ session without session_close? ── no ──▶ normal start
                      │ yes
                      ▼
          trim the .open chunk to its last whole line / record, close it (recovered: true)
                      ▼
          "Recording was interrupted at 14:32:10. Resume?"
             Resume: same session, segment + 1, chunk numbers continue, sample index restarts at 0
             Close:  session_close (clean: false)
```

- The Mac keys samples by (segment, index).
- App inactive / background / terminate, memory warnings and Watch workout end are logged and
  followed by an `fsync`.
- The Watch recovers its workout with `handleActiveWorkoutRecovery()` +
  `recoverActiveWorkoutSession` and then runs the same chunk recovery.

## 5. Keeping all three recording in a pocket

Core Motion doesn't keep an app awake; the app must stay awake through a background mode
([`device-research.md`](../research/device-research.md) §1).

| Device | How | Status |
|---|---|---|
| Watch | `HKWorkoutSession` (+ `audio` background mode for speech and haptics); workout recovered after a crash | ✅ |
| iPhone | Background location at 3 km accuracy (Apple-confirmed to keep motion flowing); the default setting until the stage 0b check decides | ✅ built; 🧪 T6 |
| iPhone, optional | Workout mirroring, started after the Watch session is prepared (works around an iOS 26 bug) | ✅ built (setting); not relied on |
| iPhone, fallback | Pocket mode: app in the foreground, screen off by the proximity sensor | ✅ exists |
| AirPods | Head motion through the phone app; the Watch can't read it | ❓ background behaviour checked in stage 0b |

- If the app goes to the background with no keep-alive running, or AirPods motion stops there for
  3 s, the phone says "Heads up: keep the app open in your pocket." and logs `pocket_mode_needed`.
- **Background tests must run with Xcode detached** (launched from the Home screen): with the
  debugger attached, iOS never suspends the app.

## 6. Previewing data on the phone

| Level | When | Shows | Source |
|---|---|---|---|
| ① Live strip | While recording | Hz, last-sample age, 🟢🟡🔴 per stream | Memory |
| ② Review screen | Any time | Whole-session timeline (gaps, calibrations) + last 60 s plots per device | **Closed chunks on disk** |
| ③ Session check | After Stop | PASS / WARN / FAIL card | Journal + chunks |

```
 ┌──────────────────────────────────────┐
 │ 20261020-143000-P01      ● REC 23:41 │
 │ Phone   ███████████████████▌████████ │   gap = missing data
 │ Watch   ██████████████████████████░░ │   ░ not on the phone yet
 │ AirPods ██████▌▌██████ █████████████ │
 │          ▲cal     ▲cal      ▲cal     │
 │ Last 60 s   [Phone|Watch|AirPods]    │
 │  rotation ∿∿∿╱╲∿∿∿  accel ──╱╲──     │
 │  angle since calibration ──╱‾‾╲──   │
 │ Phone 33 Hz · 99.4 % · 2 gaps        │
 │ Watch 60 Hz · 99.8 % · 0 gaps        │
 │ AirPods 50 Hz · 96.1 % · 9 gaps      │
 └──────────────────────────────────────┘
```

- ② reads only saved files: if it appears there, it is on disk.
- Plots: one chunk loaded at a time off the main thread, ≤ 500 points per plot (Swift Charts),
  peaks preserved.
- Quick sanity test: 3 knee raises → 3 peaks in thigh angle; look left and right → head angle swings.

**Status dots** (live strip and Watch)

| Check | 🟢 | 🟡 | 🔴 |
|---|---|---|---|
| Age of last sample | < 0.5 s | 0.5-2 s | > 2 s |
| Rate vs that device's first minute | > 90 % | 70-90 % | < 70 % |
| Coverage, last 60 s | > 99 % | 95-99 % | < 95 % |
| Watch 60 Hz chunks not yet on the phone | ≤ 2 | 3-5 | > 5 |

All thresholds live in one file, `Shared/quality_thresholds.json`, read by the app and by
`ingest_field.py`, so the phone and the Mac never disagree.

## 7. Calibration

**Calibration never changes raw data.** Each calibration is a marked, checked window in the
recording; the Mac computes the rotations afterwards. Recalibrating adds windows; a bad one can be
skipped later.

**Why it drifts:** the phone's heading uses magnetic north (court fences and posts disturb it;
the phone shifts in the pocket); the Watch strap slides; the AirPods' heading is arbitrary and
resets on reconnect. E02 measured ~5-10°/min of model orientation drift for head and thigh.

**The routine** (~17 s, started from the Watch, every step spoken; prompts kept short so a returning player hears only the cue):

```
 Tap Calibrate on the Watch (or accept a reminder)
   ▼ "Calibrating. Face {landmark}."  "Three, two, one."
 ① Standing pose, arms down, facing the landmark ── hold 3 s ──▶ phone + AirPods
   ▼ "Good."
 ② Arms-out pose, arms straight out to the sides, palms down ── hold 3 s ──▶ Watch
   ▼ "Arms down."
 "Calibration done."  or  "Calibration didn't work: {reason}. Let's try again."
```

**Script** (`MotionStreamerCore/Resources/voice_prompts.json`, with every alert phrase; generate a listening copy with `tools/make_voice_sample.py`; `{landmark}` is set in Setup, e.g. "the net"):

| # | Spoken (exactly) | Data |
|---|---|---|
| C1 | "Calibrating. Face {landmark}." | `prompt` events with start/finish time (all prompts) |
| C2 | "Three, two, one." (one number per second) | |
| C3 | "Stand tall, arms down." | |
| C4 | "Hold still… now." | hold window starts 0.3 s after "now" finishes; `calibrate` event (`t_phone` + 0.3 = window start, `hold_s` 3.3) |
| C5 | "You moved. Hold still." (once; the hold restarts) | |
| C6 | "Good." | `cal_hold_end` |
| C7 | "Arms out, shoulder height." | |
| C8 | "Arms a bit higher." (if not level after 6 s) | |
| C9 | "Hold still… now." | as C4; `calibrate_arms` event |
| C10 | "Arms down." | `cal_hold_end` |
| C11 | "Calibration done." | `calibrate_result: pass` |
| C12 | "Calibration didn't work: {reason}." then "Let's try again." (at most 2 retries, then "Please check the devices, then tap Calibrate.") | `calibrate_result: fail` |

Reasons: "you moved" · "the phone isn't upright in your pocket" · "your arms weren't level" ·
"the AirPods aren't connected" · "the watch isn't sending data".

**Check on the phone right after the holds**

| Check | Pass |
|---|---|
| Still | Rotation RMS < 0.15 rad/s on every device (as `pipeline/preprocessing/calibration.py`) |
| Phone upright | Gravity along the phone's long axis > 0.85 |
| Arms level | Watch forearm axis within ~20° of horizontal |
| All devices present | Samples from each in the window |
| Drift since last calibration | Angle per device, logged and shown ("drift: 6°") |

**When:** start of session · before each trial · after an AirPods reconnect, strap adjustment,
re-pocketing or crash resume · at the reminder interval (a setting, default 10 min until test T20
measures it). Reminder: "Time to recalibrate." then "When you're ready, face {landmark} and tap the
watch." (repeats every 2 min until done or dismissed). The app also logs `still_upright` whenever
the user stands still and upright for 2 s; these correct tilt, not heading.

**On the Mac:** blend between neighbouring calibrations (slerp) to remove steady drift; use the
last calibration before each frame across segment breaks or next to a failed one.
`ingest_report.json` lists drift per interval; above ~10° between calibrations means calibrate
more often. `pipeline/preprocessing/calibration.py` must handle many calibrations and the arms-out pose.

### Voice rules (calibration and alerts)

- **Output:** iPhone `AVSpeechSynthesizer` through the AirPods; if the AirPods are out, the Watch
  speaks; the phone speaker is the last resort; `voice_unavailable` logged if none works.
- **Timing comes from speech:** holds start when "now" finishes speaking (`didFinish`).
- **Wording:** ≤ 12 words per prompt, the same every time, no jargon ("N-pose", "T-pose", "chunk",
  "sample" are banned), speech slightly slower than default.
- **Priority:** 🔴 interrupts anything; 🟡 waits until calibration ends. "Repeat" on the Watch
  replays the last prompt.
- **Audio session:** `.playAndRecord`, `.spokenAudio`, `.duckOthers`, `.allowBluetoothA2DP`, never
  `.allowBluetooth`; preferred input = the phone's built-in microphone. This keeps the AirPods out
  of call mode. The iPhone app needs the `audio` background mode.
- **Audibility check at Go/No-Go:** "Can you hear me? Tap the watch if you can." No tap in 10 s →
  raise the volume or switch output.
- **One control system:** the iPhone owns the session. Start, Stop, Calibrate, Trial, Repeat and OK
  are commands to the iPhone from either device (Start from the Watch runs the same Go/No-Go with the
  last plan). The iPhone sends its state to the Watch on every change and every 3 s; both screens
  draw their buttons from it (`ControlState.buttons`), one large button each. With no state for
  10 s the Watch shows "iPhone not reachable" and offers **Record on Watch only**; a later iPhone
  Start makes the Watch join that session.

## 8. Problems in the field: detect, fix, alert

Find a problem within seconds, fix it automatically if possible, otherwise tell the person on the
court, and **never leave the court with an incomplete trial.**

| Checkpoint | When | Checks | Outcome |
|---|---|---|---|
| ① Go / No-Go | Before Start | All required devices live, rates, battery for the planned minutes, disk, Low Power off, signing days left, settings (wrist, pocket, landmark), audibility | Start allowed or blocked with the reason |
| ② Watchdog | Every 1 s | Scenario tables below | Auto-fix, then alert |
| ③ Trial check | After each trial | Required streams complete in `[start − 2 s, end + 2 s]` | ✅ Keep or 🔁 Redo |
| ④ Court-exit check | Before Stop | Every trial ✅; 60 Hz Watch chunks on the phone; high-rate chunks closed on the Watch | "Safe to leave" or "Redo trials 3, 5" |

- **Required streams** default to phone + Watch (60 Hz and high-rate) + AirPods. Recording
  without one needs an explicit override, which is logged.
- The court-exit check doesn't wait for the high-rate transfer: the Watch journal showing every
  high-rate chunk closed is enough (rule 1).

**Watchdog loop:** measure → compare with thresholds → log the event (always) → try an auto-fix →
if not fixed, alert → escalate 🟡 to 🔴 after 30 s. Alerts need the problem to last ≥ 2 s and fire
at most once per problem per minute; one Watch tap acknowledges (logged).

**Connection and device**

| Scenario | Detect | Auto-fix | Alert |
|---|---|---|---|
| AirPods disconnect (out of ear, Bluetooth, battery) | Disconnect event or no sample > 1 s | Restart head motion on reconnect | 🔴 "Stop. The AirPods disconnected." Recalibrate after reconnect |
| AirPods taken by another device | Connected but no samples; audio route change | — | 🔴 within 3 s. Pre-flight: automatic switching off |
| Watch out of range | No live batches > 3 s | None needed (Watch writes locally) | 🟡 "Watch preview paused" |
| Watch workout ended (crown, swipe, watchOS) | Workout state change, no heartbeat | Phone relaunches the Watch app (`startWatchApp`) | 🔴 "Stop. The watch stopped recording." |
| App crashed or killed | Unclosed session at launch | Recovery + Resume (§4) | 🔴 "Resume recording?" |
| Phone rebooted / clock jump | `boot_to_unix` changes | New segment | Logged; recalibrate |

**Sampling quality**

| Scenario | Detect | Auto-fix | Alert |
|---|---|---|---|
| Low sample rate | 5 s rate < 80 % of the Go/No-Go rate | Shed load: stop UDP, pause plots | 🟡, 🔴 after 30 s, with the cause (heat / Low Power / CPU) |
| Low Power Mode | `isLowPowerModeEnabled` | — | Blocks Start; 🔴 mid-session |
| Overheating | `thermalState` ≥ `.serious` | Shed load | 🟡 "Heads up: the phone is getting hot." |
| Late or bursty delivery | Arrival gaps, sensor timestamps continuous | None needed | Logged |
| Duplicate or backwards timestamps | Index / timestamp check | Mac drops duplicates, raw kept | Logged |
| Frozen sensor | Variance ≈ 0 for 5 s while another device moves | Restart that device's updates | 🔴 if still frozen |
| Saturated accelerometer | Samples near the sensor maximum | — | Counted in the session check |
| Magnetic disturbance | Heading jumps at low rotation; low magnetometer accuracy | — | 🟡 "Compass disturbed. Recalibrate away from the fence." |
| Wrong reference frame | `ref_frame` ≠ expected | — | Shown at Go/No-Go |

**Body and placement**

| Scenario | Detect | Alert |
|---|---|---|
| Phone rotated or slipped | In a still-upright window, gravity > 15° from the last calibration | 🟡 "Phone moved: re-seat and recalibrate" |
| Watch slid on the wrist | Same test during the arms-out pose or arm hanging | 🟡 "Tighten the strap, recalibrate" |
| Phone fell out | Free fall + impact, then flat and still > 5 s while the Watch moves | 🔴 "Stop. The phone fell out of your pocket." |
| Watch on the wrong wrist | Go/No-Go "raise your watch arm" test | Fix the setting before Start |

**Power and storage**

| Scenario | Detect | Alert |
|---|---|---|
| Battery won't last the plan | Drain rate × planned minutes vs charge | Blocks Start; shows minutes per device |
| Battery low | < 20 % / < 10 % on any device | 🟡 / 🔴 "Finish this trial and stop" |
| AirPods battery | Not readable by apps; estimated from time connected | 🟡 after 3.5 h; charge at changeovers |
| Disk full / write error | Write or `fsync` fails; < 500 MB free | Chunk closed, new chunk tried; 🔴 immediately, never silent |

**People and process**

| Scenario | Detect | Response |
|---|---|---|
| Forgot to calibrate | Reminder interval passed | Spoken reminder (§7) |
| Trial incomplete | Trial check ③ | 🔁 "Redo trial four. The AirPods were missing for twelve seconds." |
| Forgot the Trial button | Sync gesture with no trial marker nearby | `possible_trial`; asked at the court-exit check |
| Forgot to Stop | Still, no activity > 10 min | Ask; auto-stop after 20 min, closed cleanly |
| Call / Siri / notification | Audio interruption and route-change events | Logged; Do Not Disturb pre-flight |
| Wrong participant or activity | — | Corrected later as a `correction` journal line |

**Alert levels** (spoken first; haptics and phone banner are backups)

| Level | Repeat | Backup |
|---|---|---|
| 🟡 Warn | Once | 1 long tap, banner |
| 🔴 Stop and fix | Every 30 s until fixed or acknowledged | 3 strong taps, banner + sound |
| 🔁 Redo trial | Once | 2 taps, trial card turns red |
| ✅ Recovered ("The watch is recording again.", "The AirPods are back.") | Once | — |

**Trial check ③**

| Check | Pass |
|---|---|
| Coverage of each required stream | ≥ 98 % |
| Longest gap | ≤ 0.3 s |
| Rate | ≥ 80 % of baseline |
| Last good calibration | Within the reminder interval, nothing that resets it since |
| Sync gesture | Detected at the start |

Watch data is checked from the live preview first, then again once its chunk arrives.

## 9. Trials and extra sensors

- **Trial button** (Watch, one large tap; also on the phone): the first tap starts trial N and logs
  a `marker` (`edge: start`), the next tap ends it, logs `marker` (`edge: end`) and runs the trial
  check (§8 ③) at once: ✅ keep, or 🔁 "Redo trial N. {reason}." spoken. Each trial starts with the
  **sync gesture**: 2 s still · 3 hops · 3 head nods · 2 s still (the hops are detected from the
  phone: three acceleration peaks above 1 g, 0.25-1.5 s apart). It gives a shared time reference
  across devices (and for OpenCap later: [`opencap.md`](../deferred/opencap.md)).
- **Extra sensors** as new packet types (motion packets unchanged; `motion_io.py` ignores them,
  `ingest_field.py` counts them). Each has a running index `i`, so gaps count like motion:

| Packet `type` | Devices | Fields | Rate |
|---|---|---|---|
| `baro` | phone, Watch | `pressure_kpa`, `rel_alt_m` (`CMAltimeter`) | ~1 Hz |
| `mag` | phone, Watch | `field_ut` (calibrated, device frame), `accuracy` (−1…2); low accuracy → 🟡 compass disturbed | 1 Hz |
| `audio_level` | phone | `rms_db`, `peak_db`, `onset`; built-in microphone only, **no audio stored** | 20 Hz |
| `uwb` | phone | `distance_m` (Nearby Interaction, optional; not built yet) | — |
| Light | — | not available to apps; dropped | — |

## 10. After the session

```
 ① Copy (Finder / AirDrop) ─▶ ② ingest_field.py ─▶ ③ Back up (2nd drive) ─▶ ④ Clear devices
    → data/recordings/field/      SHA-256 per chunk       only after PASS           only sessions listed
                                  all chunks present                                in verified.json
                                  gaps + causes, clock fit, drift
                                  ingest_report.json: PASS / FAIL / PENDING
                                  merged stream.jsonl → motion_io.py
```

- `--phone-only` marks a session recorded without a Watch, so the missing Watch isn't a failure.
- `watch_hf: PENDING` (not FAIL) while high-rate chunks are still on the Watch; the session can't
  be verified or cleared until they arrive.
- **Never delete before ② says PASS and ③ is done.**

## 11. Field protocol

**Before**
- [ ] Every device above 80 %; Low Power Mode off on phone and Watch; app signed for the session
- [ ] AirPods: automatic switching off, connected to this iPhone only
- [ ] Do Not Disturb on; automatic date and time on
- [ ] Watch strap tight; phone in a fitted pocket or armband
- [ ] 30 s dry run (records, runs the session check, discards)
- [ ] Go / No-Go all ✅ → Start
- [ ] Spoken calibration → sync gesture
- [ ] Review screen: knee raises and head turns look right

**During**
- [ ] Trial button + sync gesture at every trial; Keep or Redo right away
- [ ] Any 🔴: stop, fix, recalibrate if asked
- [ ] Recalibrate when reminded (ideally at changeovers)

**After**
- [ ] Closing calibration + sync gesture (measures drift over the whole session)
- [ ] Court-exit check "Safe to leave" → Stop → session check PASS (note any WARN)
- [ ] Watch near the phone until "High-rate: all sent"
- [ ] Same day: copy → ingest PASS → back up → clear

**Data handling:** participant codes (`P01`) everywhere, names only on a separate sheet. Session
metadata (device models and OS, app version, settings, landmark, court, weather) is saved in
`session_open`; placement photos go in the session folder.
