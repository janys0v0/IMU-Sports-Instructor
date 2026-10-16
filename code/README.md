# ES 224 — Live full-body motion capture from iPhone, Apple Watch and AirPods

The phone, Watch and AirPods stream motion to a Mac. [MobilePoser](https://github.com/SPICExLAB/MobilePoser) (UIST 2024) turns that motion into a full SMPL body mesh, live or from a recording.

```
Watch ──WCSession──▶ iPhone app ──UDP JSON──▶ Mac: live/live_viewer.py ──▶ Open3D mesh window
AirPods ─CoreMotion─▶    (MotionStreamer)          │
                                                  └─▶ recordings/<session>/mac_stream.jsonl
recordings ──▶ live/replay.py · plot_trajectories.py · knee_pca.py ──▶ videos, plots, JSON
```

## Tree

```
project/code/
├── README.md
├── PHASE0_LOG.md                 setup, baseline metrics, model-code changes
├── requirements-mac.txt
├── MotionStreamer/               iPhone + Watch app (XcodeGen: project.yml)
│   ├── Shared/MotionFormat.swift     packet format
│   ├── iOS/
│   │   ├── StreamController.swift    phone/Watch/AirPods streams, events
│   │   ├── UDPSender.swift           UDP to the Mac
│   │   ├── SessionRecorder.swift     on-phone copy of each session
│   │   ├── HeadphoneMonitor.swift    AirPods pairing check
│   │   └── ContentView.swift         UI
│   └── Watch/
│       ├── WatchStreamer.swift       Watch motion -> iPhone
│       └── WatchApp.swift
├── MobilePoser/mobileposer/      pose model (upstream repo)
│   ├── models/net.py                 online/offline inference
│   ├── checkpoints/weights.pth       pretrained weights
│   ├── smpl/basicmodel_m.pkl         SMPL body model
│   └── config.py                     paths, device slots, combos
├── receiver/
│   ├── phase1_receiver.py            log packets, coverage summary
│   └── fake_phone.py                 synthetic test packets
├── live/
│   ├── motion_io.py                  load recordings
│   ├── resample.py                   30 Hz grid
│   ├── calibration.py                device -> body frame
│   ├── replay.py                     recording -> model -> video/plots
│   ├── live_viewer.py                real-time mesh window
│   ├── send_recording.py             replay a recording over UDP
│   ├── plot_trajectories.py          head/thigh over time
│   └── knee_pca.py                   knee-path PCA, per-rep metrics
├── phase0/                       IMUPoser-dataset check: metrics, demo video
└── recordings/<session>/
    ├── mac_stream.jsonl              every packet
    ├── summary.json                  coverage per stream
    └── phase2/                       calibration.json, *.npz, *.png, *.mp4
```

## Folders

| Path | What it is |
|---|---|
| `MotionStreamer/` | iPhone + Watch app (Swift, XcodeGen). Streams 14-number motion samples over UDP. Setup: `MotionStreamer/README.md` |
| `MobilePoser/`, `IMUCoCo/` | Upstream model repos, not in git: cloned at pinned commits and patched by `tools/setup_upstream.sh` (`patches/`). Install notes: `PHASE0_LOG.md` |
| `receiver/` | `phase1_receiver.py` logs packets and checks stream coverage. `fake_phone.py` sends synthetic packets |
| `live/` | Mac pipeline: calibration, replay, live viewer, analysis (below) |
| `recordings/<session>/` | `mac_stream.jsonl` (every packet), `summary.json` (coverage), `phase2/` (outputs) |
| `phase0/` | Phase 0 check of the published model on the IMUPoser dataset: metrics and demo video |
| `PHASE0_LOG.md` | Environment, install deviations, baseline metrics, changes to model code |

## iPhone app (`MotionStreamer/`)

| File | Role |
|---|---|
| `Shared/MotionFormat.swift` | Packet format: `[t, quat xyzw, user_acc, gravity, rot_rate]` |
| `iOS/StreamController.swift` | Phone, Watch and AirPods streams; Start/Stop and Calibrate events; clock-sync pings |
| `iOS/UDPSender.swift`, `SessionRecorder.swift` | UDP to the Mac; copy of the session saved on the phone |
| `iOS/HeadphoneMonitor.swift` | AirPods pairing check (connection, rate, live head angles) |
| `Watch/WatchStreamer.swift` | Watch motion during a workout session, sent to the phone in 10-sample batches |

## Mac pipeline (`live/`)

| File | Role |
|---|---|
| `motion_io.py` | Loads a recording into one stream per device (`left_pocket`, `head`, …) and maps devices to MobilePoser slots |
| `resample.py` | Resamples each device to 30 Hz and marks frames that fall in sensor gaps |
| `calibration.py` | Standing calibration: device → body frame (x left, y up, z forward). The phone uses magnetic north; the AirPods use their own forward axis |
| `replay.py` | Recording → MobilePoser offline. Runs checks and saves model outputs, plots and videos |
| `live_viewer.py` | **Real-time viewer.** Receives UDP, calibrates when the app sends Calibrate, runs the model at 30 Hz and draws the mesh |
| `send_recording.py` | Sends a saved recording to the viewer in real time, for testing without devices |
| `plot_trajectories.py` | Head and thigh angles, heights and acceleration over time, plus a side view |
| `knee_pca.py` | PCA of the 3D knee path during knee raises, plus per-repetition metrics |

## Common commands

Run from `code/` with the project environment (`code/.venv`, Python 3.9):

```bash
PY=.venv/bin/python
```

**Live demo:** start the viewer, enter the printed IP in the app, then tap Start → Calibrate:

```bash
$PY live/live_viewer.py --screen leg
```

**Test without devices:** start the viewer, then in a second terminal:

```bash
python3 live/send_recording.py recordings/20261001-162235-P01
```

**Mesh video from a recording:** writes `phase2/replay_lp_h.mp4`:

```bash
$PY live/replay.py recordings/<session> --head --single --screen leg --render --no-tran
```

**Analysis plots:**

```bash
$PY live/plot_trajectories.py recordings/<session> --screen leg
```

```bash
$PY live/knee_pca.py recordings/<session> --screen leg
```

## Things to know

- **One listener at a time:** `live_viewer.py` and `receiver/phase1_receiver.py` both use UDP port 5005. Run only one.
- **Calibrate standing completely still** with the phone screen facing the leg (`--screen leg`). A failed check (rot > 0.2 rad/s) means you moved during the hold.
- **Latency:** about 0.2 s, mostly MobilePoser's 5-frame look-ahead.
- **Translation drifts:** about 30% of the distance travelled. The viewer keeps the root fixed unless you pass `--tran`.
- **The model compresses large movements:** knee raises above about 80° come out smaller. Use measured sensor angles for range of motion.

## Experiments

Offline model experiments (device ablation, MobilePoser vs IMUCoCo) live in
[`experiments/`](experiments/README.md). The project-level record of every run is
[`../EXPERIMENT_LOG.md`](../EXPERIMENT_LOG.md).
