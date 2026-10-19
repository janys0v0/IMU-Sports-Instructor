# Decisions

Every project decision in one place, newest last. When a decision changes, edit its row and the
date; don't leave the old version in other docs. Other docs link here instead of repeating the "why".

## Made

| Date | Decision | Why | Where it applies |
|---|---|---|---|
| 2026-10-14 | **Build the full design**, stage by stage; each stage's tests pass before the next starts | Field days are costly; bugs must be caught on the Mac | [`dev-plan.md`](dev-plan.md) |
| 2026-10-14 | **Solo recording:** everything controlled from the Watch, guided by voice | Usually one person on court | design §7, §8 |
| 2026-10-14 | **Setting:** tennis court, ~1 h sessions, no Wi-Fi, no Mac | Target use case | design §1 |
| 2026-10-14 | **Placement:** Watch on the racket arm; iPhone in the front trouser pocket on the same side; AirPods in | Matches the model inputs (head, wrist, thigh) | design §1 |
| 2026-10-14 | **High-rate Watch stream always on** (800 Hz accel + 200 Hz motion) | Tennis strokes are too fast for 60 Hz | design §2 |
| 2026-10-14 | **Participants:** only the two of us; participant codes in all files | No consent step needed now | design §11 |
| 2026-10-14 | **Offload the same day**; delete from devices only after ingest PASS + backup | No single point of loss | design §10 |
| 2026-10-14 | **Recalibration interval measured** by test T20; reminder setting defaults to 10 min until then | Drift rate is unknown for our devices | design §7 |
| 2026-10-14 | **Free Apple ID signing:** rebuild every 7 days; Go/No-Go shows days left | No paid developer account | design §8 |
| 2026-10-14 | **OpenCap deferred** until ground-truth comparison starts; Trial button and sync gesture kept | Focus on reliable IMU collection first | [`opencap.md`](../deferred/opencap.md) |
| 2026-10-14 | **Every instruction and alert is spoken**; haptics are backup | Buzzes are hard to feel during play | design §7 |
| 2026-10-14 | **Calibration = standing pose + arms-out pose**, started from the Watch | Fixes the E02 forearm calibration issue | design §7 |
| 2026-10-15 | **High-rate data in a binary format**, transferred after the session; the court-exit check needs only the 60 Hz chunks | JSON would be ~250 MB/h; transfer must not delay leaving | design §2, §3, §8 |
| 2026-10-15 | **Microphone: phone's built-in mic only**, never `.allowBluetooth` | Using the AirPods mic switches them to call mode | design §7 |
| 2026-10-15 | **Extra sensors** (barometer, magnetometer, audio level, optional UWB) as new packet types | Proposal hypothesis; old packets unchanged | design §9 |
| 2026-10-15 | **Repo:** private GitHub repo `IMU-Sports-Instructor`; recordings and model files out of git; MobilePoser / IMUCoCo pinned + patched; Conventional Commits; no AI co-author lines | Clean, small, consistent history | [`CONTRIBUTING.md`](../../CONTRIBUTING.md) |
| 2026-10-16 | **One format for branches, commits and PRs** (shared type/scope vocabulary, PR sections, squash merge), checked by `tools/check_format.py` | Consistent, searchable history | [`CONTRIBUTING.md`](../../CONTRIBUTING.md#commit-branch-and-pr-format) |
| 2026-10-16 | **Human testing:** one early device check (stage 0b); all other device tests in stage 9 | Research answered most device questions | [`dev-plan.md`](dev-plan.md), [`device-research.md`](../research/device-research.md) |
| 2026-10-17 | **One control system:** the iPhone owns the session; Start, Stop, Calibrate, Trial, Repeat and OK do the same from either device, and the Watch shows the iPhone's state and buttons. "Watch only" recording only when the iPhone is unreachable; the iPhone joins it when back | Starting each device separately opened two sessions on the first device run | design §7 |
| 2026-10-19 | **First accuracy check against single-camera video** (Apple Vision 3D pose, E04); OpenCap stays deferred | Available now with no setup or download; gives joint-angle agreement on our own motions. Limits: one camera, Vision's own error | [`dev-plan.md`](dev-plan.md) stage 11 |

## Open

| Question | Options | Recommendation | Decided by |
|---|---|---|---|
| How does the iPhone app stay awake in a pocket? | Background location (3 km) · workout mirroring · pocket mode (foreground) | Background location; mirroring optional; pocket mode as fallback ([`device-research.md`](../research/device-research.md) §1) | Stage 0b device check |
