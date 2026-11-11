"""Commercial sensor orientation with VQF (Laidig & Seel 2023, `qmt`), offline version.

Tested against OpenCap's segments on 10/28 (fit the mounting in each segment's first minute,
then watch the deviation grow): VQF without the magnetometer drifts least on the upper arm
(14-28 deg over 5 min); with it, the court's disturbed field makes things worse (60-120 deg);
E06's filter (field used once per hold) drifts 20-160 deg on the wrist. No filter holds the
trunk's heading: methods must correct it (see `geometric.py`). The Watch (Apple's own filter)
stays at 15-20 deg against OpenCap's forearm.
"""

import numpy as np
from scipy.spatial.transform import Rotation

FS_VQF = 200.0


def vqf_stream(raw, t0, t1, mag=True, offline=True):
    """(t, quat xyzw sensor -> earth, gyro, acc m/s^2) on a uniform 200 Hz grid in [t0, t1].
    Earth frame: VQF's (z up, x = horizontal field when 9-axis)."""
    import qmt

    g = np.arange(max(t0, raw.t[0]), min(t1, raw.t[-1]), 1 / FS_VQF)
    lin = lambda tt, x: np.stack([np.interp(g, tt, x[:, k]) for k in range(3)], 1)  # noqa: E731
    gyr, acc = lin(raw.t, raw.gyro), lin(raw.t, raw.acc)
    m = None
    if mag and len(raw.mag_t) > 100:
        m = lin(raw.mag_t, raw.mag)
        gapj = np.clip(np.searchsorted(raw.mag_t, g), 1, len(raw.mag_t) - 1)
        far = np.minimum(np.abs(raw.mag_t[gapj] - g), np.abs(raw.mag_t[gapj - 1] - g)) > 0.1
        m[far] = 0.0  # VQF skips zero field samples (NaN breaks it)
    est = qmt.oriEstOfflineVQF if offline else qmt.oriEstVQF
    q = est(gyr, acc, m, params={"Ts": 1 / FS_VQF})
    q = np.asarray(q)
    return g, q[:, [1, 2, 3, 0]], gyr, acc


def vqf_device_stream(raw, hold, t_end, mag=False):
    """DeviceStream (unix time) from VQF, starting 60 s before the hold so the filter settles."""
    from experiments.E06_side_by_side import commercial as C
    from pipeline.preprocessing.motion_io import DeviceStream

    t, q, gyr, acc = vqf_stream(raw, hold[0] - 60.0, t_end, mag=mag)
    in_hold = (t >= hold[0]) & (t <= hold[1])
    rot = Rotation.from_quat(q)
    gravity = rot.inv().apply([0.0, 0.0, -1.0])
    bias = gyr[in_hold].mean(axis=0) if in_hold.any() else 0.0
    return DeviceStream(
        device="commercial",
        loc=raw.sid,
        t=t,
        quat=q,
        user_acc=-acc / C.G - gravity,
        gravity=gravity,
        rot_rate=gyr - bias,
        boot_to_unix=0.0,
        ref_frame="vqf_6d",
    )
