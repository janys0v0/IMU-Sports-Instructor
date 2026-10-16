"""Side-by-side reconstruction videos from E02's saved model outputs (no models are re-run).

Run from project/code after run.py:
    .venv/bin/python experiments/E02_imucoco_comparison/make_videos.py [SESSION]

Reads results/<SESSION>/outputs/<model>_<combo>.npz and writes results/<SESSION>/videos/:
- single/<model>_<combo>.mp4   one mesh video per model and device combination (cached)
- compare_<combo>.mp4          MobilePoser | IMUCoCo for one combination
- grid_all.mp4                 rows = models, columns = every combination
Every frame is labelled with the time after Start and the annotated activity.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import metrics, paths, render  # noqa: E402
from common import mobileposer_runner as mp  # noqa: E402

MODELS = ["MobilePoser", "IMUCoCo"]
COMBOS = ["rw_rp_h", "rw_rp", "rp_h", "rp", "rw_h", "rw", "h"]  # trained MobilePoser combos first
LABEL = {
    "rw_rp_h": "Watch+phone+AirPods",
    "rw_rp": "Watch+phone",
    "rp_h": "phone+AirPods",
    "rp": "phone",
    "rw_h": "Watch+AirPods",
    "rw": "Watch",
    "h": "AirPods",
}
TRAINED = {"rw_rp_h", "rw_rp", "rp_h", "rp"}
INK, MUTED, WARN = (40, 40, 40), (110, 110, 110), (30, 30, 170)


def activity_at(t, annotation):
    for a in (annotation or {}).get("activities", []):
        if a["start"] <= t <= a["end"]:
            return a["name"].replace("_", " ")
    return ""


def compose(
    videos, rows, cols, row_labels, col_labels, col_warn, times, annotation, out_path, tile=320
):
    """Grid video: videos[r][c] are equally long mesh videos; labels around the grid, caption on top."""
    import cv2

    caps = [[cv2.VideoCapture(str(v)) for v in row] for row in videos]
    n = min(int(c.get(cv2.CAP_PROP_FRAME_COUNT)) for row in caps for c in row)
    head, side = 70, 130 if rows > 1 else 0
    W, H = side + cols * tile, head + rows * tile
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"avc1"), render.FPS, (W, H))
    font = cv2.FONT_HERSHEY_SIMPLEX
    for k in range(n):
        canvas = np.full((H, W, 3), 255, np.uint8)
        t = times[k] if k < len(times) else times[-1]
        act = activity_at(t, annotation)
        cv2.putText(canvas, f"t = {t:5.1f} s   {act}", (10, 26), font, 0.7, INK, 2, cv2.LINE_AA)
        for c in range(cols):
            x = side + c * tile
            cv2.putText(
                canvas,
                col_labels[c],
                (x + 8, 56),
                font,
                0.5,
                WARN if col_warn[c] else MUTED,
                1,
                cv2.LINE_AA,
            )
        for r in range(rows):
            y = head + r * tile
            if side:
                cv2.putText(
                    canvas, row_labels[r], (8, y + tile // 2), font, 0.6, INK, 2, cv2.LINE_AA
                )
            for c in range(cols):
                ok, f = caps[r][c].read()
                canvas[y : y + tile, side + c * tile : side + (c + 1) * tile] = cv2.resize(
                    f, (tile, tile), interpolation=cv2.INTER_AREA
                )
        writer.write(canvas)
    writer.release()
    for row in caps:
        for c in row:
            c.release()
    if render.frame_count(out_path) != n:
        raise RuntimeError(f"{out_path}: wrote {render.frame_count(out_path)} of {n} frames")
    return n


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("session", nargs="?", default="20261008-153213-P01")
    args = parser.parse_args()

    res = paths.results_dir(HERE / "run.py", args.session)
    single = res / "videos" / "single"
    single.mkdir(parents=True, exist_ok=True)
    annotation = metrics.load_annotation(Path(args.session).name)
    body = mp.body_model()

    files, times = {}, None
    for model in MODELS:
        for combo in COMBOS:
            data = np.load(res / "outputs" / f"{model}_{combo}.npz")
            times = data["t"] if times is None else times
            path = single / f"{model}_{combo}.mp4"
            if not path.exists() or render.frame_count(path) != len(data["pose"]):
                render.render_mesh(body, data["pose"], path)
            files[model, combo] = path
            print("rendered", path.name, flush=True)

    for combo in COMBOS:
        compose(
            [[files[m, combo] for m in MODELS]],
            1,
            2,
            [],
            [f"{m}: {LABEL[combo]}" for m in MODELS],
            [combo not in TRAINED and m == "MobilePoser" for m in MODELS],
            times,
            annotation,
            res / "videos" / f"compare_{combo}.mp4",
            tile=480,
        )
        print("wrote", f"compare_{combo}.mp4", flush=True)
    compose(
        [[files[m, c] for c in COMBOS] for m in MODELS],
        2,
        len(COMBOS),
        MODELS,
        [LABEL[c] + ("" if c in TRAINED else " *") for c in COMBOS],
        [c not in TRAINED for c in COMBOS],
        times,
        annotation,
        res / "videos" / "grid_all.mp4",
        tile=260,
    )
    print("wrote grid_all.mp4  (* = combination MobilePoser was not trained on)")


if __name__ == "__main__":
    main()
