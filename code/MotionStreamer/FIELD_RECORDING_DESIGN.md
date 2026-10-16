# Field recording design

> **Goal:** record iPhone + Watch + AirPods for about 1 h on a tennis court, with no Mac and no
> Wi-Fi, and never lose more than a few seconds of data.
> **Status:** design only, not implemented yet.

---

## 1. The idea in one picture

```
 ┌──────────── ON THE COURT ────────────┐        ┌────────────── LATER, AT THE MAC ──────────────┐
 │                                      │        │                                                │
 │  Watch ──▶ watch disk (chunks)       │        │                                                │
 │               │  60 Hz: as each closes│        │                                                │
 │               ▼  high-rate: later    │  USB / │   ingest_field.py                              │
 │  iPhone ─▶ phone disk (chunks) ──────┼────────┼─▶  ✓ checksums    ✓ gaps + causes              │
 │  AirPods ─▶  (via iPhone)            │ AirDrop│    ✓ clock fit    ✓ PASS / FAIL                │
 │                                      │        │        │                                       │
 │  live view (optional, may drop)      │        │        ▼                                       │
 │  Watch ┄┄▶ iPhone ┄┄▶ Mac (UDP)      │        │   stream.jsonl ─▶ motion_io.py ─▶ OpenCap sync │
 └──────────────────────────────────────┘        └────────────────────────────────────────────────┘
        ━━ durable path      ┄┄ live preview only
```

## 2. Rules

| # | Rule | Why |
|---|---|---|
| 1 | **Each device saves to its own disk** | Radio links drop; disks don't |
| 2 | **60 s chunk files, never edited after closing** | A crash damages at most 1 chunk |
| 3 | **Write every packet; `fsync` every 1 s** | App crash: lose 0 s. Power-off: lose ≤1 s |
| 4 | **Number every sample** (`first_index`) | Every gap is visible and measurable |
| 5 | **Log every disruption as an event** | Every gap has a recorded cause |
| 6 | **Delete only after the Mac verifies** | No single point of loss |

## 3. Gaps in today's app

| Today | Risk on the court | Fix |
|---|---|---|
| Won't start without a Mac IP ([StreamController.swift:183](iOS/StreamController.swift:183)) | Can't record at all | **Record-only mode**: Mac IP optional |
| Watch holds 10 s in RAM, then drops ([WatchStreamer.swift:21](Watch/WatchStreamer.swift:21)) | Watch data lost if phone app suspends | **Watch writes its own chunks** (§5) |
| One file, flushed only at Stop ([SessionRecorder.swift:19](iOS/SessionRecorder.swift:19)) | Power-off loses buffered data | Chunks + `fsync` + journal (§4) |
| Summary + events saved only at Stop | Crash = no summary | Append-only journal |
| No crash detection | Interrupted session never closed | Recovery on launch (§6) |
| Runs only in the foreground | iOS suspends app → all streams stop | Workout mirroring (§7) |
| No voice; calibration uses screen + buzz | Can't follow it with the phone in a pocket | Spoken script (§9) |
| No tests, no fakes for sensors | Every change needs devices to check | Test harness (§16 ⓪, `TEST_PLAN.md`) |

✅ **Unchanged:** packet format (`MotionFormat.swift`) and Mac loader (`live/motion_io.py`).
Each chunk line is one of today's packets.

## 4. Storage on the device

```
Documents/sessions/20261020-143000-P01/
├── journal.jsonl          ← source of truth: one line per state change
├── manifest.json          ← readable summary, rebuilt from the journal
├── phone/                 ← phone + AirPods + events + sync
│   ├── 000000.jsonl          closed  (read-only)
│   ├── 000001.jsonl          closed
│   └── 000002.jsonl.open     writing now
├── watch/                 ← 60 Hz Watch chunks, each sent as soon as it closes (§5)
│   └── 000000.jsonl …
└── watch_hf/              ← high-rate Watch chunks (binary, §13), sent after the session
    └── 000000.bin …
```

**Chunk lifecycle**

```
  open ──▶ write each packet ──▶ fsync every 1 s ──▶ 60 s? ──▶ fsync + close
                                                              ──▶ SHA-256
                                                              ──▶ rename .open → .jsonl
                                                              ──▶ journal: chunk_closed
```

- File protection: **`.completeUntilFirstUserAuthentication`**, so writes keep working while the phone is locked.
- ⚠️ Never `.complete`: it blocks writes when the phone is locked.

**Journal lines**

| `j` | When | Key fields |
|---|---|---|
| `session_open` | Start | participant, activity, devices, battery, free disk, `boot_to_unix` |
| `chunk_closed` | Each rotation | file, lines, bytes, `sha256`, index range per device |
| `chunk_received` | Watch chunk arrives | file, `sha256`, verified |
| `health` | Every 60 s | battery (phone + Watch), thermal state, low power, AirPods, Watch reachable |
| `segment_open` | Resume after crash | segment #, reason |
| `session_close` | Stop or recovery | `clean: true/false` |

**Size per hour**

| Where | Streams | Size |
|---|---|---|
| Phone | phone + AirPods + 60 Hz Watch copy (JSON) | ~115 MB |
| Watch | 60 Hz stream (JSON) | ~40 MB |
| Watch | high-rate stream (binary, §13) | ~100 MB |
| Phone, after transfer | high-rate copy | ~100 MB |

Start requires **2 GB free** on the phone and **2 GB** on the Watch. That covers several sessions,
since the Watch keeps data until the Mac verifies it.

## 5. Watch: save locally first, send each chunk as it closes

```
 Watch                                           iPhone
 ─────                                           ──────
 CMMotionManager
     │
     ▼
 chunk writer ──▶ watch/NNNNNN.jsonl ━━ transferFile ━━▶ verify SHA-256
     │              (durable)            (watchOS queues    │
     │                                    and retries)      ▼
     │                                              save to sessions/<id>/watch/
     │                                                      │
     │                       ◀━━━━━━━━━ ack (file, sha) ━━━━┘
     ┊
     ┊┄┄ sendMessageData (live preview, may drop) ┄┄▶ live display
```

- Local writing **no longer depends on the phone** being reachable.
- The existing 10 s buffer becomes **preview only**.
- **Each chunk is sent as soon as it closes**, not only after Stop. The phone then holds a
  checked copy of the Watch data that is at most ~1–2 min old, which the phone preview (§8) reads.
- After an ack, the Watch keeps its copy. It deletes only when the **Mac has verified** the session.
- After Stop, the phone shows **"Watch: 58 / 60 chunks"** until every 60 Hz chunk arrives.
- **High-rate chunks (`watch_hf/`) are not sent during play.** They transfer after the session (§13);
  the phone shows them separately: **"High-rate: 12 / 60 sent"**.
- The Watch has a **"Resend session"** button.

## 6. Crash recovery

```
 App launches
     │
     ▼
 Any session without session_close? ── no ──▶ normal start
     │ yes
     ▼
 Trim the .open chunk to its last full line ──▶ close it (recovered: true)
     │
     ▼
 "Recording interrupted at 14:32:10. Resume?"
     │                              │
  Resume                          Close
     ▼                              ▼
 Same session ID              session_close
 segment += 1                 (clean: false)
 chunk numbers continue
 sample index restarts at 0  →  Mac keys samples by (segment, index)
```

- **Also logged + `fsync`:** app goes inactive/background/terminates, memory warning, Watch workout ends.
- Phone and Watch each run this on their own.

## 7. Keeping all three running in a pocket

| Device | How | Status |
|---|---|---|
| **Watch** | `HKWorkoutSession` | ✅ already in place |
| **iPhone (primary)** | **Workout mirroring** (iOS 17+): the Watch calls `startMirroringToCompanionDevice()`; iOS launches and keeps the phone app alive | 🧪 test T6 |
| **iPhone (fallback)** | Foreground pocket mode (proximity sensor, idle timer off) | ✅ already in place |
| **AirPods** | `CMHeadphoneMotionManager` on the phone | ❓ does it keep running in the background? (T6) |

- 📱 Wear the phone in an **armband or fitted pocket**: a loose pocket adds fake motion and can drop the phone.

## 8. Previewing data on the phone

Three levels, from "is it running?" to "is it right?":

```
 ① Live strip               ② Review screen               ③ Session check
    while recording            any time                      after Stop
 ─────────────────────      ─────────────────────────     ─────────────────────────
 Hz · last-sample age       timeline + last-60 s plots     one card: PASS/WARN/FAIL
 🟢 🟡 🔴 per stream          per device                     same rules as the Mac check
 source: memory             source: DISK (closed chunks)   source: journal + chunks
```

- **② reads the saved files, not memory.** If it shows up there, it is on disk.

**Review screen**

```
 ┌──────────────────────────────────────┐
 │ 20261020-143000-P01      ● REC 23:41 │
 │                                      │
 │ Whole session                        │
 │ Phone   ███████████████████▌████████ │
 │ Watch   ██████████████████████████░░ │   ░ not received yet
 │ AirPods ██████▌▌██████ █████████████ │   gap = missing data
 │          ▲cal     ▲cal      ▲cal     │   tap anywhere to jump
 │                                      │
 │ Last 60 s     [Phone|Watch|AirPods]  │
 │  rotation   ∿∿∿╱╲∿∿∿∿╱╲∿∿∿∿          │
 │  accel      ──╱╲───────╱╲──          │
 │  angle      ───────╱‾‾╲─────         │   from the last calibration
 │                                      │
 │ Phone   33 Hz · 99.4% · 2 gaps       │
 │ Watch   60 Hz · 99.8% · 0 gaps       │
 │ AirPods 25 Hz · 96.1% · 9 gaps       │
 │ 14:31 cal ✅ · 14:38 AirPods out 4 s │
 └──────────────────────────────────────┘
```

- **Plots:** rotation-rate size, acceleration size, and angle since the last calibration (thigh pitch, head turn, forearm tilt).
- **Fast:** load one chunk at a time off the main thread; draw ~500 points per plot (Swift Charts).
- **Quick sanity test:** 3 knee raises → thigh angle shows 3 peaks; look left/right → head angle swings.

**Status dots** (live strip and Watch face)

| Check | 🟢 | 🟡 | 🔴 |
|---|---|---|---|
| Age of last sample | < 0.5 s | 0.5–2 s | > 2 s |
| Rate vs that device's first minute | > 90% | 70–90% | < 70% |
| Coverage, last 60 s | > 99% | 95–99% | < 95% |
| Watch chunks not yet on phone | ≤ 2 | 3–5 | > 5 |

- 🔴 for more than 10 s → **spoken alert** (§10), with a Watch haptic as backup.
- **Session check (③):** duration, coverage, gaps > 0.5 s, calibrations passed, saturated samples, Watch chunks received.
- One rules file, `Shared/quality_thresholds.json`, used by **both** the app and `ingest_field.py`, so the phone and the Mac never disagree.

## 9. Calibration that stays calibrated

**Why it drifts**

| Device | Heading measured against | What shifts over time |
|---|---|---|
| Phone | magnetic north | metal court fences/posts bend the compass; phone shifts in the pocket |
| Watch | its reference frame | strap slides or rotates on the wrist |
| AirPods | **arbitrary**, wherever tracking started | heading drifts; resets after a reconnect |

- E02 measured **~5–10°/min** of model orientation drift for the head and thigh.

**Key idea: calibration never changes the raw data.**
- Each calibration is just a marked, checked window in the recording.
- Recalibrating = adding more windows. The Mac computes all the rotations afterwards.
- A bad calibration can be skipped later; nothing is overwritten.

**The calibration routine: spoken step by step** (~20 s, started from the **Watch**, since the phone is in a pocket)

Every instruction is **spoken in plain words**. Buzzes are hard to feel during play, so
haptics are only a backup that fires together with each spoken step.

```
 Tap "Calibrate" on the Watch (or accept a reminder)
   │
   ▼  🔊 intro + "three, two, one"
 ① Standing pose ─ stand straight, arms down, face the landmark ─ hold 3 s → phone + AirPods
   ▼  🔊 "Good."
 ② Arms-out pose ─ arms straight out to the sides, palms down ─── hold 3 s → Watch (fixes the E02 arm issue)
   ▼  🔊 "Arms down."
 🔊 result: "Calibration complete." or the reason it failed + "Let's try again."
```

**The script.** `{landmark}` is set in Setup (e.g. "the net", "the wall"); the default is "the same direction as last time".

| # | Phase | Spoken (exactly) | What the person does | Data |
|---|---|---|---|---|
| C1 | Start | "Calibration. Face {landmark} and stand still." | Turns to the landmark | `cal_prompt C1` |
| C2 | Countdown | "Starting in three, two, one." (one number per second) | Gets ready | |
| C3 | Standing pose | "Stand up straight. Feet hip-width apart. Arms relaxed at your sides. Look straight ahead." | Takes the pose | |
| C4 | Hold | "Hold still… now." | Freezes | **window starts 0.3 s after "now" ends** |
| C5 | Hold, if moving | "You moved. Hold still." (once, mid-hold; the hold restarts) | Freezes again | hold restarts |
| C6 | End of hold | "Good." | Relaxes | `cal_hold_end` |
| C7 | Arms-out pose | "Now raise both arms straight out to the sides, at shoulder height, palms facing down." | Raises arms | |
| C8 | If arms not level after 6 s | "Raise your arms a little higher, level with your shoulders." | Adjusts | |
| C9 | Hold | "Hold still… now." | Freezes | window starts 0.3 s after "now" (as C4) |
| C10 | End | "Arms down." | Lowers arms | `cal_hold_end` |
| C11 | Pass | "Calibration complete. You can start." | Continues | `calibrate_result: pass` |
| C12 | Fail | "Calibration didn't work: {reason}. Let's try again." → back to C1 (at most 2 retries, then "Please check the devices, then tap Calibrate.") | Redoes it | `calibrate_result: fail` |

Reasons (C12), one short phrase each: "you moved" · "the phone isn't upright in your pocket" ·
"your arms weren't level" · "the AirPods aren't connected" · "the watch isn't sending data".

**Voice rules**
- **Output:** the iPhone's `AVSpeechSynthesizer` speaks through whatever is connected, normally the AirPods. If the AirPods are out, the Watch speaks the same script (watchOS `AVSpeechSynthesizer`) and the phone speaker is the last resort.
- **Timing comes from the speech, not a fixed clock:** the hold starts when "now" *finishes speaking* (`didFinish` callback). Every prompt is logged as an event with start/finish time, so the Mac can rebuild the exact windows.
- **Short and identical every time:** at most ~12 words per prompt, no jargon ("N-pose" and "T-pose" are never spoken), the same wording at every calibration, speech rate slightly slower than default.
- **Priority:** a 🔴 alert interrupts anything; 🟡 warnings wait until the calibration ends.
- **Repeat:** tapping "Repeat" on the Watch replays the last prompt.
- **Audio session:** `.playAndRecord` with `.spokenAudio` mode, `.duckOthers` and `.allowBluetoothA2DP`, and **never `.allowBluetooth`**. The preferred input is set to the **phone's built-in microphone** (needed for the audio-level sensor, addendum §2C). This keeps the AirPods in normal playback mode: if the app used the AirPods' microphone, iOS would switch them to call mode (lower quality, possible effect on head motion). The iPhone app needs the `audio` background mode so speech works while it's in the pocket or in the background (today only the Watch declares a background mode).
- **Audibility check at Go/No-Go:** "Can you hear me? Tap the watch if you can." No tap within 10 s → raise the volume or switch the output.

- **Always face the same landmark** so heading means the same at every calibration. This is the only way to anchor the AirPods' arbitrary heading.

**When to calibrate**

- ✅ Start of the session
- ✅ At the measured interval (device test T20 decides it; ~every changeover until then)
- ✅ Before each trial (marked with the Trial button)
- ✅ After: AirPods reconnect · strap adjusted · phone re-pocketed · crash resume
- ⏰ **Spoken reminder** once the reminder interval (a setting; default 10 min until T20 sets it) has passed since the last good one, or after any event above:
  "Time to recalibrate. When you're ready, face {landmark} and tap the watch." (repeats every 2 min until done or dismissed)
- ➕ **Bonus anchors:** the app logs `still_upright` whenever the user stands still and upright for 2 s. These correct tilt, not heading.

**Check on the phone right after the hold**

| Check | Pass |
|---|---|
| Still | rotation RMS < 0.15 rad/s on every device (same as `calibration.py`) |
| Phone upright | gravity along the phone's long axis > 0.85 |
| Arms out in T-pose | Watch forearm axis within ~20° of horizontal |
| All 3 devices present | samples from each in the window |
| Change since last calibration | angle per device → logged, shown as "drift: 6°" |

- Logged as `calibrate_result` (metrics + per-device rotation). The Mac recomputes them, but this is the field check.

**How the Mac uses many calibrations**

```
 time ───────────────────────────────────────────────▶
        C0            C1            C2            C3
        ├─────────────┼─────────────┼─────────────┤
 A  piecewise:  each frame uses the last calibration before it
 B  blend:      interpolate (slerp) between neighbours → removes steady drift   ← default
```

- Use **A** across segment breaks or next to a failed calibration.
- `ingest_report.json` lists drift per interval (°/min). If it's above ~10° between calibrations, calibrate more often.
- Needed in `live/calibration.py`: handle **many** calibrate events (today it uses only the last) and the T-pose step.
- 🐞 Fix first: Stop during a countdown leaves `calibrationTimer` set, which blocks later calibrations (EXPERIMENT_LOG).

## 10. Problems in the field: detect, fix, alert

> **Rule:** find a problem within seconds, fix it automatically if possible, otherwise tell the
> person on the court, and **never leave the court with an incomplete trial.**

### Four checkpoints

```
  ① Go / No-Go          ② Watchdog            ③ Trial check          ④ Court-exit check
  before Start          every 1 s             after each trial       before packing up
 ──────────────        ──────────────        ──────────────         ──────────────
 all devices live?     rate · gaps ·         every required         every trial ✅?
 rates OK?             frozen · moved ·      stream complete        60 Hz Watch chunks
 battery for plan?     battery · disk ·      in the trial window?     all on the phone?
 disk · Low Power?     heat · Watch alive    → ✅ keep / 🔁 redo      high-rate chunks closed
                                                                      on the Watch?
                                                                    → "Safe to leave"
                                                                      or "Redo trials 3, 5"
      │                     │                     │                      │
      ▼                     ▼                     ▼                      ▼
  Start allowed       auto-fix → alert        shown at once          shown before Stop
```

- **Court-exit check does not wait for high-rate data to transfer.** It only needs the Watch's
  journal to show every high-rate chunk closed and checksummed on the Watch disk (rule 1: the data
  is already safe there). The transfer happens later (§13).
- **Required streams** are chosen per session (default: phone + Watch + AirPods). Starting without one needs an explicit "Record without AirPods" override, which is logged.

### The watchdog loop (runs every 1 s on the phone, a lighter version on the Watch)

```
  measure ──▶ compare with thresholds ──▶ problem?
                                            │ yes
                                            ▼
                                  log event (always)
                                            │
                                  auto-fix possible? ── yes ──▶ try it ──▶ fixed? ── yes ──▶ log "recovered"
                                            │ no                            │ no
                                            ▼                               ▼
                                  alert the person  ◀────────────────────────┘
                                  (escalate if not fixed in 30 s)
```

### Scenarios

**Connection and device**

| Scenario | Detect | Auto-fix | Alert / user action |
|---|---|---|---|
| AirPods disconnect (out of ear, Bluetooth, battery) | `didDisconnect` or no sample for > 1 s | Restart head-motion updates on reconnect | 🔴 "AirPods lost". After reconnect: **recalibrate** (heading reset) |
| AirPods taken by another device (Mac/iPad auto-switch) | Connected but no samples; audio route changes | — | 🔴 "AirPods switched away". Pre-flight: auto-switch off |
| Watch out of range of phone | No live batches for > 3 s | None needed: Watch keeps writing locally | 🟡 "Watch preview paused" (data safe) |
| Watch workout ended (crown press, swipe, watchOS) | Workout state change; no Watch heartbeat | Phone relaunches Watch app via `startWatchApp`; Watch restarts the workout | 🔴 Watch haptic + phone banner |
| Watch or phone app crashed / killed | Unclosed session on launch | Recovery + Resume (§6) | 🔴 "Resume recording?" |
| Phone rebooted / clock jump | `boot_to_unix` changes | New segment | Logged; recalibrate |

**Sampling quality**

| Scenario | Detect | Auto-fix | Alert / user action |
|---|---|---|---|
| **Low sample rate** | 5 s rolling rate < 80% of the rate measured at Go/No-Go | Shed load: stop UDP, pause preview plots | 🟡 then 🔴 if it lasts > 30 s; show cause (heat / Low Power / CPU) |
| Low Power Mode on | `isLowPowerModeEnabled` | — | Blocks Start until turned off; 🔴 if turned on mid-session |
| Overheating | `thermalState` ≥ `.serious` | Shed load (as above) | 🟡 "Phone hot: move to shade between games" |
| Bursty or late delivery | Gaps in arrival but sensor timestamps continuous | None needed (timestamps are sensor time) | Logged only |
| Duplicate or backwards timestamps | Index / timestamp check | Drop duplicates on the Mac, keep raw | Logged only |
| **Frozen sensor** (samples arrive, values don't change) | Variance ≈ 0 for 5 s while another device moves | Restart that device's motion updates | 🔴 if restart fails |
| Saturated accelerometer | Samples at the sensor's maximum | — | Counted; shown in session check |
| Magnetic disturbance (court fences) | Heading jumps while rotation rate is low; `magneticField.accuracy` low | — | 🟡 "Compass disturbed: recalibrate away from the fence" |
| Wrong reference frame (fallback to arbitrary) | `ref_frame` in hello ≠ expected | — | Logged; shown at Go/No-Go |

**Body and placement**

| Scenario | Detect | Alert / user action |
|---|---|---|
| Phone rotated or slipped in pocket | In a still-upright window, gravity direction differs from the last calibration by > 15° | 🟡 "Phone moved: re-seat and recalibrate" |
| Watch rotated or slid on wrist | Same test during the T-pose or arm-hanging rest | 🟡 "Tighten the strap, recalibrate" |
| **Phone fell out of pocket** | Free fall then impact, then flat and still for > 5 s while the Watch keeps moving | 🔴 Watch alarm "Phone dropped" |
| Watch on the other wrist from the settings | Go/No-Go: "raise your watch arm" test checks which side moves | Fix the setting before Start |

**Power and storage**

| Scenario | Detect | Auto-fix | Alert / user action |
|---|---|---|---|
| Battery won't last the plan | Go/No-Go: drain rate × planned minutes vs. charge | — | Blocks Start, shows minutes available per device |
| Battery low mid-session | < 20% any device; projected time left < 10 min | — | 🟡 at 20%, 🔴 at 10%: "Finish this trial and stop" |
| AirPods battery low | The app can't read AirPods battery, so estimate from time connected | — | 🟡 after 3.5 h connected; charge in the case at changeovers |
| Disk full / write error | Write or `fsync` fails; free space < 500 MB | Close the chunk; try again in a new chunk | 🔴 immediately — **never silent** |

**People and process**

| Scenario | Detect | Response |
|---|---|---|
| Forgot to calibrate | Longer than the reminder interval since the last good calibration | Spoken reminder (§9) |
| Trial without full IMU coverage | Trial check ③ | 🔁 "Redo trial 4: AirPods missing 12 s" |
| Forgot to tap the Trial button | Sync gesture detected (3 hops) with no trial marker nearby | Logged as `possible_trial`; ask at court-exit check |
| Forgot to Stop | Still and no activity for > 10 min | Ask; auto-stop after 20 min, cleanly closed |
| Phone call / Siri / notification | Audio-session interruption and route-change events | Logged. Pre-flight: Do Not Disturb |
| Wrong participant or activity typed | — | Edit later; saved as a **correction** in the journal, never an overwrite |
| Wearing gloves / sun glare | — | All alerts are **haptic + sound**, not just on screen |

### Alerts that work on a tennis court: spoken first

Every alert is **spoken in plain words** (same voice and output rules as §9); haptics and the
phone banner are backups.

| Level | Spoken (examples) | Repeat | Backup |
|---|---|---|---|
| 🟢 OK | — | — | — |
| 🟡 Warn | "Heads up: the phone is getting hot." · "Compass disturbed. Recalibrate away from the fence." | once | 1 long tap, banner |
| 🔴 Stop and fix | "Stop. The watch stopped recording." · "Stop. The AirPods disconnected." · "Stop. The phone fell out of your pocket." | every 30 s until fixed or acknowledged | 3 strong taps, banner + sound |
| 🔁 Redo trial | "Redo trial four. The AirPods were missing for twelve seconds." | once | 2 taps, trial card turns red |
| ✅ Recovered | "The watch is recording again." | once | — |

- Every alert phrase names **what** happened and, for 🔴, **what to do**. All phrases live in one
  file (`Shared/voice_prompts.json`) next to the calibration script, so wording is reviewed in one place.
- Spoken alerts are logged like calibration prompts (start/finish time).

- **Debounce:** a problem must last ≥ 2 s before alerting; at most 1 alert per problem per minute.
- **Escalate:** a 🟡 that lasts > 30 s becomes 🔴.
- **One tap to acknowledge** on the Watch; acknowledging is logged too.

### Trial check (③) in detail

After each trial ends (Trial button), check its window `[start − 2 s, end + 2 s]`:

| Check | Pass |
|---|---|
| Each required stream's coverage | ≥ 98% |
| Longest gap | ≤ 0.3 s |
| Rate | ≥ 80% of baseline |
| Last good calibration | Within the reminder interval before the trial, and nothing that resets it since |
| Sync gesture | Detected at the start (3 hops) |

- Result: ✅ **Keep** or 🔁 **Redo**, with the reason. Logged as `trial_check`.
- For Watch data the check uses the live preview at first, then re-checks once that chunk arrives from the Watch.

## 11. Mac: copy → check → back up → clear

```
 ① Copy            ② Check                       ③ Back up          ④ Clear
 Finder / AirDrop  ingest_field.py               2nd drive / cloud  "Clear verified"
 → recordings/     ├ SHA-256 per chunk           (after PASS only)  on phone + Watch
   field/          ├ all chunks present?                            (needs verified.json
                   ├ index gaps + their causes                       copied back)
                   ├ clock fit + drift
                   ├ ingest_report.json  PASS/FAIL
                   └ merged stream.jsonl → motion_io.py
```

- ⚠️ **Never delete** before ② says PASS and ③ is done.

## 12. Aligning with OpenCap: deferred

> **Not part of data collection for now (decided 2026-10-14).** Keep the generic **Trial button**
> and the **sync gesture** in the app, because they are useful without OpenCap (they mark
> activities and give a time reference). The OpenCap-specific parts below, and §2A-B of
> `DATA_COLLECTION_PLAN_ADDENDUM.md`, return when ground-truth comparison starts.

- **App button "OpenCap trial":** logs trial #, Unix time and a note. Tap it when OpenCap starts.
- **Sync gesture** at the start and end of each trial:

  ```
  ── 2 s still ── 3 hops ── 3 head nods ── 2 s still ──
  ```

- **Two-step alignment:**
  - wall clock → within ~1 s (keep automatic date and time on for every phone)
  - gyroscope cross-correlation → within ~1 frame

## 13. Tennis-specific

- 🎾 **Sample rate: high-rate Watch stream always on (decided 2026-10-14).** Watch
  `CMBatchedSensorManager` (800 Hz acceleration, 200 Hz motion, Series 8+, during the workout)
  writes a separate `watch_hf/` chunk stream next to the normal 60 Hz one.
  - **Binary format (decided 2026-10-15).** JSON would be ~250 MB/h. Each `watch_hf/NNNNNN.bin` chunk is:

    ```
    ┌──────────────────────────────┬────────────────────────────────────────────┐
    │ header: 1 JSON line + "\n"   │ fixed-size little-endian records            │
    │ format, version, session,    │ accel  (800 Hz): t f64 · ax ay az f32 = 20 B │
    │ segment, first_index per     │ motion (200 Hz): t f64 · 13 × f32     = 60 B │
    │ stream, boot_to_unix, fields │ each record starts with a 1-byte type tag   │
    └──────────────────────────────┴────────────────────────────────────────────┘
    ```

    About **28 KB/s ≈ 100 MB/h**. Fixed-size records mean a torn chunk is trimmed to its last whole
    record (as §6 does with lines), and the SHA-256 and journal rules are unchanged. The Mac reads
    it with a small `numpy` loader in `ingest_field.py`.
  - **Transfer later (decided 2026-10-15):** 60 Hz chunks go to the phone as they close (§5).
    **High-rate chunks are not sent during play** (saves radio time and battery) and **the
    court-exit check doesn't wait for them** (§10). After the session, keep the Watch near the
    phone with the app open, ideally both charging; the phone shows "High-rate: N / M sent".
    Over Bluetooth this can take tens of minutes (to measure in T7).
  - **Ingest:** if high-rate chunks are still on the Watch, `ingest_field.py` reports
    `watch_hf: PENDING` (not FAIL) and the session can't be marked verified or cleared until they arrive.
  - **Battery:** measure the drain in device test T7; Go/No-Go uses it for the "battery for the
    planned minutes" check.
  - **Pass/fail:** a missing high-rate stream is a 🔴 at Go/No-Go, like any required stream.
- 💥 **Saturation:** serves and impacts can hit the accelerometer's limit, more so with the Watch on the racket arm. The ingest script flags samples near it.
- ☀️ **Heat:** log `thermalState` every 60 s; warn at `.serious`.
- 📵 **Interruptions:** turn on Do Not Disturb. A call takes over the audio route and can cut the AirPods.

## 14. Field checklist

**Before**
- [ ] Every device above 80%; Low Power Mode **off** on phone and Watch
- [ ] AirPods: automatic switching **off**, paired to this iPhone only
- [ ] Do Not Disturb on; automatic date and time on
- [ ] Watch strap tight; phone in an armband or fitted pocket
- [ ] **Go / No-Go is all ✅** (devices, rates, battery for the planned minutes, disk) → Start
- [ ] Spoken calibration (face the landmark) → "Calibration complete" → sync gesture
- [ ] Review screen: 30 s of knee raises + head turns look right

**During**
- [ ] Trial button + sync gesture at every trial
- [ ] After each trial: ✅ Keep or 🔁 Redo **right away**, before moving on
- [ ] Any 🔴 alert: stop playing, fix it, recalibrate if asked
- [ ] Between games, glance at the Watch status if no alert has been spoken
- [ ] Recalibrate from the Watch when the spoken reminder asks (or at changeovers)

**After**
- [ ] **Court-exit check says "Safe to leave"** (all trials ✅, 60 Hz Watch chunks on the phone, high-rate chunks closed on the Watch) → Stop
- [ ] Session check card: PASS (WARN → note why in the session sheet)
- [ ] Keep the Watch near the phone (app open, charging) until "High-rate: all sent"
- [ ] Same day: copy → ingest **PASS** (no `watch_hf: PENDING`) → back up → clear

**Session sheet:** ID · participant · date · court · device placement · trial list · notes

## 15. Failure tests before the first field day

Run these **on devices only after** every simulated test in `TEST_PLAN.md` passes; T20 runs last. the same
scenarios are rehearsed there first with fakes and replayed recordings.

| # | Do this | Expect |
|---|---|---|
| T1 | Force-quit the phone app at 5 min, relaunch, Resume | 1 segment break; data intact; Watch complete |
| T2 | Walk 3 min away from the phone wearing the Watch | Watch data complete; preview gap logged |
| T3 | Take the AirPods out for 30 s | Gap bracketed by disconnect/connect events |
| T4 | Hard power-off of the phone mid-session | ≤1 s lost; open chunk recovered |
| T5 | Lock + pocket mode, 20 min | No gap |
| T6 | Mirrored workout, phone app in background, 20 min | Phone + AirPods continuous → decides §7 |
| T7 | Full 60 min tennis rehearsal | PASS; phone/Watch >99%, AirPods >95% |
| T8 | Flip 1 byte in a copied chunk | Ingest FAILs that chunk |
| T9 | After T1 and T3, open the review screen | Gaps show in the timeline with their causes |
| T10 | Calibrate while swaying | ❌ "You moved, redo" |
| T11 | Stand still, calibrate twice 10 min apart | Drift shown on phone matches the Mac report |
| T12 | Turn on Low Power Mode before Start, then mid-session | Start blocked; mid-session 🔴 + rate drop logged |
| T13 | Press the Watch crown to end the workout | Watch app relaunched, workout restarted, gap logged |
| T14 | Switch AirPods to a Mac mid-session | 🔴 "AirPods switched away" within 3 s |
| T15 | Drop the phone on grass while moving the Watch | 🔴 "Phone dropped" on the Watch |
| T16 | Fill the phone's disk to < 500 MB free | Go/No-Go blocks; mid-session 🔴, no silent loss |
| T17 | Run a trial with the AirPods out for 5 s | Trial check says 🔁 Redo with the reason |
| T18 | Full spoken calibration on a court, with wind and play nearby | Every phrase understood first time; audibility check passes |
| T19 | Speak continuously through the AirPods for 5 min while recording, **with the audio-level sensor on** | AirPods stay in playback mode (not call mode); motion rate and gaps unchanged vs silent |
| T20 | **How long calibration holds** (last stage, after T1-T19 and T21): calibrate once, play normally, and every 5 min stand in the calibration pose for 5 s *without* recalibrating; repeat on 2 days | Per device: angle from the calibration pose at each check. **Interval = time until any device exceeds 10°** (rounded down to whole minutes); set it as the reminder default |
| T21 | After a 60 min session, transfer the high-rate chunks with Watch and phone side by side | All arrive, SHA verified; time taken recorded (sets expectations for §13) |

## 16. Build order

```
 ⓪ Test harness            core logic in a Swift package · fake motion / clock / files / link / voice
        │                  · replay of real recordings · Mac tests (see TEST_PLAN.md)
 ① Phone recorder          chunks · journal · fsync · record-only · health events · crash recovery
        │
 ② Watch local + transfer  chunks · journal · transferFile per chunk + ack
        │                  · high-rate stream (binary chunks, sent after the session)
        │
 ③ ingest_field.py         checks · report · merged stream · shared thresholds file
        │
 ④ Phone preview           live strip · review screen (from disk) · session check card
        │
 ⑤ Calibration + voice     timer bug fix · Watch-started spoken routine (§9) · on-phone check
        │                  · spoken reminders and alerts · multi-calibration blend in calibration.py
 ⑥ Keeping alive           workout mirroring · tests T5–T6
        │
 ⑦ Watchdog + alerts       Go/No-Go · per-second checks · auto-fixes · spoken alerts
        │                  · trial check · court-exit check
 ⑧ Trial button + sync     + extra sensors (addendum §2C: barometer, magnetometer,
        │                  audio level, UWB) · OpenCap parts deferred
        │
 ⑨ All simulated tests green (TEST_PLAN.md) → device tests T1–T19, T21 → T20 sets the calibration interval → first field session
```

> **Decisions (2026-10-14):** build the **full design**, and
> **each step's tests must all pass before the next step starts** (gates in `TEST_PLAN.md` §5).
> Signing: **rebuild and reinstall every 7 days** (free Apple ID); Go/No-Go shows days left.
>
> **Confirmed assumptions (2026-10-14):** solo recording, everything from the Watch with voice
> guidance · main sessions on a tennis court, ~1 h, no Wi-Fi, no Mac · iPhone in a front trouser
> pocket · high-rate Watch stream (800 Hz acceleration + 200 Hz motion) **always on** (§13) ·
> Watch on the **racket arm**, phone in the pocket on the same side · participants: **only the two
> of us** (no consent step needed; still use participant codes) · offload **the same day** (§11) ·
> **calibration interval chosen by measurement** in device test T20 (until then the reminder interval is a setting, default 10 min).

- The high-rate stream is **required, always on**, built in ② (tests W8-W10).
- ⓪ comes first: every later step is tested on the Mac and in the simulators before it touches a device.
- ① gives most of the reliability gain; ④ is how you'll *see* it working; ⑦ stops you wasting court time.

## 17. Design review (2026-10-14)

### Feasibility

| Item | Verdict | Risk / action |
|---|---|---|
| Chunks, `fsync`, journal, recovery (§4, §6) | ✅ Standard file APIs | Low |
| Watch writes locally + `transferFile` (§5) | ✅ Supported; watchOS queues and retries transfers | Transfers can be slow while the phone app is suspended; the design already tolerates that |
| **Phone kept alive by workout mirroring (§7)** | ⚠️ API exists (iOS 17 / watchOS 10) | **Unverified:** whether Core Motion and especially **AirPods head motion keep delivering while the phone app is in the background.** Decide with T6 early; the foreground pocket mode is the fallback |
| **Spoken prompts (§9, §10)** | ✅ `AVSpeechSynthesizer` on iPhone and Watch | Needs the iPhone `audio` background mode. Check that speech on the AirPods doesn't disturb head-motion data (test V7) |
| Swift Charts review screen (§8) | ✅ | Downsample to ~500 points per plot |
| AirPods battery | ❌ Not readable by apps | Time-connected estimate only (already in §10) |
| "Phone dropped" detection | ⚠️ Feasible | Jumps also produce free fall: require "flat and still for > 5 s" (already in §10); tune on recordings |
| High-rate Watch stream (§13) | ✅ Series 8 qualifies | ~10× data and more battery. **Decided: always on, binary format, transferred after the session** |
| **App signing** | ⚠️ **Free Apple ID installs expire after 7 days** | **Decided: rebuild every 7 days.** Store the build date in the app; Go/No-Go blocks Start if the build expires within the planned session and says "Rebuild the app: it expires in N days" |
| Scope | ⚠️ Large for a course timeline | **Decided: full design**, built step by step, each step gated on its tests (`TEST_PLAN.md` §5) |

### Usability

| Issue | Change |
|---|---|
| Buzzes are hard to feel during play | **Done:** every instruction and alert is spoken (§9, §10) |
| The person on the court can't read screens | Voice + Watch only. Every action during a session must be possible from the Watch with one large button: Calibrate, Trial, Repeat, Acknowledge |
| Too many alert types → alerts get ignored | 🟡 is spoken **once**; only 🔴 repeats; debounce and escalation rules in §10 |
| "Face the net" only works on a tennis court | `{landmark}` is set in Setup |
| Jargon in prompts ("N-pose", "T-pose", "chunk") | Banned from spoken text; the script uses body instructions only |
| Who does what | Define roles: **solo** (everything from the Watch, voice-guided) or **with an operator** (operator holds a second phone/Mac for the live view). Most sessions are solo, so design for solo first |
| Frequent calibration interrupts play | Tie it to natural breaks (changeovers); the reminder repeats instead of nagging continuously |
| Hearing the voice on a loud court | Go/No-Go audibility check (§9); haptics stay as backup |

### Missing from the design (now added or to add)

| Missing | Where |
|---|---|
| Spoken calibration script and voice rules | §9 (added) |
| Spoken alert wording, `Shared/voice_prompts.json` | §10 (added) |
| Prompt start/finish logged as events, so the Mac rebuilds calibration windows exactly | §9 (added) |
| A way to test everything without devices | §16 ⓪ + `TEST_PLAN.md` (added) |
| Signing expiry and app version in each session's journal | Add `app_version`, `build_date`, `signing_expires` to `session_open` |
| Settings check before Start: wrist side, pocket side, screen direction, landmark | Go/No-Go (extend ①: spoken "Raise your watch arm" test already listed in §10) |
| In-app session sheet instead of paper | Setup screen fields; saved in `session_open` |
| What to do if the voice output fails (no audio route) | Fall back to Watch speech, then haptics + phone banner; log `voice_unavailable` |
| Microphone use switching the AirPods to call mode | Built-in mic only, no `.allowBluetooth` (§9 voice rules); checked in T19 |
| High-rate transfer delaying the end of a session | Binary format; court-exit check needs only 60 Hz chunks (§10, §13) |
