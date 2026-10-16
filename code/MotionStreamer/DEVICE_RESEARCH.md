# Device research: what we know without testing

> Online research (2026-10-16) to answer the device questions in [`DEV_PLAN.md`](DEV_PLAN.md)
> without human testing. Sources are Apple documentation, Apple's WWDC sessions, and Apple
> Developer Forums threads with Apple engineer (DTS) answers. Each finding is marked:
> ✅ confirmed by Apple · ⚠️ reported by developers, not documented · ❓ still unknown.

## Our devices (from our own recordings)

- **Watch:** `Watch6,14` = **Apple Watch Series 8**, watchOS 26.6 (from `watch_hello` events).
- **iPhone:** iPhone 16 (delivers 33.4 Hz device motion at 60 Hz requested; `MotionFormat.swift`).
- **Measured rates (E03):** iPhone 33.5 Hz, Watch 66.4 Hz, AirPods 50 Hz delivered.

## Summary

| Question | Answer | Still needs a device? |
|---|---|---|
| Does the phone keep recording motion in the background? | ✅ **Only if the app is kept awake by a background mode.** Core Motion has no background support of its own | Yes, but only to confirm (low risk) |
| Which background mode keeps it awake? | ✅ Location works (Apple DTS, 99.5 % of samples on iOS 26.5). ⚠️ Workout mirroring not documented to keep it awake | Confirm with our app |
| Do AirPods keep streaming when the phone app is in the background? | ❓ Not documented anywhere | **Yes** |
| Can the Watch read AirPods motion instead? | ⚠️ No: `isDeviceMotionAvailable` is false on watchOS in practice | No |
| Does speech through the AirPods disturb head motion? | ❓ No source | Yes, but **not blocking** (see below) |
| Does the high-rate Watch stream work on our Watch? | ✅ Series 8 supports 800 Hz accel + 200 Hz motion, during an active workout | No (battery only) |
| Accelerometer saturation during strokes | ❓ Series 8 has a 256 g high-g sensor; the range of the batched stream is undocumented | Check in the first real recording |
| Watch → phone transfer speed | ❓ Undocumented; Bluetooth-level speeds | Measure in stage 9 (T21) |
| Does workout mirroring work in the simulator? | ✅ **No** (Apple DTS) | — |

## 1. Phone recording in the background

- ✅ **Core Motion doesn't keep an app awake.** Apple DTS: "CoreMotion itself doesn't provide any
  direct support for actually running in the background. Motion apps that run in the background use
  one or more of our other background APIs to stay awake — typically some combination of
  CoreLocation, HKWorkoutSession, and (possibly) 'audio'." What matters is that the app is "awake
  in the background", not which API keeps it awake. ([forum 841001])
- ✅ **Measured on iOS 26.5.2** in the same thread: device motion with a low-accuracy background
  location session running: **1366 / 1373 samples (99.5 %)** over 137 s in the background.
  Without it: **2 / 1286**; updates stop "within a few seconds" of leaving the foreground.
- ⚠️ **Testing trap:** "With the Xcode debugger attached the app is not suspended." Every
  background test must be run **launched from the Home screen, without Xcode attached**, or it
  passes falsely.
- ⚠️ **Workout mirroring** (design §7) launches the phone app in the background and gives it
  "10 seconds" to take the session ([WWDC23 10023]). Apple does **not** say the phone app then stays
  awake for the whole workout.
- ⚠️ **Mirroring is buggy on iOS/watchOS 26.0–26.1:** the mirrored session disconnects or
  `startMirroringToCompanionDevice` hangs. Apple's workaround: call it only after the session is
  prepared or running (`prepare()` first). No fixed version is stated. ([forum 804276])
- ✅ **Mirroring doesn't run in simulators** ("workout mirroring is not supported in simulators").
  The sample project "needs to run on physical devices". ([forum 765469], [Apple sample])
- ✅ **iOS 26 added workout sessions on iPhone itself** ([WWDC25 322]), with crash recovery through
  a scene delegate. Apple's guidance with a Watch: start the workout on the Watch and mirror it.
- Apple's DTS also notes the App Store reviews background modes against what the app does. **This
  app isn't going to the App Store**, so a location keep-alive is acceptable here.

**Implication (recommended change to design §7):**
- **Primary keep-alive: background location** at the lowest accuracy (3 km, no updates in
  practice), which Apple confirms keeps motion flowing. It also adds the `location` background mode
  and a "When In Use" location permission.
- **Workout mirroring: optional extra**, not relied on (undocumented runtime + 26.x bugs).
- **Pocket mode: last fallback**, unchanged.
- Battery: a 3 km-accuracy location session uses little power, but it's measured in the device check.

## 2. AirPods head motion

- ✅ API available on iOS 14+, macOS 14+; data from "audio products that support spatial audio with
  dynamic head tracking, like AirPods Pro". ([WWDC23 10179], [Apple docs])
- ✅ **One bud at a time:** "motion data is delivered to you from one bud at a time"; if that bud is
  removed, the other one takes over. ([WWDC23 10179])
- ✅ **Ear detection:** taking the buds out gives a disconnect event; putting them back gives a
  connect event. Our watchdog's A1 test matches this. ([WWDC23 10179])
- ✅ `NSMotionUsageDescription` is required, or the app crashes when updates start (already in our
  `project.yml`).
- ⚠️ **watchOS:** the docs list watchOS 7+, but developers report `isDeviceMotionAvailable` is
  **false** on the Watch; no Apple answer. ([forum 739005]) → AirPods motion must stay on the phone.
- ⚠️ A macOS project reports AirPods only send motion while they're the **active audio output**.
  Not confirmed on iOS. If true, speaking through the AirPods would *help* keep motion flowing.
- ❓ **Background:** no source says whether headphone motion keeps flowing while the phone app is
  awake in the background. **This is the one real unknown**, and the most important device check.
- ❓ **Speech / microphone vs head motion:** no source. Phone calls use the Bluetooth hands-free
  profile; whether our built-in-mic + A2DP setup affects head motion is undocumented.

## 3. High-rate Watch stream (`CMBatchedSensorManager`)

- ✅ "Apple Watch Series 8 and Ultra support both high rate accelerometer and device motion" —
  **our Watch qualifies.** ([WWDC23 10179])
- ✅ Rates: **800 Hz accelerometer, 200 Hz device motion** (vs 100 Hz max for `CMMotionManager`).
- ✅ Delivery: "a batch of data per second"; suited to apps "without very tight latency
  requirements" (fine for recording).
- ✅ "you need to have an active HealthKit workout session to get data" (we already run one).
- ✅ Check `isAccelerometerSupported` / `isDeviceMotionSupported`; errors surface if motion isn't
  authorized or the platform is unsupported.
- ✅ **Watch background limits** ([Apple: Running workout sessions]):
  - the app "continues to run throughout the entire workout session";
  - "If your app uses an excessive amount of CPU while in the background, watchOS may suspend it" →
    keep high-rate writing light (binary records, no JSON on the Watch for that stream);
  - "If your app plays audio or provides haptic feedback during the workout session, you must also
    add the Audio background mode" → **add `audio` to the Watch's `WKBackgroundModes`** for Watch
    speech and haptics;
  - after a crash, `handleActiveWorkoutRecovery()` + `recoverActiveWorkoutSession` restore the
    workout → use in the Watch's crash recovery (design §6).
- ❓ Accelerometer range of the batched stream: undocumented. Series 8 has "a high-g accelerometer
  that handles up to 256 g" for crash detection ([Apple specs]). Whether the batched stream clips
  on ball impact shows up in the first real recording (ingest flags near-maximum values).
- ❓ Battery drain: not documented; measured in the device check.

## 4. Watch → phone transfer

- ✅ "The timing of file transfers is based on system conditions, and ... larger files may take
  longer"; Watch Connectivity works over Bluetooth or the same Wi-Fi. ([WWDC21 10003])
- ✅ Move a received file out of the inbox before the delegate method returns; the system deletes it.
- ⚠️ No published speed. One user reports **2-3 Mbps** through the phone's Bluetooth link. At that
  rate ~100 MB of high-rate data takes roughly **5-7 min**. Our design already sends high-rate
  chunks after the session, so this only affects waiting time.

## 5. Free Apple ID signing

- ❓ Not confirmed by a source. Our app already runs with HealthKit workouts on our devices, so the
  capability works with our current signing. The 7-day expiry stays as designed (Go/No-Go shows days left).

## What this changes

| Before research | After research |
|---|---|
| Stage 0b: half-day device spike, 3 open questions | **One ~1-hour device check**, mainly AirPods-in-background |
| Keep-alive: workout mirroring first | **Background location first**, mirroring optional |
| T19 (speech vs AirPods) blocking | **Not blocking:** the `Voice` protocol can route speech to the Watch if the AirPods are affected |
| High-rate stream support unknown | ✅ Confirmed for our Series 8 |
| E1, E2, E4 simulator tests include mirroring | **Mirroring can't be simulated**; those parts move to device tests |
| — | All background device tests run **without the Xcode debugger attached** |
| — | Watch needs the `audio` background mode for speech and haptics |

### The one remaining early device check (~1 hour)

One throwaway build, launched from the Home screen with Xcode detached:
1. Phone: background location (3 km) + phone motion + AirPods motion, phone locked in a pocket, 20 min.
2. During those 20 min, speak a short phrase through the AirPods every 30 s.
3. Watch: workout + high-rate stream for the same 20 min.
4. Afterwards: count samples per device (foreground vs background), note battery % used per device.

Pass: phone and AirPods ≥ 95 % of samples while locked; AirPods rate unchanged around speech;
Watch high-rate counts ≈ 800 / 200 per second.

## Sources

- [forum 841001]: [Does background CMDeviceMotion delivery depend on an active Core Location session?](https://developer.apple.com/forums/thread/841001) (Apple DTS answer)
- [forum 804276]: [watchOS 26.0.2 / iOS 26.0.1 + Workout Session Mirroring Failure](https://developer.apple.com/forums/thread/804276)
- [forum 765469]: [Mirroring Workouts Sample Code Doesn't Work With Simulators](https://developer.apple.com/forums/thread/765469)
- [forum 739005]: [CMHeadphoneMotionManager on watchOS](https://developer.apple.com/forums/thread/739005)
- [WWDC23 10023]: [Build a multi-device workout app](https://developer.apple.com/videos/play/wwdc2023/10023/)
- [WWDC23 10179]: [What's new in Core Motion](https://developer.apple.com/videos/play/wwdc2023/10179/)
- [WWDC25 322]: [Track workouts with HealthKit on iOS and iPadOS](https://developer.apple.com/videos/play/wwdc2025/322/)
- [WWDC21 10003]: [There and back again: Data transfer on Apple Watch](https://developer.apple.com/videos/play/wwdc2021/10003/)
- [Apple sample]: [Building a multidevice workout app](https://developer.apple.com/documentation/HealthKit/building-a-multidevice-workout-app)
- [Apple: Running workout sessions](https://developer.apple.com/documentation/HealthKit/running-workout-sessions)
- [Apple docs]: [CMHeadphoneMotionManager](https://developer.apple.com/documentation/coremotion/cmheadphonemotionmanager), [workoutSessionMirroringStartHandler](https://developer.apple.com/documentation/healthkit/hkhealthstore/workoutsessionmirroringstarthandler), [HKWorkoutSession](https://developer.apple.com/documentation/healthkit/hkworkoutsession)
- [Apple specs]: [Apple Watch Series 8 technical specifications](https://support.apple.com/en-sg/111848)
- Transfer speed anecdote: [Apple Community: Watch Ultra 2 connection very slow](https://discussions.apple.com/thread/255152330)
