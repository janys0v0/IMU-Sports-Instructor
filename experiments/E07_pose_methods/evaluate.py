"""Score every method against OpenCap: whole block and swings only (±0.5 s around each swing).

.venv/bin/python -m experiments.E07_pose_methods.evaluate   # writes results/scores.json
"""

import json

import numpy as np

from .common import OUT, angle_between, load, load_method, methods
from .data import PLAYERS, elevation_plane

PLANE_MIN_ELEV = 30.0  # the plane of elevation is meaningless for a hanging arm
SHOULDER, ELBOW, WRIST = 1, 2, 3  # OpenCap marker order (RShoulder, RElbow, RWrist)


def arm_lengths(mk, valid):
    """Upper-arm and forearm length (m): median OpenCap marker distances over valid frames."""
    m = mk[valid]
    upper = np.nanmedian(np.linalg.norm(m[:, ELBOW] - m[:, SHOULDER], axis=1))
    fore = np.nanmedian(np.linalg.norm(m[:, WRIST] - m[:, ELBOW], axis=1))
    return float(upper), float(fore)


def position_errors(hum, fore, gt_hum, gt_fore, lengths):
    """Elbow and wrist position error (cm), shoulder-anchored in the trunk frame.

    Both arms get the player's OpenCap segment lengths, so only the directions differ:
    elbow = |Lu (h - h*)|, wrist = |Lu (h - h*) + Lf (f - f*)|."""
    lu, lf = lengths
    e = lu * (hum - gt_hum)
    w = e + lf * (fore - gt_fore)
    return 100 * np.linalg.norm(e, axis=1), 100 * np.linalg.norm(w, axis=1)


def score(d, m):
    base = d["gt_valid"] & m["valid"]
    lengths = arm_lengths(d["gt_mk"], d["gt_valid"])
    out = {}
    for part, mask in (("all", base), ("swing", base & d["in_swing"])):
        s = {"minutes": round(float(mask.sum() / 30 / 60), 2)}
        if mask.sum() < 30:
            out[part] = s
            continue
        fore_ok = mask & np.isfinite(m["fore"]).all(1)
        if fore_ok.sum():
            s["forearm_dir_deg"] = float(
                np.median(angle_between(m["fore"][fore_ok], d["gt_fore"][fore_ok]))
            )
            # heading-free: how far the forearm points up from hanging, relative to the trunk
            inc = np.degrees(np.arccos(np.clip(-m["fore"][fore_ok][:, 1], -1, 1)))
            inc_gt = np.degrees(np.arccos(np.clip(-d["gt_fore"][fore_ok][:, 1], -1, 1)))
            s["forearm_incl_mae"] = float(np.median(np.abs(inc - inc_gt)))
            s["forearm_incl_r"] = float(np.corrcoef(inc, inc_gt)[0, 1])
        hum_ok = mask & np.isfinite(m["hum"]).all(1)
        if hum_ok.sum():
            s["upper_arm_dir_deg"] = float(
                np.median(angle_between(m["hum"][hum_ok], d["gt_hum"][hum_ok]))
            )
            el, pl = elevation_plane(m["hum"][hum_ok])
            e = el - d["gt_elev"][hum_ok]
            s["elevation_mae"] = float(np.median(np.abs(e)))
            s["elevation_r"] = float(np.corrcoef(el, d["gt_elev"][hum_ok])[0, 1])
            up = d["gt_elev"][hum_ok] > PLANE_MIN_ELEV
            if up.sum() > 30:
                dp = (pl[up] - d["gt_plane"][hum_ok][up] + 180) % 360 - 180
                s["plane_mae"] = float(np.median(np.abs(dp)))
        both_ok = hum_ok & np.isfinite(m["fore"]).all(1)
        if both_ok.sum() > 30:
            pe, pw = position_errors(m["hum"][both_ok], m["fore"][both_ok],
                                     d["gt_hum"][both_ok], d["gt_fore"][both_ok], lengths)  # fmt: skip
            s["elbow_pos_cm"] = float(np.median(pe))
            s["wrist_pos_cm"] = float(np.median(pw))
        if "prosup" in m and "gt_prosup" in d:  # forearm twist (twist.py)
            tw_ok = mask & np.isfinite(m["prosup"]) & np.isfinite(d["gt_prosup"])
            if tw_ok.sum() > 30:
                e = (m["prosup"][tw_ok] - d["gt_prosup"][tw_ok] + 180) % 360 - 180
                s["pronation_mae"] = float(np.median(np.abs(e)))
                s["pronation_bias"] = float(np.median(e))
        el_ok = mask & np.isfinite(m["elbow"])
        if el_ok.sum() > 30:
            e = m["elbow"][el_ok] - d["gt_elbow"][el_ok]
            s["elbow_mae"] = float(np.median(np.abs(e)))
            s["elbow_bias"] = float(np.median(e))
            s["elbow_r"] = float(np.corrcoef(m["elbow"][el_ok], d["gt_elbow"][el_ok])[0, 1])
        out[part] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}
    return out


def main():
    scores = {}
    for p in PLAYERS:
        d = load(p)
        for name in methods(p):
            scores.setdefault(name, {})[p] = score(d, load_method(p, name))
    (OUT / "scores.json").write_text(json.dumps(scores, indent=1) + "\n")
    cols = [
        "forearm_incl_mae",
        "elevation_mae",
        "elbow_mae",
        "elbow_r",
        "forearm_dir_deg",
        "upper_arm_dir_deg",
        "plane_mae",
    ]
    for part in ("all", "swing"):
        print(f"\n{part:5s} {'method':34s}" + "".join(f"{c[:12]:>13s}" for c in cols))
        for name, v in scores.items():
            for p in PLAYERS:
                s = v.get(p, {}).get(part, {})
                print(
                    f"      {name[:26]:26s} {p:7s}"
                    + "".join(
                        f"{s.get(c, float('nan')):13.1f}"
                        if not c.endswith("_r")
                        else f"{s.get(c, float('nan')):13.2f}"
                        for c in cols
                    )
                )


if __name__ == "__main__":
    main()
