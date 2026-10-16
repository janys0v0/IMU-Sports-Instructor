"""E03: data consistency of each sensor stream (sampling rate, missingness, delay) next to the
motion trajectories it produces, in one figure.

Run from project/code:
    .venv/bin/python -m experiments.E03_stream_quality.run [SESSION]

Writes results/<SESSION>/: stream_quality.png, metrics.json, summary.md.
Model trajectories: MobilePoser is run here on all devices (a few seconds); IMUCoCo is overlaid
from E02's saved outputs when they exist.
"""

import argparse
import json

import numpy as np

from experiments.common import metrics, paths, stream_quality
from experiments.common import mobileposer_runner as mp
from experiments.common.session import load_session

REFERENCE_SESSION = "20261008-153213-P01"
DEVICE_COLOR = {"phone": "#1f77b4", "watch": "#2ca02c", "airpods": "#9467bd"}
DEVICE_NAME = {"phone": "iPhone (pocket)", "watch": "Watch (wrist)", "airpods": "AirPods (head)"}
ACT_COLORS = {
    "standing_still": "#7f7f7f",
    "jumping_jacks": "#2ca02c",
    "tennis_swings": "#9467bd",
    "squats": "#ff7f0e",
    "head_turns": "#8c564b",
}


def shade(ax, annotation, events, label=False):
    cal = dict(events).get("calibrate")
    if cal is not None:
        ax.axvspan(cal + 0.3, cal + 3.0, color="gold", alpha=0.25, lw=0)
        if label:
            ax.text(
                cal + 1.6,
                0.04,
                "calibrate",
                transform=ax.get_xaxis_transform(),
                ha="center",
                fontsize=7,
                color="#a07800",
                rotation=90,
                va="bottom",
            )
    for a in (annotation or {}).get("activities", []):
        ax.axvspan(a["start"], a["end"], color=ACT_COLORS.get(a["name"], "gray"), alpha=0.08, lw=0)
        if label:
            ax.text(
                (a["start"] + a["end"]) / 2,
                1.02,
                a["name"].replace("_", " "),
                transform=ax.get_xaxis_transform(),
                ha="center",
                fontsize=8,
                color=ACT_COLORS.get(a["name"], "gray"),
            )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default=REFERENCE_SESSION)
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    rec = stream_quality.load(args.session)
    annotation = metrics.load_annotation(rec.name)
    out = paths.results_dir(__file__, rec.name)
    order = sorted(
        rec.streams, key=lambda l: ["phone", "watch", "airpods"].index(rec.streams[l].device)
    )
    stop = dict(rec.events).get("stop", max(s.t[-1] for s in rec.streams.values()))

    # Stream statistics: whole session and the analysed part (calibration end to Stop)
    session = load_session(rec.name)
    t_cal_end = session.segments[0].t[0]
    stats = {
        loc: {
            "device": rec.streams[loc].device,
            "whole_session": rec.streams[loc].summary(0, stop),
            "after_calibration": rec.streams[loc].summary(t_cal_end, stop),
        }
        for loc in order
    }

    # Motion trajectories
    m_out = mp.run(session, session.locs)
    ref = metrics.reference(session, len(m_out.t))
    sig = metrics.signals(m_out, ref)
    coco_file = (
        paths.EXPERIMENTS
        / "E02_imucoco_comparison"
        / "results"
        / rec.name
        / "outputs"
        / f"IMUCoCo_{mp.combo_name(session.locs)}.npz"
    )
    coco = np.load(coco_file) if coco_file.exists() else None

    fig = plt.figure(figsize=(18, 14))
    gs = GridSpec(
        6,
        2,
        figure=fig,
        width_ratios=[2.3, 1],
        height_ratios=[1, 0.6, 0.8, 1, 1, 1],
        hspace=0.55,
        wspace=0.15,
    )
    fig.suptitle(
        f"{rec.name}: data consistency of each sensor stream and the motion trajectories it produces",
        fontsize=13,
        y=0.93,
    )

    # 1. Sampling rate over time
    ax0 = ax = fig.add_subplot(gs[0, 0])
    for loc in order:
        s = rec.streams[loc]
        c = DEVICE_COLOR[s.device]
        x, hz = s.rolling_hz()
        ax.plot(x, hz, color=c, lw=1.2, label=f"{DEVICE_NAME[s.device]}: delivered")
        ax.axhline(s.requested_hz, color=c, lw=0.9, ls="--", alpha=0.7)
    ax.set_ylabel("samples / s\n(1 s window)")
    ax.set_title("Data consistency", fontsize=11, loc="left", pad=18)
    ax.text(
        0.995,
        0.03,
        "dashed = rate requested by the app",
        transform=ax.transAxes,
        ha="right",
        fontsize=7,
        color="gray",
    )
    ax.legend(fontsize=7, ncol=3, loc="upper left")
    shade(ax, annotation, rec.events, label=True)

    # 2. Missingness raster
    ax = fig.add_subplot(gs[1, 0], sharex=ax0)
    for row, loc in enumerate(order):
        s = rec.streams[loc]
        c = DEVICE_COLOR[s.device]
        ax.broken_barh([(s.t[0], s.t[-1] - s.t[0])], (row - 0.3, 0.6), color=c, alpha=0.25)
        ax.broken_barh([(a, b - a) for a, b in s.gaps()], (row - 0.38, 0.76), color="red")
        ax.plot(s.missing_t, np.full(len(s.missing_t), row), "kx", ms=5, mew=1)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([DEVICE_NAME[rec.streams[l].device] for l in order], fontsize=8)
    ax.set_ylim(-0.6, len(order) - 0.4)
    ax.text(
        0.995,
        1.04,
        "bar = stream present   red = gap > 100 ms   x = sample missing from index",
        transform=ax.transAxes,
        ha="right",
        fontsize=7,
        color="gray",
    )
    shade(ax, annotation, rec.events)

    # 3. Delivery delay to the Mac
    ax = fig.add_subplot(gs[2, 0], sharex=ax0)
    for loc in order:
        s = rec.streams[loc]
        ax.plot(s.packet_t, s.delay_ms, ".", ms=2, color=DEVICE_COLOR[s.device], alpha=0.6)
        ax.axhline(np.median(s.delay_ms), color=DEVICE_COLOR[s.device], lw=1)
    ax.set_ylabel("delay to Mac\n(ms)")
    ax.set_ylim(
        0, np.percentile(np.concatenate([s.delay_ms for s in rec.streams.values()]), 99.5) * 1.1
    )
    shade(ax, annotation, rec.events)

    # 4. Sensor motion: rotation away from the calibration pose, gaps marked
    ax = fig.add_subplot(gs[3, 0], sharex=ax0)
    t = sig["t"]
    for loc in order:
        dev = session.segments[0].devices[loc]
        n = len(t)
        rot = metrics.angle_deg(dev.ori[:n], np.eye(3))
        c = DEVICE_COLOR[rec.streams[loc].device]
        ax.plot(t, rot, color=c, lw=1.1, label=DEVICE_NAME[rec.streams[loc].device])
        bad = ~dev.valid[:n]
        if bad.any():
            ax.plot(t[bad], rot[bad], "o", ms=3, color="red")
    ax.set_ylabel("sensor rotation from\ncalibration pose (deg)")
    ax.set_title("Motion trajectories", fontsize=11, loc="left", pad=6)
    ax.legend(fontsize=7, ncol=3, loc="upper left")
    shade(ax, annotation, rec.events)

    # 5-6. Model trajectories
    ax = fig.add_subplot(gs[4, 0], sharex=ax0)
    ax.plot(t, sig["wrist_height_right"], color="#1f77b4", lw=1.2, label="MobilePoser right wrist")
    ax.plot(
        t,
        sig["wrist_height_left"],
        color="#1f77b4",
        lw=1,
        ls="--",
        label="MobilePoser left wrist (no sensor)",
    )
    if coco is not None:
        j = coco["joints"]
        ax.plot(
            coco["t"],
            j[:, 21, 1] - j[:, 0, 1],
            color="#d62728",
            lw=1.2,
            label="IMUCoCo right wrist",
        )
    ax.axhline(-0.05, color="black", lw=0.8, ls=":")
    ax.set_ylabel("model wrist height\nabove pelvis (m)")
    ax.legend(fontsize=7, ncol=3, loc="upper right")
    shade(ax, annotation, rec.events)

    ax = fig.add_subplot(gs[5, 0], sharex=ax0)
    ax.plot(
        t,
        (sig["knee_flexion_right"] + sig["knee_flexion_left"]) / 2,
        color="#1f77b4",
        lw=1.2,
        label="MobilePoser",
    )
    if coco is not None:
        j = coco["joints"]
        ax.plot(
            coco["t"],
            (metrics.knee_flexion_deg(j, "right") + metrics.knee_flexion_deg(j, "left")) / 2,
            color="#d62728",
            lw=1.2,
            label="IMUCoCo",
        )
    ax2 = ax.twinx()
    if "head_yaw_airpods" in sig:
        ax2.plot(
            t, sig["head_yaw_airpods"], color="#9467bd", lw=1, alpha=0.7, label="head yaw, AirPods"
        )
    ax2.set_ylabel("head yaw (deg)", color="#9467bd", fontsize=8)
    ax.set_ylabel("model knee\nflexion (deg)")
    ax.set_xlabel("s after Start (phone clock; Watch samples mapped through boot_to_unix)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7, ncol=3, loc="upper left")
    shade(ax, annotation, rec.events)
    ax.set_xlim(0, stop)

    # Right column: interval distributions and the summary table
    ax = fig.add_subplot(gs[0:2, 1])
    for loc in order:
        s = rec.streams[loc]
        ax.hist(
            np.clip(s.dt_ms, 0, 300),
            bins=np.arange(0, 301, 2.5),
            histtype="step",
            lw=1.3,
            color=DEVICE_COLOR[s.device],
            label=f"{DEVICE_NAME[s.device]} ({1000 / s.requested_hz:.0f} ms requested)",
        )
    ax.axvline(100, color="red", lw=0.8, ls=":")
    ax.set_yscale("log")
    ax.set_xlabel("interval between consecutive samples (ms, clipped at 300)")
    ax.set_ylabel("count")
    ax.set_title("Sampling intervals", fontsize=10, loc="left")
    ax.legend(fontsize=7)

    ax = fig.add_subplot(gs[2:5, 1])
    ax.axis("off")
    rows = [
        ("requested rate (Hz)", "requested_hz"),
        ("delivered rate (Hz)", "delivered_hz"),
        ("interval p5-p95 (ms)", "interval_ms_p5_p95"),
        ("samples", "samples"),
        ("coverage", "coverage"),
        ("missing (by index)", "missing_from_index"),
        ("gaps > 100 ms", "gaps_over_100ms"),
        ("longest gap (ms)", "longest_gap_ms"),
        ("delay to Mac, median (ms)", "delivery_delay_ms_median"),
    ]
    cell = []
    for label, key in rows:
        r = [label]
        for loc in order:
            v = stats[loc]["after_calibration"][key]
            r.append(
                f"{v[0]:g}-{v[1]:g}"
                if isinstance(v, list)
                else (f"{v:.1%}" if key == "coverage" else f"{v:g}")
            )
        cell.append(r)
    table = ax.table(
        cellText=cell,
        colLabels=["calibration end → Stop"]
        + [DEVICE_NAME[rec.streams[l].device].replace(" (", "\n(") for l in order],
        loc="upper center",
        cellLoc="center",
        colWidths=[0.4, 0.2, 0.2, 0.2],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.6)
    for k in range(len(order) + 1):
        table[0, k].set_height(table[0, k].get_height() * 1.7)
    for k, loc in enumerate(order, 1):
        table[0, k].set_text_props(color=DEVICE_COLOR[rec.streams[loc].device], weight="bold")

    ax = fig.add_subplot(gs[5, 1])
    ax.axis("off")
    ax.text(
        0,
        1,
        "How to read this\n"
        "• Coverage = samples received / samples expected at the delivered rate.\n"
        "• 'Missing (by index)' counts samples the device numbered but never arrived;\n"
        "  a gap with no missing index means the device itself paused or was late.\n"
        "• Delay = Mac receive time minus sample time; includes clock offsets and,\n"
        "  for the Watch, the relay through the iPhone.\n"
        "• Red dots on the sensor trajectories: frames inside a gap > 0.25 s, where\n"
        "  the model input is interpolated.",
        fontsize=8,
        va="top",
        family="monospace",
    )

    fig.savefig(out / "stream_quality.png", dpi=110, bbox_inches="tight")
    (out / "metrics.json").write_text(
        json.dumps(
            {"session": rec.name, "events_s_after_start": rec.events, "streams": stats}, indent=2
        )
    )
    lines = [
        f"# E03 results: {rec.name}",
        "",
        "Stream quality from calibration end to Stop (whole session in metrics.json).",
        "",
        "| | " + " | ".join(DEVICE_NAME[rec.streams[l].device] for l in order) + " |",
        "|---|" + "---|" * len(order),
    ] + ["| " + " | ".join(r) + " |" for r in cell]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("Saved", out)


if __name__ == "__main__":
    main()
