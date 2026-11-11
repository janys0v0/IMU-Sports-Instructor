"""9-axis Madgwick (gyro + gravity + magnetometer all the time) for the commercial sensors.

E06's filter used the magnetometer once, after each hold; with tennis swings (1000+ deg/s) the
gyro-only heading then drifts 20-160 deg within minutes (wrist sensor vs the Watch on the same
wrist). Keeping the field in the loop bounds that drift; the field near the court is disturbed,
so the gain on it is kept low.
"""

import numpy as np
from scipy.spatial.transform import Rotation

BETA = 0.05


def madgwick_marg(t, gyro, acc, mag, q0: Rotation, beta=BETA):
    """Sensor -> earth (x magnetic north, y west, z up) at every sample. `mag` on the same times
    (NaN rows = no field sample: that step uses gravity only)."""
    x, y, z, w = q0.as_quat()
    q = np.array([w, x, y, z])
    out = np.empty((len(t), 4))
    out[0] = q
    for i in range(1, len(t)):
        dt = max(t[i] - t[i - 1], 0.0)
        gx, gy, gz = gyro[i]
        q1, q2, q3, q4 = q
        qdot = 0.5 * np.array([-q2 * gx - q3 * gy - q4 * gz, q1 * gx + q3 * gz - q4 * gy,
                               q1 * gy - q2 * gz + q4 * gx, q1 * gz + q2 * gy - q3 * gx])  # fmt: skip
        a = acc[i]
        na = np.linalg.norm(a)
        if na > 0:
            ax, ay, az = a / na
            m = mag[i]
            if np.isfinite(m).all() and np.linalg.norm(m) > 0:
                mx, my, mz = m / np.linalg.norm(m)
                # earth-frame field direction from the current estimate
                hx = (
                    mx * (q1 * q1 + q2 * q2 - q3 * q3 - q4 * q4)
                    + 2 * my * (q2 * q3 - q1 * q4)
                    + 2 * mz * (q2 * q4 + q1 * q3)
                )
                hy = (
                    2 * mx * (q2 * q3 + q1 * q4)
                    + my * (q1 * q1 - q2 * q2 + q3 * q3 - q4 * q4)
                    + 2 * mz * (q3 * q4 - q1 * q2)
                )
                bx, bz = (
                    np.hypot(hx, hy),
                    2 * mx * (q2 * q4 - q1 * q3)
                    + 2 * my * (q3 * q4 + q1 * q2)
                    + mz * (q1 * q1 - q2 * q2 - q3 * q3 + q4 * q4),
                )
                f = np.array(
                    [
                        2 * (q2 * q4 - q1 * q3) - ax,
                        2 * (q1 * q2 + q3 * q4) - ay,
                        2 * (0.5 - q2 * q2 - q3 * q3) - az,
                        2 * bx * (0.5 - q3 * q3 - q4 * q4) + 2 * bz * (q2 * q4 - q1 * q3) - mx,
                        2 * bx * (q2 * q3 - q1 * q4) + 2 * bz * (q1 * q2 + q3 * q4) - my,
                        2 * bx * (q1 * q3 + q2 * q4) + 2 * bz * (0.5 - q2 * q2 - q3 * q3) - mz,
                    ]
                )
                J = np.array([
                    [-2 * q3, 2 * q4, -2 * q1, 2 * q2],
                    [2 * q2, 2 * q1, 2 * q4, 2 * q3],
                    [0, -4 * q2, -4 * q3, 0],
                    [-2 * bz * q3, 2 * bz * q4, -4 * bx * q3 - 2 * bz * q1, -4 * bx * q4 + 2 * bz * q2],
                    [-2 * bx * q4 + 2 * bz * q2, 2 * bx * q3 + 2 * bz * q1, 2 * bx * q2 + 2 * bz * q4, -2 * bx * q1 + 2 * bz * q3],
                    [2 * bx * q3, 2 * bx * q4 - 4 * bz * q2, 2 * bx * q1 - 4 * bz * q3, 2 * bx * q2],
                ])  # fmt: skip
            else:
                f = np.array(
                    [
                        2 * (q2 * q4 - q1 * q3) - ax,
                        2 * (q1 * q2 + q3 * q4) - ay,
                        2 * (0.5 - q2 * q2 - q3 * q3) - az,
                    ]
                )
                J = np.array(
                    [
                        [-2 * q3, 2 * q4, -2 * q1, 2 * q2],
                        [2 * q2, 2 * q1, 2 * q4, 2 * q3],
                        [0, -4 * q2, -4 * q3, 0],
                    ]
                )
            s = J.T @ f
            ns = np.linalg.norm(s)
            if ns > 0:
                qdot = qdot - beta * s / ns
        q = q + qdot * dt
        q /= np.linalg.norm(q)
        out[i] = q
    return Rotation.from_quat(out[:, [1, 2, 3, 0]])


def device_stream_marg(raw, hold, t_end, beta=BETA):
    """Like E06's commercial.device_stream (same conventions, unix time), but 9-axis throughout."""
    from experiments.E06_side_by_side import commercial as C
    from pipeline.preprocessing.motion_io import DeviceStream

    sel = (raw.t >= hold[0] - C.PRE_HOLD_S) & (raw.t <= t_end)
    t, gyro, acc = raw.t[sel], raw.gyro[sel], raw.acc[sel]
    in_hold = (t >= hold[0]) & (t <= hold[1])
    bias = gyro[in_hold].mean(axis=0)
    mag = np.full((len(t), 3), np.nan)
    if len(raw.mag_t) > 10:
        j = np.clip(np.searchsorted(raw.mag_t, t), 1, len(raw.mag_t) - 1)
        near = np.minimum(np.abs(raw.mag_t[j] - t), np.abs(raw.mag_t[j - 1] - t)) < 0.05
        mi = np.stack([np.interp(t, raw.mag_t, raw.mag[:, k]) for k in range(3)], 1)
        mag[near] = mi[near]
    hm = mag[in_hold & np.isfinite(mag[:, 0])]
    q0 = C.tilt_heading(acc[in_hold].mean(axis=0), hm.mean(axis=0) if len(hm) > 5 else None)
    rot = madgwick_marg(t, gyro - bias, acc, mag, q0, beta)
    gravity = rot.inv().apply([0.0, 0.0, -1.0])
    return DeviceStream(
        device="commercial",
        loc=raw.sid,
        t=t,
        quat=rot.as_quat(),
        user_acc=-acc / C.G - gravity,
        gravity=gravity,
        rot_rate=gyro - bias,
        boot_to_unix=0.0,
        ref_frame="xMagneticNorthZVertical",
    )
