"""E06 video: Apple and commercial reconstructions side by side, with an OpenCap slot to fill
later, and rolling charts of each sensor's rotation speed under them.

Run after run.py:
    .venv/bin/python -m experiments.E06_side_by_side.make_video LABEL [--seconds N] [--opencap MP4]

Top: one SMPL mesh per system (root fixed, so posture is compared, not travel), the third panel
waits for OpenCap. Bottom: the last 10 s of rotation speed, the right edge is now: wrist (Watch vs
the commercial wrist sensor), pocket/waist (iPhone vs the waist sensor, AirPods), other commercial
sensors. Ticks: swings found by the commercial logger (orange) and Calibrate holds (blue).
Writes results/<LABEL>/videos/side_by_side.mp4 (videos are not committed).
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import cv2
import numpy as np

from pipeline.paths import MOBILEPOSER_DIR

PANEL, FPS, WINDOW_S = 480, 30, 10.0
HEADER, CHART_H, FOOT = 92, 130, 84
WHITE, INK, GREY, LIGHT = (255, 255, 255), (40, 40, 40), (150, 150, 150), (232, 232, 232)
BLUE, ORANGE, GREEN, RED, PURPLE, BROWN, TEAL = (
    (200, 110, 30), (30, 140, 255), (60, 160, 60), (60, 60, 210), (170, 80, 150), (40, 90, 140), (150, 150, 30)
)  # fmt: skip
CHARTS = [
    ("Wrist (same arm)", [("apple:watch", "Apple Watch", BLUE, False), ("commercial:msense_D0E5", "msense D0E5 wrist", ORANGE, True)]),
    ("Pocket / waist / head", [("apple:phone", "iPhone pocket", GREEN, False), ("commercial:msense_2F5A", "msense 2F5A waist", RED, True),
                               ("apple:airpods", "AirPods head", PURPLE, False)]),
    ("Other commercial sensors", [("commercial:msense_01F7", "01F7 racket? (swing detector)", BROWN, True),
                                  ("commercial:msense_6955", "6955 racket?", BROWN, True),
                                  ("commercial:msense_1D03", "1D03 upper arm?", TEAL, True)]),
]  # fmt: skip


def text(img, s, xy, scale=0.5, color=INK, thick=1):
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def dashed(img, pts, color):
    for i in range(0, len(pts) - 1, 2):
        cv2.line(img, tuple(pts[i]), tuple(pts[i + 1]), color, 2, cv2.LINE_AA)


def chart(img, y0, w, title, lines, series, t, now, swings, cals, ymax):
    x0, x1 = 200, w - 16
    h = CHART_H - 26
    cv2.rectangle(img, (x0, y0), (x1, y0 + h), LIGHT, -1)
    for v in (0, ymax / 2, ymax):
        y = int(y0 + h - v / ymax * h)
        cv2.line(img, (x0, y), (x1, y), WHITE, 1)
        text(img, f"{v:.0f}", (x0 - 42, y + 4), 0.38, GREY)
    text(img, title, (8, y0 + 14), 0.45, INK, 1)
    text(img, "deg/s", (8, y0 + 32), 0.38, GREY)

    def x_of(tt):
        return (x0 + (tt - (now - WINDOW_S)) / WINDOW_S * (x1 - x0)).astype(int)

    for s in swings:
        if now - WINDOW_S <= s <= now:
            x = int(x_of(np.array([s]))[0])
            cv2.line(img, (x, y0), (x, y0 + 14), ORANGE, 3)
    for c in cals:
        if now - WINDOW_S <= c <= now:
            x = int(x_of(np.array([c]))[0])
            cv2.line(img, (x, y0), (x, y0 + h), BLUE, 1)
    i0, i1 = np.searchsorted(t, now - WINDOW_S), np.searchsorted(t, now, side="right")
    legend_x = x0 + 6
    for key, label, color, is_dashed in lines:
        if key not in series:
            continue
        v = series[key][i0:i1]
        ok = ~np.isnan(v)
        if ok.sum() > 1:
            pts = np.stack(
                [x_of(t[i0:i1][ok]), (y0 + h - np.clip(v[ok], 0, ymax) / ymax * h).astype(int)], 1
            )
            (
                dashed
                if is_dashed
                else lambda im, p, c: cv2.polylines(im, [p], False, c, 2, cv2.LINE_AA)
            )(img, pts, color)
            cur = f"{v[ok][-1]:.0f}"
        else:
            cur = "no data"
        cv2.line(img, (legend_x, y0 + h + 14), (legend_x + 18, y0 + h + 14), color, 2)
        text(img, f"{label}: {cur}", (legend_x + 22, y0 + h + 18), 0.38, INK)
        legend_x += 290


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("label")
    p.add_argument("--seconds", type=float, help="only the first N seconds (a quick check)")
    p.add_argument(
        "--opencap", type=Path, help="OpenCap render to fill the third panel, already in time"
    )
    args = p.parse_args()
    res = Path(__file__).resolve().parent / "results" / args.label
    out_dir = res / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((res / "meta.json").read_text())
    outs = np.load(res / "outputs.npz")
    series = dict(np.load(res / "series.npz"))
    t = outs["t"]
    n = len(t) if not args.seconds else min(len(t), int(args.seconds * FPS))
    os.chdir(MOBILEPOSER_DIR)
    from experiments.common import mobileposer_runner as mp
    from experiments.common.render import frame_count, render_mesh

    body = mp.body_model()
    mesh = {}
    for name in ("apple", "commercial"):
        path = out_dir / f"{name}{'_test' if args.seconds else ''}.mp4"
        if not path.exists() or frame_count(path) != n:
            render_mesh(body, outs[f"{name}_pose"][:n], path, size=PANEL)
        mesh[name] = cv2.VideoCapture(str(path))
    ocap = cv2.VideoCapture(str(args.opencap)) if args.opencap else None

    w = PANEL * 3
    hgt = HEADER + PANEL + 3 * CHART_H + FOOT
    final = out_dir / f"side_by_side{'_test' if args.seconds else ''}.mp4"
    writer = cv2.VideoWriter(str(final), cv2.VideoWriter_fourcc(*"avc1"), FPS, (w, hgt))
    swings = [s["t"] for s in meta["swings"]]
    cals = meta["calibrations_s"]
    ymax = {0: 800, 1: 700, 2: 1400}
    who = args.label.split("-")[0].capitalize()
    for i in range(n):
        img = np.full((hgt, w, 3), 250, np.uint8)
        now = t[i]
        clock = dt.datetime.fromtimestamp(meta["start_unix"] + now).strftime("%H:%M:%S.%f")[:-5]
        seg = next(
            (k for k, s in enumerate(meta["segments"]) if s["from_s"] <= now <= s["to_s"] + 0.1), 0
        )
        text(img, f"E06  {who}  2026-10-28  {clock}   ({now:.1f} s after Start, segment {seg + 1}/{len(meta['segments'])},"
                  f" calibrated at {meta['segments'][seg]['hold_s']:.0f} s)", (10, 26), 0.6, INK, 2)  # fmt: skip
        text(img, f"Same Calibrate holds and body heading for both. Clock: commercial logger {meta['clock_lag_s']:+.2f} s"
                  f" vs ours (wrist match r {meta['clock_match_r']:.2f}). MobilePoser, root fixed.", (10, 52), 0.45, GREY)  # fmt: skip
        labels = [
            (
                "Apple: iPhone + Watch" + (" + AirPods" if "head" in meta["apple_inputs"] else ""),
                meta["combos"]["apple"],
            ),
            (
                "Commercial: wrist D0E5 + waist 2F5A",
                meta["combos"]["commercial"] + "  (waist in pocket slot)",
            ),
            ("OpenCap (2 phone videos)", "ground truth: to be added"),
        ]
        for k, (name, sub) in enumerate(labels):
            x = k * PANEL
            if k < 2:
                ok, f = mesh[("apple", "commercial")[k]].read()
                panel = (
                    cv2.resize(f, (PANEL, PANEL))
                    if ok
                    else np.full((PANEL, PANEL, 3), 255, np.uint8)
                )
            elif ocap is not None:
                ok, f = ocap.read()
                panel = (
                    cv2.resize(f, (PANEL, PANEL))
                    if ok
                    else np.full((PANEL, PANEL, 3), 255, np.uint8)
                )
            else:
                panel = np.full((PANEL, PANEL, 3), 236, np.uint8)
                text(panel, "OpenCap: not processed yet", (90, PANEL // 2), 0.7, GREY, 2)
                text(
                    panel,
                    "phone1 + phone2 videos -> OpenCap -> here",
                    (55, PANEL // 2 + 30),
                    0.5,
                    GREY,
                )
            img[HEADER : HEADER + PANEL, x : x + PANEL] = panel
            text(img, name, (x + 10, HEADER + 22), 0.55, INK, 2)
            text(img, sub, (x + 10, HEADER + 44), 0.42, GREY)
            if k:
                cv2.line(img, (x, HEADER), (x, HEADER + PANEL), LIGHT, 2)
        for c, (title, lines) in enumerate(CHARTS):
            chart(
                img,
                HEADER + PANEL + 10 + c * CHART_H,
                w,
                title,
                lines,
                series,
                t,
                now,
                swings,
                cals,
                ymax[c],
            )
        fy = HEADER + PANEL + 3 * CHART_H + 18
        text(
            img,
            "Orange ticks: swings found by the commercial logger. Blue lines: Calibrate holds. Dashed: commercial sensors.",
            (10, fy),
            0.42,
            GREY,
        )
        text(
            img,
            "Placements: wrist sensor worn with the Watch (reported); waist 2F5A, racket 01F7/6955, arm 1D03 inferred from motion.",
            (10, fy + 20),
            0.42,
            GREY,
        )
        text(
            img,
            "Commercial orientation: Madgwick (gyro + gravity), heading from its magnetometer after each hold; gyro bias from the hold.",
            (10, fy + 40),
            0.42,
            GREY,
        )
        stuck = ", ".join(
            f"{k.replace('msense_', '')} {v * 100:.1f} %"
            for k, v in meta.get("frozen_gyro_share", {}).items()
        )
        text(
            img,
            f"Commercial gyro stuck on one value >= 0.1 s (left blank): {stuck}.",
            (10, fy + 60),
            0.42,
            GREY,
        )
        writer.write(img)
    writer.release()
    for c in mesh.values():
        c.release()
    if frame_count(final) != n:
        raise RuntimeError(f"{final}: wrote {frame_count(final)} of {n} frames")
    print(f"Saved {final}")


if __name__ == "__main__":
    main()
