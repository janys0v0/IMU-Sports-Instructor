"""Resample a device stream onto a fixed-rate grid (MobilePoser runs at 30 Hz)."""

from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from pipeline.preprocessing.motion_io import DeviceStream

MODEL_FPS = 30.0
MAX_GAP_S = 0.25  # grid points inside a longer sensor gap are marked invalid


@dataclass
class Resampled:
    t: np.ndarray  # grid times, device clock
    rot: Rotation  # device -> reference frame
    user_acc: np.ndarray  # (N, 3) g, device frame
    gravity: np.ndarray  # (N, 3) g, device frame
    rot_rate: np.ndarray  # (N, 3) rad/s, device frame
    valid: np.ndarray  # (N,) False where the source had a gap > MAX_GAP_S


def resample(stream: DeviceStream, rate=MODEL_FPS, t_start=None, t_end=None) -> Resampled:
    t0 = stream.t[0] if t_start is None else max(t_start, stream.t[0])
    t1 = stream.t[-1] if t_end is None else min(t_end, stream.t[-1])
    grid = np.arange(t0, t1, 1.0 / rate)

    rot = Slerp(stream.t, Rotation.from_quat(stream.quat))(grid)

    def lerp(values):
        return np.stack(
            [np.interp(grid, stream.t, values[:, k]) for k in range(values.shape[1])], axis=1
        )

    # Distance from each grid point to the nearest real sample on each side.
    idx = np.clip(np.searchsorted(stream.t, grid), 1, len(stream.t) - 1)
    gap = stream.t[idx] - stream.t[idx - 1]
    valid = gap <= MAX_GAP_S
    return Resampled(
        t=grid,
        rot=rot,
        user_acc=lerp(stream.user_acc),
        gravity=lerp(stream.gravity),
        rot_rate=lerp(stream.rot_rate),
        valid=valid,
    )
