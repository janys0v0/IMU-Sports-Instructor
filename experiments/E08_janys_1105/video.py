"""Janys 11/05 comparison video: the IMG_0021 camera (behind Janys) with OpenCap's skeleton
projected on it, one arm panel per method (OpenCap's arm as a grey ghost in each; methods without
their own color in E07's colors.py drawn dark grey), and rolling
curves under them: the Watch's rotation speed, elbow angle and shoulder elevation per method with
OpenCap in black. Same panels, charts and colors as E07's video; the frame is laid out for 15
methods (5 x 3).

    .venv/bin/python -m experiments.E08_janys_1105.video [--start S --seconds N] [--methods a,b,...]

`--start` counts seconds of OpenCap-covered footage (segments are joined; the header names the
segment). Writes results/janys/videos/compare_<start>.mp4 (not committed).
"""

import argparse
import datetime as dt
import json

import cv2
import numpy as np

from experiments.E06_side_by_side import camera as cam6
from experiments.E07_pose_methods import video as V
from experiments.E07_pose_methods.colors import bgr
from experiments.E07_pose_methods.data import elevation_plane

from .camera import CAMS
from .data import OUT, load
from .figures import LINEUP, method_color

PANEL = 240
NCOL, NROW = 5, 3
CAM_W = 520


ARM_OTHER = (78, 81, 82)  # dark grey for methods without their own color: the ghost is light grey


def panel(name, color, hum, fore, gh, gf, el, gel):
    """E07's arm panel; a forearm-only method's forearm hangs from OpenCap's elbow."""
    img = V.arm_panel(name, color, hum, fore, gh, gf, el, gel)
    if not np.isfinite(hum).all() and np.isfinite(fore).all() and np.isfinite(gh).all():
        scale, origin = 330, np.array([V.PANEL_W / 2, 110])
        elbow = V.SHOULDER + V.UPPER_M * gh
        uv = (V.view(np.array([elbow, elbow + V.FORE_M * fore])) * scale + origin).astype(int)
        cv2.line(img, tuple(uv[0]), tuple(uv[1]), color, 4, cv2.LINE_AA)
        cv2.circle(img, tuple(uv[1]), 6, color, -1, cv2.LINE_AA)
        V.text(img, "forearm only (hung from OpenCap's elbow)", (8, V.PANEL_H - 28), 0.42, V.GREY)
    return img


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--methods", default=",".join(LINEUP))
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--seconds", type=float)
    a = p.parse_args()
    d = load()
    names = [n for n in a.methods.split(",") if (OUT / "janys" / f"method_{n}.npz").exists()]
    ms = [np.load(OUT / "janys" / f"method_{n}.npz") for n in names]
    V.NICE.update({n: LINEUP[n][0] for n in names if n in LINEUP})
    fitted = json.loads((OUT / "camera.json").read_text())
    cap = cv2.VideoCapture(str(CAMS / "IMG_0021_540.mov"))
    cfps, cn = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    csize = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cscale = csize[0] / fitted["frame_size"][0]
    mk_names = [str(x) for x in d.get("mk_names", [])] or None
    if mk_names is None:
        z = np.load(sorted((CAMS.parent / "aligned").iterdir())[0] / "opencap_gt.npz")
        mk_names = list(z["mk_names"])
    top_h = NROW * PANEL
    crop_h = int(0.9 * csize[1])
    crop = (min(csize[0], int(crop_h * CAM_W / top_h)), crop_h)
    follow = cam6.Follow(csize, crop)

    # a continuous playback time over the joined segments
    n = len(d["t"])
    tp = np.arange(n) / V.FPS
    i0 = int(a.start * V.FPS)
    i1 = n if not a.seconds else min(n, i0 + int(a.seconds * V.FPS))
    gt_ok = d["gt_valid"]
    gel, gev = d["gt_elbow"], d["gt_elev"]
    curves = []
    for m in ms:
        hum = np.where(np.isfinite(m["hum"]), m["hum"], np.nan)
        ev = elevation_plane(hum)[0] if np.isfinite(hum).any() else np.full(n, np.nan)
        curves.append((m["elbow"], ev))
    spin = np.degrees(np.linalg.norm(d["watch_gyro"], axis=1))
    # swing ticks on the playback clock
    sw = np.array([tp[np.argmin(np.abs(d["t"] - s))] for s in d["swing_t"]])
    colored = [k for k, nm in enumerate(names) if method_color(nm) != "#b5b4ae"]

    W = CAM_W + NCOL * PANEL
    H = V.HEADER + top_h + 3 * V.CHART_H + V.FOOT
    out_dir = OUT / "janys" / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"compare_{int(a.start)}.mp4"
    wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"avc1"), V.FPS, (W, H))
    cpos, cframe = -1, None
    for i in range(i0, i1):
        img = np.full((H, W, 3), V.BG, np.uint8)
        now = tp[i]
        clock = dt.datetime.fromtimestamp(d["t"][i]).strftime("%H:%M:%S")
        V.text(img, f"E08  Janys  2026-11-05 {clock}  ({d['seg_name'][i]})   arm pose methods vs OpenCap "
               "(grey ghost = OpenCap)", (10, 26), 0.6, V.INK, 2)  # fmt: skip
        V.text(img, "Trained models: Janys + Tom 10/28 unless named. Right arm in the chest frame, same view "
               "for every method. Swings (grey ticks) from the Watch.", (10, 52), 0.42, V.GREY)  # fmt: skip
        want = int(round((d["t"][i] - fitted["clip_unix0"]) * cfps))
        camimg = np.full((top_h, CAM_W, 3), 30, np.uint8)
        if 0 <= want < cn:
            if want < cpos or want - cpos > 300:
                cap.set(cv2.CAP_PROP_POS_FRAMES, want)
                cpos = want - 1
            while cpos < want:
                ok, f = cap.read()
                cpos += 1
                if ok:
                    cframe = f
            if cframe is not None:
                fr = cframe.copy()
                centre = None
                if gt_ok[i]:
                    uv = cam6.project(fitted["P"], d["gt_mk"][i]) * cscale
                    cam6.draw_skeleton(fr, uv, mk_names, thick=2)
                    centre = uv[mk_names.index("midHip")]
                x0, y0 = follow.window(centre)
                camimg = cv2.resize(fr[y0 : y0 + crop[1], x0 : x0 + crop[0]], (CAM_W, top_h),
                                    interpolation=cv2.INTER_AREA)  # fmt: skip
        V.text(
            camimg, "IMG_0021 + OpenCap skeleton (ground truth)", (8, 20), 0.5, (255, 255, 255), 1
        )
        img[V.HEADER : V.HEADER + top_h, :CAM_W] = camimg
        for k, (nm, m) in enumerate(zip(names, ms)):
            r, c = divmod(k, NCOL)
            col = bgr(method_color(nm)) if method_color(nm) != "#b5b4ae" else ARM_OTHER
            pan = panel(nm, col, m["hum"][i], m["fore"][i],
                              d["gt_hum"][i] if gt_ok[i] else np.full(3, np.nan),
                              d["gt_fore"][i] if gt_ok[i] else np.full(3, np.nan),
                              m["elbow"][i], gel[i] if gt_ok[i] else np.nan)  # fmt: skip
            pan = cv2.resize(pan, (PANEL, PANEL), interpolation=cv2.INTER_AREA)
            x, y = CAM_W + c * PANEL, V.HEADER + r * PANEL
            img[y : y + PANEL, x : x + PANEL] = pan
            cv2.rectangle(img, (x, y), (x + PANEL - 1, y + PANEL - 1), V.LIGHT, 1)
        cy = V.HEADER + top_h + 8
        gmask = lambda v: np.where(gt_ok, v, np.nan)  # noqa: E731
        V.chart(
            img,
            cy,
            W,
            "Watch rotation speed",
            [(spin, (90, 90, 90), 1)],
            tp,
            now,
            1500,
            sw,
            "deg/s",
        )
        V.chart(img, cy + V.CHART_H, W, "Elbow flexion",
                [(gmask(gel), V.GT_COLOR, 3)] + [(curves[k][0], bgr(method_color(names[k])), 1) for k in colored],
                tp, now, 160, sw, "deg")  # fmt: skip
        V.chart(img, cy + 2 * V.CHART_H, W, "Shoulder elevation",
                [(gmask(gev), V.GT_COLOR, 3)] + [(curves[k][1], bgr(method_color(names[k])), 1) for k in colored],
                tp, now, 160, sw, "deg")  # fmt: skip
        V.text(img, "Black: OpenCap. Colours: methods as in the panels (grey-panel methods not drawn in the "
               "charts). Last 10 s; right edge is now.", (10, H - 14), 0.42, V.GREY)  # fmt: skip
        wr.write(img)
    wr.release()
    print("saved", path)


if __name__ == "__main__":
    main()
