# Mac pipeline

Python code that receives, loads, calibrates and analyses MotionStreamer recordings, and runs
[MobilePoser](https://github.com/SPICExLAB/MobilePoser) to turn them into a full SMPL body.

```
iPhone app ──UDP──▶ live/receiver.py ──▶ data/recordings/<session>/mac_stream.jsonl
             └────▶ live/live_viewer.py ──▶ live mesh window
data/recordings ──▶ preprocessing/ (load · resample · calibrate) ──▶ pose/ (MobilePoser) ──▶ analysis/
```

| Folder | File | Role |
|---|---|---|
| `preprocessing/` | `motion_io.py` | Load a recording into one stream per device; map devices to MobilePoser slots |
| | `resample.py` | Resample each device to 30 Hz; mark frames that fall in sensor gaps |
| | `calibration.py` | Standing calibration: device → body frame (x left, y up, z forward) |
| `pose/` | `replay.py` | Recording → MobilePoser offline, with checks; saves outputs, plots, videos |
| | `render_session.py` | Mesh video of a whole session (started by the receiver after each session) |
| `live/` | `receiver.py` | Log every UDP packet, check stream coverage, write `summary.json` |
| | `live_viewer.py` | Real-time viewer: receives UDP, calibrates on Calibrate, runs the model at 30 Hz |
| | `send_recording.py` | Replay a saved recording over UDP (test without devices) |
| | `fake_phone.py` | Send synthetic packets (test the receiver without devices) |
| `ingest/` | `ingest_field.py` | Check a field session (checksums, gaps + causes, clock fit, high-rate) and merge it into `stream.jsonl` |
| | `merge_watch.py` | Merge a Watch session recorded under its own ID (`…-W`) into its phone session (new `<phone>+<watch>` folder) |
| | `quality.py`, `high_rate.py` | Shared quality rules (same as the app) and the binary high-rate loader |
| `analysis/` | `plot_trajectories.py` | Head and thigh angles, heights and acceleration over time |
| | `knee_pca.py` | PCA of the 3D knee path during knee raises, per-repetition metrics |

`paths.py` holds the project locations shared with `experiments/`. Each recording folder holds `mac_stream.jsonl` (every packet), `summary.json` (coverage) and
`phase2/` (replay outputs).

## Commands

Run from the repo root with the ML environment (`.venv`, Python 3.9):

```bash
PY=.venv/bin/python
```

| Task | Command |
|---|---|
| Live demo (enter the printed IP in the app, then Start → Calibrate) | `$PY -m pipeline.live.live_viewer --screen leg` |
| Record without the viewer | `$PY -m pipeline.live.receiver` |
| Test without devices (viewer running) | `$PY -m pipeline.live.send_recording data/recordings/20261001-162235-P01` |
| Mesh video from a recording (`phase2/replay_lp_h.mp4`) | `$PY -m pipeline.pose.replay data/recordings/<session> --head --single --screen leg --render --no-tran` |
| Trajectory plots | `$PY -m pipeline.analysis.plot_trajectories data/recordings/<session> --screen leg` |
| Check and merge a field session copied from the phone | `$PY -m pipeline.ingest.ingest_field data/recordings/field/<session>` (`--phone-only` without a Watch) |
| Watch recorded under its own ID (`…-W`): merge, then ingest the new folder | `$PY -m pipeline.ingest.merge_watch data/recordings/field/<phone> data/recordings/field/<watch-W>` |
| Knee PCA | `$PY -m pipeline.analysis.knee_pca data/recordings/<session> --screen leg` |

## Things to know

- **One listener at a time:** the viewer and the receiver both use UDP port 5005.
- **Start the viewer before Start on the phone,** or tap Calibrate again: the mesh moves only after
  the viewer has seen a calibration.
- **Calibrate standing completely still** with the phone screen facing the leg (`--screen leg`).
  A failed check (rotation > 0.2 rad/s) means you moved during the hold.
- **Latency:** about 0.2 s, mostly MobilePoser's 5-frame look-ahead.
- **Translation drifts** about 30 % of the distance travelled; the viewer keeps the root fixed
  unless you pass `--tran`.
- **The model compresses large movements:** knee raises above about 80° come out smaller. Use
  measured sensor angles for range of motion.
