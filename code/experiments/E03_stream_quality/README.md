# E03: data consistency of each sensor stream

**Question.** How consistent is the data each device delivers (sampling rate, missing samples,
gaps, delivery delay), and where do problems in the streams line up with the motion and with the
reconstructed trajectories?

Here "data consistency" means stream quality. For agreement between a model's bones and the
sensors, see E02 (`plot_agreement.py`).

**Method.**
- Raw packets from `recordings/<session>/mac_stream.jsonl`, parsed by `common/stream_quality.py`:
  - Each packet carries `first_index`, so every sample has an index. Samples missing from the
    index sequence were numbered by the device but never arrived.
  - A time gap (interval > 100 ms) with no missing index means the device itself paused, or
    its samples were late, before numbering. AirPods samples are numbered by the iPhone app as
    they arrive.
  - All times are on the phone clock (Watch samples mapped through each device's
    `boot_to_unix`), in seconds after Start.
  - Delay = Mac receive time minus the packet's last sample time. It includes clock offsets and,
    for the Watch, the relay through the iPhone.
- Motion trajectories:
  - Sensor side: each device's rotation away from its calibration pose.
  - Model side: MobilePoser on all devices (run here), plus IMUCoCo from E02's saved outputs when present.
- Statistics cover two spans: the whole session, and calibration end → Stop (the span the models see).

**Run.** From `project/code`: `.venv/bin/python experiments/E03_stream_quality/run.py [SESSION]` (about 10 s).

**Outputs** in `results/<session>/`:
- `stream_quality.png`: one image. Left: rate, missingness raster, delay, sensor and model
  trajectories over time. Right: interval histograms and the summary table.
- `metrics.json`
- `summary.md`

## Results: 20261008-153213-P01 (2026-10-14)

Calibration end → Stop:

| | iPhone (pocket) | Watch (wrist) | AirPods (head) |
|---|---|---|---|
| requested rate | 60 Hz | 60 Hz | 25 Hz |
| delivered rate | 33.5 Hz | 66.4 Hz | 50 Hz |
| coverage | 99.3 % | 99.7 % | 95.7 % |
| missing by index | 10 | 5 | 5 |
| gaps > 100 ms | 1 | 0 | 14 |
| longest gap | 329 ms | 90 ms | 219 ms |
| delay to Mac, median | 173 ms | 341 ms | 135 ms |

**Findings.**
1. **No device delivers the rate the app asks for.** The iPhone gives 33.5 Hz instead of 60
   (the same on 2026-10-01, so it is this phone/app). The Watch gives 66.4 Hz instead of 60. The
   AirPods give 50 Hz instead of 25. All are above the models' 30 Hz input rate, so the models
   are not starved, but the app's requested rates are not a reliable description of the data.
2. **The AirPods are the least consistent stream.** They have 14 gaps over 100 ms after
   calibration (30 over the whole session) but only 5 samples missing by index. So the AirPods
   pause or deliver late before the iPhone numbers their samples; Wi-Fi loss is not the cause.
   Their rate also drops to 30-45 Hz before calibration and during tennis swings.
3. **The iPhone's one real gap (329 ms at ~39 s, during the swings) loses 10 samples.** It is
   the only interval where the models' inputs are interpolated over a gap > 0.25 s (red dots in
   the sensor trajectory panel).
4. **The Watch stream is the most regular** (99.7 %, no gap > 100 ms). It has the longest
   delay (341 ms median) from the relay through the iPhone, and a backlog of up to 2 s in the
   first ~15 s after Start, before calibration.
5. **Open question about posture, not stream quality.** After the jumping jacks the Watch never
   returns near its calibration orientation. Its tilt from vertical is 88° before the swings and
   75-81° during the head turns, while the phone and AirPods return within 7-25°. Tilt is
   gravity-referenced and cannot drift, so either the forearm really was bent (hands in front or on
   the hips) or the Watch shifted on the wrist. To be confirmed with the participant or video.
