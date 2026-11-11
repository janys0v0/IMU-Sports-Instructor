"""E06 video: Apple and commercial reconstructions side by side with OpenCap on the camera video,
and rolling charts of each sensor's rotation speed under them.

Run after run.py:
    .venv/bin/python -m experiments.E06_side_by_side.make_video LABEL [--seconds N]
        [--opencap-dir data/external/20261028/aligned_hrnet3/<trial> --phone1 <clip>]

Top: one SMPL mesh per system (root fixed, so posture is compared, not travel), then a camera with
OpenCap's reconstruction superposed: phone1 with OpenCap's markers projected by the camera fitted
in camera.py (--phone1), or the team's overlay video (--overlay). Bottom: the last 10 s
of rotation speed, the right edge is now: wrist (Watch vs the commercial wrist sensor), pocket/waist
(iPhone vs the waist sensor, AirPods), other commercial sensors; OpenCap's own segment rotation
speeds are drawn in black as the reference. Ticks: swings found by the commercial logger (orange)
and Calibrate holds (blue).

OpenCap's time is seconds into the phone2 clip; it is put on our clock by cross-correlating its right
forearm rotation speed with the Watch (see opencap_series).
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
WIDTHS = (400, 400, 640)  # mesh, mesh, camera (16:9 fits 640 x 360)
TITLE_H = 54  # light strip at the top of each panel for its title
HEADER, CHART_H, FOOT = 92, 130, 84
WHITE, INK, GREY, LIGHT = (255, 255, 255), (40, 40, 40), (150, 150, 150), (232, 232, 232)
BLUE, ORANGE, GREEN, RED, PURPLE, BROWN, TEAL, BLACK = (
    (200, 110, 30), (30, 140, 255), (60, 160, 60), (60, 60, 210), (170, 80, 150), (40, 90, 140), (150, 150, 30),
    (30, 30, 30),
)  # fmt: skip
CHARTS = [
    ("Wrist (same arm)", [("opencap:radius_r", "OpenCap forearm", BLACK, False), ("apple:watch", "Apple Watch", BLUE, False),
                          ("commercial:msense_D0E5", "msense D0E5 wrist", ORANGE, True)]),
    ("Thigh / trunk / head", [("opencap:femur_r", "OpenCap R thigh", BLACK, False), ("apple:phone", "iPhone pocket", GREEN, False),
                              ("commercial:msense_2F5A", "2F5A trunk", RED, True), ("opencap:torso", "OpenCap trunk", GREY, False),
                              ("apple:airpods", "AirPods head", PURPLE, False)]),
    ("Upper arm / racket", [("opencap:humerus_r", "OpenCap upper arm", BLACK, False), ("commercial:msense_1D03", "1D03 upper arm", TEAL, True),
                            ("commercial:msense_6955", "6955 racket butt", BROWN, True), ("commercial:msense_01F7", "01F7 racket butt", BROWN, True)]),
]  # fmt: skip
OPENCAP_BODIES = ("radius_r", "femur_r", "torso", "humerus_r", "pelvis")


def opencap_series(opencap_dir, watch_unix_t, watch_w, t_unix):
    """OpenCap segment rotation speeds (deg/s) on `t_unix`, and the clip-time -> unix offset found
    by cross-correlating its right forearm with the Watch over the whole session (FFT, 30 Hz)."""
    z = np.load(Path(opencap_dir) / "opencap_gt.npz")
    names = list(z["body_names"])
    tv = z["t"]
    fs = 30.0
    ga = np.arange(watch_unix_t[0], watch_unix_t[-1], 1 / fs)
    a = np.interp(ga, watch_unix_t, np.linalg.norm(watch_w, axis=1))
    gv = np.arange(tv[0], tv[-1], 1 / fs)
    b = np.interp(gv, tv, np.linalg.norm(z["W"][:, names.index("radius_r")], axis=1))
    gap = np.diff(tv)[np.clip(np.searchsorted(tv, gv) - 1, 0, len(tv) - 2)] > 0.2
    a, b = (a - a.mean()) / a.std(), (b - b.mean()) / b.std()
    b[gap] = 0
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    k = int(np.argmax(c))
    k = k if k < n // 2 else k - n
    unix0 = ga[0] + k / fs - gv[0]
    tq = t_unix - unix0
    idx = np.clip(np.searchsorted(tv, tq), 1, len(tv) - 1)
    bad = (tq < tv[0]) | (tq > tv[-1]) | (tv[idx] - tv[idx - 1] > 0.2)
    out = {}
    for body in OPENCAP_BODIES:
        v = np.degrees(np.interp(tq, tv, np.linalg.norm(z["W"][:, names.index(body)], axis=1)))
        v[bad] = np.nan
        out[f"opencap:{body}"] = v
    return out, unix0, (tv[0] + unix0, tv[-1] + unix0)


def text(img, s, xy, scale=0.5, color=INK, thick=1):
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def dashed(img, pts, color):
    for i in range(0, len(pts) - 1, 2):
        cv2.line(img, tuple(pts[i]), tuple(pts[i + 1]), color, 2, cv2.LINE_AA)


BONES = [("Neck", "RShoulder"), ("RShoulder", "RElbow"), ("RElbow", "RWrist"), ("Neck", "LShoulder"),
         ("LShoulder", "LElbow"), ("LElbow", "LWrist"), ("Neck", "midHip"), ("midHip", "RHip"),
         ("RHip", "RKnee"), ("RKnee", "RAnkle"), ("RAnkle", "RHeel"), ("RHeel", "RBigToe"),
         ("midHip", "LHip"), ("LHip", "LKnee"), ("LKnee", "LAnkle"), ("LAnkle", "LHeel"), ("LHeel", "LBigToe")]  # fmt: skip


def opencap_markers(opencap_dir):
    z = np.load(Path(opencap_dir) / "opencap_gt.npz")
    return z["t"], z["mk"], list(z["mk_names"])


def skeleton_inset(mk, names, size=210):
    """OpenCap's 3D markers as a stick figure turned to face the viewer, like the meshes (y up; the
    body heading from the hips). Right side red, as the Watch arm elsewhere."""
    out = np.full((size, size, 3), 248, np.uint8)
    cv2.rectangle(out, (0, 0), (size - 1, size - 1), LIGHT, 1)
    if mk is None or not np.isfinite(mk).all():
        text(out, "OpenCap: no frame", (20, size // 2), 0.45, GREY)
        return out
    i = {n: k for k, n in enumerate(names)}
    p = mk - mk[i["midHip"]]
    right = p[i["RHip"]] - p[i["LHip"]]
    right[1] = 0
    right /= np.linalg.norm(right) + 1e-9
    fwd = np.cross(right, [0.0, 1.0, 0.0])  # body forward, horizontal
    xs, ys = p @ -right, p[:, 1]  # facing the viewer: body right appears on the left
    sc = size * 0.42
    pts = {n: (int(size / 2 + xs[k] * sc), int(size * 0.55 - ys[k] * sc)) for n, k in i.items()}
    for a, b in BONES:
        color = RED if a.startswith("R") or b.startswith("R") else (90, 90, 90)
        if a == "Neck" and b == "midHip":
            color = (90, 90, 90)
        cv2.line(out, pts[a], pts[b], color, 3, cv2.LINE_AA)
    head = (pts["Neck"][0], pts["Neck"][1] - int(0.12 * sc))
    cv2.circle(out, head, int(0.09 * sc), (90, 90, 90), 2, cv2.LINE_AA)
    text(out, "OpenCap 3D (facing you)", (6, size - 8), 0.38, INK)
    _ = fwd
    return out


def fit(frame, width, bg=250):
    """`frame` scaled to fit width x (PANEL - TITLE_H) below the title strip, centred."""
    h, w = frame.shape[:2]
    room = PANEL - TITLE_H
    s = min(width / w, room / h)
    small = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    out = np.full((PANEL, width, 3), bg, np.uint8)
    y = TITLE_H + (room - small.shape[0]) // 2
    x = (width - small.shape[1]) // 2
    out[y : y + small.shape[0], x : x + small.shape[1]] = small
    return out


def blank(msg, width):
    out = np.full((PANEL, width, 3), 236, np.uint8)
    text(out, msg, (40, PANEL // 2), 0.6, GREY, 2)
    return out


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
        legend_x += 245


def phone1_panel(frame, cam, follow, crop, mk_t, mk, names, tq, width, camera):
    """The phone1 frame with OpenCap's markers at OpenCap time `tq` projected on it, cropped around
    the player and scaled to the panel (below its title strip)."""
    img = frame.copy()
    j = int(np.clip(np.searchsorted(mk_t, tq), 0, len(mk_t) - 1))
    centre = None
    if abs(mk_t[j] - tq) < 0.1:
        uv = cam(mk[j])
        camera.draw_skeleton(img, uv, names, thick=max(2, frame.shape[1] // 400))
        centre = uv[names.index("midHip")]
    x0, y0 = follow.window(centre)
    view = img[y0 : y0 + crop[1], x0 : x0 + crop[0]]
    h = PANEL - TITLE_H
    panel = np.full((PANEL, width, 3), 20, np.uint8)
    panel[TITLE_H:] = cv2.resize(view, (width, h), interpolation=cv2.INTER_AREA)
    if centre is None:
        text(panel, "OpenCap: no frame here", (10, PANEL - 14), 0.45, WHITE)
    return panel


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("label")
    p.add_argument("--seconds", type=float, help="only N seconds (a quick check)")
    p.add_argument(
        "--start-s", type=float, default=0.0, help="with --seconds: start this far into the video"
    )
    p.add_argument("--opencap-dir", type=Path, help="aligned_hrnet3/<trial> with opencap_gt.npz")
    p.add_argument("--overlay", type=Path, help="the team's camera video with OpenCap superposed")
    p.add_argument("--clip", default="phone3", help="which camera the overlay is from (label only)")
    p.add_argument(
        "--overlay-t0", type=float, default=0.0,
        help="OpenCap session time of the overlay's first frame (read off its on-screen clock)",
    )  # fmt: skip
    p.add_argument(
        "--phone1", type=Path,
        help="phone1's clip (any size; e.g. a 960x540 copy): OpenCap's skeleton is projected onto it"
        " with the camera fitted by camera.py",
    )  # fmt: skip
    args = p.parse_args()
    res = Path(__file__).resolve().parent / "results" / args.label
    out_dir = res / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((res / "meta.json").read_text())
    outs = np.load(res / "outputs.npz")
    series = dict(np.load(res / "series.npz"))
    t = outs["t"]
    i0 = int(args.start_s * FPS) if args.seconds else 0
    n = len(t) - i0 if not args.seconds else min(len(t) - i0, int(args.seconds * FPS))
    os.chdir(MOBILEPOSER_DIR)
    from experiments.common import mobileposer_runner as mp
    from experiments.common.render import frame_count, render_mesh

    body = mp.body_model()
    mesh = {}
    for name in ("apple", "commercial"):
        path = out_dir / f"{name}{f'_test{i0}' if args.seconds else ''}.mp4"
        if not path.exists() or frame_count(path) != n:
            render_mesh(body, outs[f"{name}_pose"][i0 : i0 + n], path, size=PANEL)
        mesh[name] = cv2.VideoCapture(str(path))
    ocap, unix0, oc_span = None, None, None
    if args.opencap_dir:
        from pipeline.preprocessing.motion_io import load_recording

        rec = load_recording(Path(meta["session_dir"]))
        watch = next(s for s in rec.streams.values() if s.device == "watch")
        oc, unix0, oc_span = opencap_series(
            args.opencap_dir, watch.t + watch.boot_to_unix, watch.rot_rate, t + meta["start_unix"]
        )
        series.update(oc)
    mk_t = None
    if args.opencap_dir:
        mk_t, mk, mk_names = opencap_markers(args.opencap_dir)
    if args.overlay:
        ocap = cv2.VideoCapture(str(args.overlay))
        ocap_fps = ocap.get(cv2.CAP_PROP_FPS)
        ocap_n = int(ocap.get(cv2.CAP_PROP_FRAME_COUNT))
        ocap_pos, ocap_frame = -1, None

    cam = None
    if args.phone1:
        from experiments.E06_side_by_side import camera

        fitted = json.loads(camera.CAMERA_JSON.read_text())
        clip_unix = fitted["clips"][args.label]["start_unix"]
        ocap = cv2.VideoCapture(str(args.phone1))
        ocap_fps = ocap.get(cv2.CAP_PROP_FPS)
        ocap_n = int(ocap.get(cv2.CAP_PROP_FRAME_COUNT))
        ocap_pos, ocap_frame = -1, None
        size = (int(ocap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(ocap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        scale = size[0] / fitted["frame_size"][0]

        def cam(X):
            return camera.project(fitted["P"], X) * scale

        ch = int(0.8 * size[1])  # zoom in a little on the player, keeping the panel's shape
        crop = (min(size[0], int(ch * WIDTHS[2] / (PANEL - TITLE_H))), ch)
        follow = camera.Follow(size, crop)
        args.clip = "phone1"

    w = sum(WIDTHS)
    hgt = HEADER + PANEL + 3 * CHART_H + FOOT
    final = out_dir / f"side_by_side{'_test' if args.seconds else ''}.mp4"
    writer = cv2.VideoWriter(str(final), cv2.VideoWriter_fourcc(*"avc1"), FPS, (w, hgt))
    swings = [s["t"] for s in meta["swings"]]
    cals = meta["calibrations_s"]
    ymax = {0: 800, 1: 700, 2: 1400}
    who = args.label.split("-")[0].capitalize()
    for i in range(i0, i0 + n):
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
            (
                f"OpenCap on camera ({args.clip})"
                if ocap is not None
                else "OpenCap (2 phone videos)",
                f"OpenCap session t {now + meta['start_unix'] - unix0:.1f} s (aligned to the Watch)"
                if unix0
                else "ground truth: to be added",
            ),
        ]
        for k, (name, sub) in enumerate(labels):
            x, pw = sum(WIDTHS[:k]), WIDTHS[k]
            if k < 2:
                ok, f = mesh[("apple", "commercial")[k]].read()
                panel = fit(f, pw, bg=255) if ok else blank("no frame", pw)
            elif ocap is not None:
                t0 = clip_unix if cam is not None else unix0 + args.overlay_t0
                want = int(round((now + meta["start_unix"] - t0) * ocap_fps))
                if 0 <= want < ocap_n:
                    if want < ocap_pos or want - ocap_pos > 300:
                        ocap.set(cv2.CAP_PROP_POS_FRAMES, want)
                        ocap_pos = want - 1
                    while ocap_pos < want:
                        ok, f = ocap.read()
                        ocap_pos += 1
                        if ok:
                            ocap_frame = f
                    if ocap_frame is None:
                        panel = blank("no frame", pw)
                    elif cam is not None:
                        panel = phone1_panel(ocap_frame, cam, follow, crop, mk_t, mk, mk_names,
                                             now + meta["start_unix"] - unix0, pw, camera)  # fmt: skip
                    else:
                        panel = fit(ocap_frame, pw, bg=20)
                else:
                    panel = blank("outside the camera clip", pw)
            else:
                panel = np.full((PANEL, pw, 3), 236, np.uint8)
                text(panel, "OpenCap: not processed yet", (90, PANEL // 2), 0.7, GREY, 2)
                text(
                    panel,
                    "phone1 + phone2 videos -> OpenCap -> here",
                    (55, PANEL // 2 + 30),
                    0.5,
                    GREY,
                )
            if k == 2 and mk_t is not None and cam is None:
                tq = now + meta["start_unix"] - unix0
                j = int(np.clip(np.searchsorted(mk_t, tq), 0, len(mk_t) - 1))
                inset = skeleton_inset(mk[j] if abs(mk_t[j] - tq) < 0.1 else None, mk_names)
                panel[PANEL - inset.shape[0] - 8 : PANEL - 8, 8 : 8 + inset.shape[1]] = inset
            panel[:TITLE_H] = 250
            img[HEADER : HEADER + PANEL, x : x + pw] = panel
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
            "Black: OpenCap (video) segment rotation speed, the reference. Dashed: commercial sensors. Orange ticks: logger swings. Blue: Calibrate.",
            (10, fy),
            0.42,
            GREY,
        )
        text(
            img,
            "Placements (team): D0E5 wrist with the Watch, 2F5A trunk, 1D03 upper arm, 6955 + 01F7 racket butt."
            + (
                f" OpenCap {dt.datetime.fromtimestamp(oc_span[0]):%H:%M:%S}-{dt.datetime.fromtimestamp(oc_span[1]):%H:%M:%S}."
                if oc_span
                else ""
            ),
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
