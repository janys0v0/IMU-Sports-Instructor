"""Render SMPL motion to video, and tile several videos side by side with labels.

Every video is checked for its full frame count after writing: one render on 2026-10-08 wrote
only 168 of 7430 frames without any error, so a short file is retried once and then reported.
"""

from pathlib import Path

import numpy as np

FPS = 30


def frame_count(path):
    import cv2

    c = cv2.VideoCapture(str(path))
    n = int(c.get(cv2.CAP_PROP_FRAME_COUNT))
    c.release()
    return n


def render_mesh(body, pose, out_path, size=720, tran=None):
    """Render a local-rotation pose sequence (n, 24, 3, 3); root fixed unless `tran` is given."""
    import torch
    import vctoolkit.viso3d as vo3d

    pose = torch.from_numpy(np.asarray(pose)).float()
    tr = None if tran is None else torch.from_numpy(np.asarray(tran)).float()
    verts = np.concatenate(
        [
            body.forward_kinematics(
                pose[i : i + 500], tran=None if tr is None else tr[i : i + 500], calc_mesh=True
            )[2]
            .numpy()
            .astype(np.float32)
            for i in range(0, len(pose), 500)
        ]
    )
    for _attempt in (1, 2):
        vo3d.render_sequence_3d(
            verts, body.face, size, size, str(out_path), FPS, visible=True, verbose=False
        )
        if frame_count(out_path) == len(verts):
            return out_path
    raise RuntimeError(f"{out_path}: wrote {frame_count(out_path)} of {len(verts)} frames")


def tile(videos, labels, out_path, tile_size=360):
    """Side-by-side video from equally long inputs, each labelled at the top."""
    import cv2

    caps = [cv2.VideoCapture(str(v)) for v in videos]
    n = min(int(c.get(cv2.CAP_PROP_FRAME_COUNT)) for c in caps)
    writer = cv2.VideoWriter(
        str(out_path), cv2.VideoWriter_fourcc(*"avc1"), FPS, (tile_size * len(caps), tile_size)
    )
    for _ in range(n):
        frames = []
        for c, label in zip(caps, labels):
            ok, f = c.read()
            f = cv2.resize(f, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
            cv2.putText(
                f, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 160), 2, cv2.LINE_AA
            )
            frames.append(f)
        writer.write(np.hstack(frames))
    writer.release()
    for c in caps:
        c.release()
    if frame_count(out_path) != n:
        raise RuntimeError(f"{out_path}: wrote {frame_count(out_path)} of {n} frames")
    return Path(out_path)
