"""Commercial IMU logs (msense sensors: acceleration, rotation rate, magnetometer) as orientation
streams in the same form and reference frame as the Apple devices, so the same calibration and
pose model can run on them.

- Axes: the magnetometer's x, y, z are the gyro's y, x, -z (found from dm/dt = -w x m on the
  10/28 logs, both sensors). Hard-iron offset: centre of the 1st-99th percentile box per axis.
- Orientation: Madgwick filter on rotation rate + acceleration (gravity) at the sensor's rate.
  At each calibration hold it restarts from gravity (tilt), with the gyro bias measured during the
  hold; one constant heading turn then aligns it to magnetic north (Apple's xMagneticNorthZVertical
  frame) using the field in the 30 s from the hold. The magnetometer is used only there: its field
  near the court is too disturbed to steer by, and the log drops field samples in places.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from pipeline.preprocessing.motion_io import DeviceStream

G = 9.80665
MAG_AXES, MAG_SIGNS = (1, 0, 2), np.array([1.0, 1.0, -1.0])
PRE_HOLD_S = 0.5  # stream starts this long before the hold (resampling needs a margin)
BETA = 0.033  # Madgwick gain
HEADING_WINDOW_S = 30.0  # field samples used for the heading, from the hold start


@dataclass
class Raw:
    sid: str
    t: np.ndarray  # logger time, unix seconds
    acc: np.ndarray  # (n, 3) m/s^2, specific force (+1 g up at rest)
    gyro: np.ndarray  # (n, 3) rad/s
    mag_t: np.ndarray
    mag: np.ndarray  # (m, 3) uT in gyro axes, hard-iron corrected


def mag_to_gyro_axes(m):
    return np.asarray(m)[:, MAG_AXES] * MAG_SIGNS


def load(imu_csv, mag_csv, tz="America/New_York") -> dict:
    """sensor id -> Raw, from one logger export."""

    def read(path):
        d = pd.read_csv(path)
        d["unix"] = pd.to_datetime(d["timestamp"]).dt.tz_localize(tz).astype("int64") / 1e9
        return d

    imu, mag = read(imu_csv), read(mag_csv)
    out = {}
    for sid, g in imu.groupby("source_id"):
        g = g.sort_values("unix").drop_duplicates("unix")
        m = mag[mag.source_id == sid].sort_values("unix").drop_duplicates("unix")
        M = mag_to_gyro_axes(m[["mx_uT", "my_uT", "mz_uT"]].to_numpy(float).reshape(-1, 3))
        # No field samples at all for some sensors: heading then stays unreferenced (see device_stream).
        lo = np.percentile(M, 1, axis=0) if len(M) else np.zeros(3)
        hi = np.percentile(M, 99, axis=0) if len(M) else np.zeros(3)
        out[sid] = Raw(
            sid,
            g["unix"].to_numpy(),
            g[["ax", "ay", "az"]].to_numpy(float),
            g[["gx", "gy", "gz"]].to_numpy(float),
            m["unix"].to_numpy(),
            M - (lo + hi) / 2,
        )
    return out


def tilt_heading(acc, mag=None) -> Rotation:
    """Sensor -> earth (x magnetic north, y west, z up) from mean specific force and field.
    Without a field the heading is arbitrary (the sensor's x axis, levelled, is taken as north)."""
    up = acc / np.linalg.norm(acc)
    ref = np.array([1.0, 0, 0]) if mag is None else mag
    if mag is None and abs(np.dot(ref, up)) > 0.9:
        ref = np.array([0, 1.0, 0])
    horizontal = ref - np.dot(ref, up) * up
    north = horizontal / np.linalg.norm(horizontal)
    west = np.cross(up, north)
    return Rotation.from_matrix(np.stack([north, west, up]))


def heading_correction(rot_at, mag_t, mag, t0, t1):
    """Yaw (rad) that turns the filter's frame to magnetic north, from field samples in [t0, t1]:
    each sample, rotated to the earth frame with the filter's orientation at its time, should point
    north (+x). None when the log has no field samples there."""
    sel = (mag_t >= t0) & (mag_t <= t1)
    if sel.sum() < 10:
        return None
    m = rot_at(mag_t[sel]).apply(mag[sel])
    psi = np.arctan2(m[:, 1], m[:, 0])
    return -float(np.arctan2(np.sin(psi).mean(), np.cos(psi).mean()))


def madgwick(t, gyro, acc, q0: Rotation, beta=BETA):
    """Sensor -> earth orientation at every sample (Madgwick 2010, IMU form)."""
    x, y, z, w = q0.as_quat()
    q = np.array([w, x, y, z])
    out = np.empty((len(t), 4))
    out[0] = q
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        gx, gy, gz = gyro[i]
        q0_, q1, q2, q3 = q
        qdot = 0.5 * np.array(
            [-q1 * gx - q2 * gy - q3 * gz, q0_ * gx + q2 * gz - q3 * gy,
             q0_ * gy - q1 * gz + q3 * gx, q0_ * gz + q1 * gy - q2 * gx]
        )  # fmt: skip
        a = acc[i]
        n = np.linalg.norm(a)
        if n > 0:
            ax, ay, az = a / n
            f = np.array([2 * (q1 * q3 - q0_ * q2) - ax, 2 * (q0_ * q1 + q2 * q3) - ay,
                          2 * (0.5 - q1 * q1 - q2 * q2) - az])  # fmt: skip
            J = np.array([[-2 * q2, 2 * q3, -2 * q0_, 2 * q1], [2 * q1, 2 * q0_, 2 * q3, 2 * q2],
                          [0, -4 * q1, -4 * q2, 0]])  # fmt: skip
            s = J.T @ f
            ns = np.linalg.norm(s)
            if ns > 0:
                qdot -= beta * s / ns
        q = q + qdot * max(dt, 0.0)
        q /= np.linalg.norm(q)
        out[i] = q
    return Rotation.from_quat(out[:, [1, 2, 3, 0]])


def device_stream(raw: Raw, hold, t_end, unix_to_phone, sid=None) -> DeviceStream:
    """Stream from `hold` (corrected unix times) to `t_end`, on the phone's clock (t + unix_to_phone).
    Orientation restarts at the hold: tilt from gravity, heading from the magnetometer, gyro bias
    from the hold (the person stands still there)."""
    sel = (raw.t >= hold[0] - PRE_HOLD_S) & (raw.t <= t_end)
    t, gyro, acc = raw.t[sel], raw.gyro[sel], raw.acc[sel]
    in_hold = (t >= hold[0]) & (t <= hold[1])
    bias = gyro[in_hold].mean(axis=0)
    rot = madgwick(t, gyro - bias, acc, tilt_heading(acc[in_hold].mean(axis=0)))
    # Heading: one constant turn to magnetic north from the field just after the hold (the log
    # drops field samples in places, so the hold alone is not enough).
    from scipy.spatial.transform import Slerp

    yaw = heading_correction(
        Slerp(t, rot),
        raw.mag_t,
        raw.mag,
        max(hold[0], t[0]),
        min(hold[0] + HEADING_WINDOW_S, t[-1]),
    )
    if yaw is not None:
        rot = Rotation.from_euler("z", yaw) * rot
    gravity = rot.inv().apply([0.0, 0.0, -1.0])
    return DeviceStream(
        device="commercial",
        loc=sid or raw.sid,
        t=t + unix_to_phone,
        quat=rot.as_quat(),
        user_acc=-acc / G - gravity,
        gravity=gravity,
        rot_rate=gyro - bias,
        boot_to_unix=-unix_to_phone,
        ref_frame="xMagneticNorthZVertical",
    )
