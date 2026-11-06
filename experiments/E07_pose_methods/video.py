"""E07 comparison video: phone1 with OpenCap's skeleton, one arm panel per method (OpenCap's arm as
a grey ghost in each), and rolling curves under them: the Watch's 200 Hz rotation speed, elbow
angle and shoulder elevation per method with OpenCap in black.

    .venv/bin/python -m experiments.E07_pose_methods.video PLAYER --methods a,b,c [--start S --seconds N]

Writes results/<player>/videos/compare_<start>.mp4 (not committed).
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .common import OUT, angle_between, load, load_method
from .data import PLAYERS, elevation_plane

FPS = 30
PANEL_W, PANEL_H, CAM_W = 300, 300, 640
CHART_H, HEADER, FOOT = 120, 70, 40
INK, GREY, LIGHT, BG = (40, 40, 40), (150, 150, 150), (225, 225, 225), (250, 250, 250)
GT_COLOR = (30, 30, 30)
COLORS = [
    (214, 120, 42),
    (52, 104, 235),
    (122, 175, 27),
    (0, 161, 237),
    (164, 123, 232),
    (0, 131, 0),
    (129, 129, 217),
    (180, 130, 60),
]  # BGR, fixed order
UPPER_M, FORE_M = 0.30, 0.27
SHOULDER = np.array([0.0, 0.0, 0.18])  # right shoulder in the trunk frame (x fwd, y up, z right), m

NICE = {
    "aligned_trunk_upper_watch": "Geometric: chest+upper-arm+Watch (no mag)",
    "constraint_watch_static_trunk": "Constraints: Watch only",
    "wearmocap_watch": "WearMoCap (pretrained): Watch",
    "mobileposer_rw_rp_h": "MobilePoser: Watch+phone+AirPods",
    "imucoco_rw_rp_h_upperarm_chest": "IMUCoCo: Apple + upper arm + chest",
    "own_gru_watch_phone_personal": "Ours (GRU): Watch+phone",
    "own_gru_watch_phone_xplayer": "Ours (GRU, other player only)",
    "own_ridge_watch_phone_personal": "Ours (ridge): Watch+phone",
    "opensense_trunk_upper_watch_phone": "OpenSense IK: chest+upper arm+Watch+phone",
    "constraint_watch_swing": "Joint-limit constraints: Watch only",
    "imucoco_rw_rp_h": "IMUCoCo: Watch+phone+AirPods",
    "own_gru_watch_xplayer": "Ours GRU: Watch (trained on other player)",
    "own_gru_allsensors_personal": "Ours GRU: all sensors (+own half)",
}


def view(p, az=-35, el=12):
    """Trunk-frame points (x fwd, y up, z right) -> 2D: camera in front-right, looking at the body."""
    a, e = np.radians(az), np.radians(el)
    # rotate about up (y) by az, then tilt by el
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    x1, z1 = x * np.cos(a) - z * np.sin(a), x * np.sin(a) + z * np.cos(a)
    y2 = y * np.cos(e) - x1 * np.sin(e)
    return np.stack([z1, -y2], -1)  # screen: right = +z1, down = -y


def draw_arm(img, hum, fore, color, thick, scale, origin):
    if not (np.isfinite(hum).all() and np.isfinite(fore).all()):
        return
    pts = np.array([SHOULDER, SHOULDER + UPPER_M * hum, SHOULDER + UPPER_M * hum + FORE_M * fore])
    uv = (view(pts) * scale + origin).astype(int)
    cv2.line(img, tuple(uv[0]), tuple(uv[1]), color, thick, cv2.LINE_AA)
    cv2.line(img, tuple(uv[1]), tuple(uv[2]), color, thick, cv2.LINE_AA)
    cv2.circle(img, tuple(uv[1]), thick + 1, color, -1, cv2.LINE_AA)
    cv2.circle(img, tuple(uv[2]), thick + 2, color, -1, cv2.LINE_AA)


def body_outline(img, scale, origin):
    """Trunk and left arm/head silhouette in the trunk frame (fixed)."""
    pts = {
        "neck": np.array([0, 0.05, 0]),
        "pelvis": np.array([0, -0.5, 0]),
        "rs": SHOULDER,
        "ls": -SHOULDER,
        "lh": np.array([0, -0.5, -0.1]),
        "rh": np.array([0, -0.5, 0.1]),
        "head": np.array([0, 0.22, 0]),
        "le": -SHOULDER + np.array([0, -0.3, 0]),
        "lw": -SHOULDER + np.array([0.05, -0.57, 0]),
    }
    uv = {k: (view(v) * scale + origin).astype(int) for k, v in pts.items()}
    for a, b in (
        ("ls", "rs"),
        ("neck", "pelvis"),
        ("lh", "rh"),
        ("ls", "le"),
        ("le", "lw"),
        ("rs", "rh"),
        ("ls", "lh"),
    ):
        cv2.line(img, tuple(uv[a]), tuple(uv[b]), LIGHT, 3, cv2.LINE_AA)
    cv2.circle(img, tuple(uv["head"]), int(0.09 * scale), LIGHT, 3, cv2.LINE_AA)


def text(img, s, xy, scale=0.45, color=INK, thick=1):
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def arm_panel(name, color, hum, fore, gh, gf, el, gel):
    img = np.full((PANEL_H, PANEL_W, 3), 255, np.uint8)
    scale, origin = 330, np.array([PANEL_W / 2, 110])
    body_outline(img, scale, origin)
    draw_arm(img, gh, gf, (175, 175, 175), 7, scale, origin)
    draw_arm(img, hum, fore, color, 4, scale, origin)
    text(img, NICE.get(name, name)[:44], (8, 18), 0.42, INK, 1)
    if np.isfinite(el) and np.isfinite(gel):
        text(img, f"elbow {el:5.0f}  (OpenCap {gel:3.0f})", (8, PANEL_H - 28), 0.42, INK)
    if np.isfinite(fore).all() and np.isfinite(gf).all():
        text(
            img,
            f"forearm off by {float(angle_between(fore, gf)):3.0f} deg",
            (8, PANEL_H - 10),
            0.42,
            GREY,
        )
    return img


def chart(img, y0, w, title, series, t, now, ymax, swings, unit):
    left, right = 70, w - 10
    text(img, f"{title} ({unit})", (left, y0 + 12), 0.42, INK, 1)
    y0 += 18
    h = CHART_H - 26
    cv2.rectangle(img, (left, y0), (right, y0 + h), LIGHT, 1)
    sel = (t > now - 10) & (t <= now)
    x_of = lambda tt: (left + (tt - (now - 10)) / 10 * (right - left)).astype(int)  # noqa: E731
    for s in swings[(swings > now - 10) & (swings <= now)]:
        cv2.line(
            img,
            (int(x_of(np.array([s]))[0]), y0),
            (int(x_of(np.array([s]))[0]), y0 + h),
            (200, 220, 245),
            1,
        )
    for v, color, thick in series:
        vv = v[sel]
        ok = np.isfinite(vv)
        if ok.sum() < 2:
            continue
        pts = np.stack([x_of(t[sel]), (y0 + h - np.clip(vv, 0, ymax) / ymax * h).astype(int)], 1)
        for a, b, oa, ob in zip(pts[:-1], pts[1:], ok[:-1], ok[1:]):
            if oa and ob:
                cv2.line(img, tuple(a), tuple(b), color, thick, cv2.LINE_AA)
    text(img, f"{ymax:.0f}", (left - 30, y0 + 10), 0.35, GREY)
    text(img, "0", (left - 14, y0 + h), 0.35, GREY)


def main():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from experiments.E06_side_by_side import camera

    p = argparse.ArgumentParser()
    p.add_argument("player", choices=list(PLAYERS))
    p.add_argument("--methods", required=True)
    p.add_argument("--start", type=float, default=0.0, help="seconds into the block")
    p.add_argument("--seconds", type=float)
    p.add_argument("--clip", help="phone1 clip (960x540 copy)")
    a = p.parse_args()
    d = load(a.player)
    names = a.methods.split(",")
    ms = [load_method(a.player, n) for n in names]
    t = d["t"] - d["t"][0]
    i0 = int(a.start * FPS)
    i1 = len(t) if not a.seconds else min(len(t), i0 + int(a.seconds * FPS))
    label = PLAYERS[a.player][0]
    fitted = json.loads(camera.CAMERA_JSON.read_text())
    clip = a.clip or str(camera.DATA / fitted["clips"][label]["clip"]).replace(".MOV", "_540.mov")
    clip_unix = fitted["clips"][label]["start_unix"]
    cap = cv2.VideoCapture(clip)
    cfps, cn = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    csize = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cscale = csize[0] / fitted["frame_size"][0]
    mk_names = list(d["mk_names"])
    cpos, cframe = -1, None
    crop_h = int(0.8 * csize[1])
    crop = (min(csize[0], int(crop_h * CAM_W / (2 * PANEL_H))), crop_h)
    follow = camera.Follow(csize, crop)

    gel, gev = d["gt_elbow"], d["gt_elev"]
    curves = []
    for m in ms:
        ev, _ = (
            elevation_plane(np.where(np.isfinite(m["hum"]), m["hum"], np.nan))
            if np.isfinite(m["hum"]).any()
            else (np.full(len(t), np.nan), None)
        )
        curves.append((m["elbow"], ev))
    hf_t = d["hf_t"] - d["t"][0]
    hf_w = np.degrees(d["hf_w"])
    sw = d["swing_t"] - d["t"][0]

    ncol = 4
    rows = int(np.ceil(len(ms) / ncol))
    W = CAM_W + ncol * PANEL_W
    top_h = max(2 * PANEL_H, rows * PANEL_H)
    H = HEADER + top_h + 3 * CHART_H + FOOT
    out_dir = OUT / a.player / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"compare_{int(a.start)}.mp4"
    wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"avc1"), FPS, (W, H))
    gt_ok = d["gt_valid"]
    import datetime as dt

    for i in range(i0, i1):
        img = np.full((H, W, 3), BG, np.uint8)
        now = t[i]
        clock = dt.datetime.fromtimestamp(d["t"][i]).strftime("%H:%M:%S")
        text(
            img,
            f"E07  {a.player.capitalize()}  2026-10-28 {clock}   arm pose methods vs OpenCap (grey ghost = OpenCap)",
            (10, 26),
            0.62,
            INK,
            2,
        )
        text(
            img,
            "Right arm in the chest frame, same view for every method. Swings (blue ticks) from the Watch's 200 Hz rotation speed.",
            (10, 52),
            0.45,
            GREY,
        )
        # camera
        want = int(round((d["t"][i] - clip_unix) * cfps))
        cam = np.full((top_h, CAM_W, 3), 30, np.uint8)
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
                    uv = camera.project(fitted["P"], d["gt_mk"][i]) * cscale
                    camera.draw_skeleton(fr, uv, mk_names, thick=2)
                    centre = uv[mk_names.index("midHip")]
                x0, y0 = follow.window(centre)
                view_ = fr[y0 : y0 + crop[1], x0 : x0 + crop[0]]
                cam = cv2.resize(view_, (CAM_W, top_h), interpolation=cv2.INTER_AREA)
        text(cam, "phone1 + OpenCap skeleton (ground truth)", (8, 20), 0.5, (255, 255, 255), 1)
        img[HEADER : HEADER + top_h, :CAM_W] = cam
        for k, (n, m) in enumerate(zip(names, ms)):
            r, c = divmod(k, ncol)
            pan = arm_panel(
                n,
                COLORS[k % len(COLORS)],
                m["hum"][i],
                m["fore"][i],
                d["gt_hum"][i] if gt_ok[i] else np.full(3, np.nan),
                d["gt_fore"][i] if gt_ok[i] else np.full(3, np.nan),
                m["elbow"][i],
                gel[i] if gt_ok[i] else np.nan,
            )
            x, y = CAM_W + c * PANEL_W, HEADER + r * PANEL_H
            img[y : y + PANEL_H, x : x + PANEL_W] = pan
            cv2.rectangle(img, (x, y), (x + PANEL_W - 1, y + PANEL_H - 1), LIGHT, 1)
        cy = HEADER + top_h + 8
        gmask = lambda v: np.where(gt_ok, v, np.nan)  # noqa: E731
        sel_hf = (hf_t > now - 10) & (hf_t <= now)
        # rotation speed chart from the 200 Hz stream (decimated)
        chart(
            img,
            cy,
            W,
            "Watch rotation speed",
            [
                (
                    np.interp(t, hf_t[sel_hf], hf_w[sel_hf], left=np.nan, right=np.nan)
                    if sel_hf.sum() > 2
                    else np.full(len(t), np.nan),
                    (60, 60, 200),
                    1,
                )
            ],
            t,
            now,
            1500,
            sw,
            "deg/s",
        )
        chart(
            img,
            cy + CHART_H,
            W,
            "Elbow flexion",
            [(gmask(gel), GT_COLOR, 3)]
            + [(c[0], COLORS[k % len(COLORS)], 1) for k, c in enumerate(curves)],
            t,
            now,
            160,
            sw,
            "deg",
        )
        chart(
            img,
            cy + 2 * CHART_H,
            W,
            "Shoulder elevation",
            [(gmask(gev), GT_COLOR, 3)]
            + [(c[1], COLORS[k % len(COLORS)], 1) for k, c in enumerate(curves)],
            t,
            now,
            160,
            sw,
            "deg",
        )
        text(
            img,
            "Black: OpenCap. Colours: methods as in the panels. Last 10 s; right edge is now.",
            (10, H - 14),
            0.42,
            GREY,
        )
        wr.write(img)
    wr.release()
    print("saved", path)


if __name__ == "__main__":
    main()
