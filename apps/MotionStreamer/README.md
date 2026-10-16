# MotionStreamer (Phase 1)

iPhone + Apple Watch app that streams 60 Hz device motion to a Mac over UDP and
saves every packet on the iPhone.

```
Watch (CMMotionManager, workout session) --WCSession, 10-sample batches--> iPhone
iPhone (CMMotionManager) --UDP JSON packets--> Mac: pipeline/live/receiver.py
```

## One-time setup
1. Xcode -> Settings -> Components: install the **watchOS** platform (needed to build the Watch app).
2. iPhone and Watch: Settings -> Privacy & Security -> **Developer Mode** on.
3. `brew install xcodegen`, then in this folder: `xcodegen generate`.
4. Open `MotionStreamer.xcodeproj`. For **both** targets: Signing & Capabilities -> Team.
   If Xcode says the bundle ID is unavailable, change `BUNDLE_ID` in `project.yml` and regenerate.
5. Run the `MotionStreamer` scheme on the iPhone. The Watch app installs with it
   (or install it from the Watch app on the iPhone -> Available Apps).
6. First launch: allow Motion, Local Network and Health (workout) permissions on both devices.

## Each session
1. Mac, from the repo root: `.venv/bin/python -m pipeline.live.receiver` and note the printed IP.
2. Mac and iPhone on the same Wi-Fi network.
3. iPhone app: enter the Mac IP, port 5005, participant, activity, Watch wrist.
4. Put the Watch on that wrist and the iPhone in the **same-side** trouser pocket.
5. Tap **Start**. The Watch app launches itself and starts a workout session.
6. Tap **Calibrate** and stand still 3 s. Use **Trial marker** at each trial boundary.
7. Tap **Pocket mode** (screen turns off near your leg; long-press to unlock), then pocket the phone.
8. Tap **Stop**. The receiver prints the summary and the Phase 1 pass/fail.

## Data
- iPhone: Files app -> MotionStreamer -> `sessions/<id>/stream.jsonl` + `manifest.json`
  (also visible in Finder when the iPhone is connected).
- Mac: `recordings/<id>/mac_stream.jsonl` (each packet + `recv_mac_unix`) and `summary.json`.

Packet types (one JSON object per UDP datagram / file line):
- `imu`: `device`, `loc`, `seq`, `first_index`, `rate_hz`, `boot_to_unix`, `ref_frame`, `s` (samples).
  Each sample: `[t, qx, qy, qz, qw, ax, ay, az, gx, gy, gz, rx, ry, rz]`; `t` is
  `CMDeviceMotion.timestamp` (s since that device booted), accelerations in g, rotation in rad/s.
  Watch packets add `sent_watch` and `recv_phone`.
- `event`: `start`, `stop`, `calibrate`, `marker`, `watch_hello`, `watch_reachable`,
  `watch_unreachable`, `watch_launch_failed`.
- `sync`: every 5 s, `t_phone_send`, `t_watch`, `t_phone_recv` for Phase 2 clock mapping.

## Test the receiver without devices (from the repo root)
```
.venv/bin/python -m pipeline.live.receiver --port 5099 &
.venv/bin/python -m pipeline.live.fake_phone --port 5099 --seconds 20
```

## Known limits
- Used for 35 recorded sessions (iPhone 16, Apple Watch Series 8 on watchOS 26.6).
- **Bug:** pressing Stop during the calibration countdown blocks later calibrations until the app
  is relaunched (fix planned in stage 0 of [`docs/plan/dev-plan.md`](../../docs/plan/dev-plan.md)).
- The field-recording redesign (on-device chunks, crash recovery, spoken calibration) is in
  [`docs/plan/design.md`](../../docs/plan/design.md); this README describes the app as it is today.
- Pocket mode relies on the proximity sensor keeping the app in the foreground with the screen off.
  If iOS still suspends the app in a pocket, fall back to leaving the screen on (it already
  disables auto-lock while recording).
- If the iPhone is unreachable, the Watch keeps up to 10 s of batches and retries; older batches are dropped and counted.
