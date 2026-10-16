"""Convert Apple device motion into MobilePoser's body frame.

Frames
- Device (S): the phone's axes.
- World (I): Apple reference frame, `xMagneticNorthZVertical`: x north, z up.
  The attitude quaternion rotates device axes into this frame (R_IS); verified on
  recordings: R_IS @ gravity_device = (0, 0, -1).
- Body (M): SMPL/MobilePoser frame fixed at calibration: x = subject's left,
  y = up, z = forward.

Calibration (TransPose/MobilePoser live-demo method) while standing straight:
- R_MI: world -> body. Up is world z. Forward comes from the phone's screen normal,
  flat against the front of the thigh: screen facing the leg -> forward = -screen normal.
- device2bone = (R_MI R_IS)^T, so the thigh "bone" is identity when standing.
- Output per frame: ori = R_MI R_IS(t) device2bone,
  acc = R_MI R_IS(t) (-9.81 * user_acc) - offset   (m/s^2, physical sign).
Apple's userAcceleration is minus the physical acceleration (its accelerometer
reports the gravity vector, not specific force), hence the -9.81.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial.transform import Rotation

from motion_io import DeviceStream
from resample import Resampled

G = 9.81
CAL_HOLD_S = 3.0


@dataclass
class Calibration:
    R_MI: np.ndarray  # (3, 3) world -> body
    device2bone: np.ndarray  # (3, 3)
    acc_offset: np.ndarray  # (3,) body frame, m/s^2
    window: tuple  # (t0, t1) device clock
    pocket_screen: str
    checks: dict = field(default_factory=dict)


def event_window(recording, hold_s=CAL_HOLD_S):
    """Still window from the app's calibrate event (phone clock)."""
    event = recording.last_event("calibrate")
    if event is None:
        return None
    t0 = event["t_phone"]
    return (t0 + 0.3, t0 + event.get("hold_s", hold_s))


def find_still_window(stream: DeviceStream, length_s=2.0, max_rot_rms=0.15, upright=0.85):
    """Earliest window where the phone is still and upright (long axis vertical),
    i.e. standing with the phone in a front pocket."""
    rot_norm = np.linalg.norm(stream.rot_rate, axis=1)
    vertical = np.abs(stream.gravity[:, 1])
    step = max(1, int(stream.rate_hz * 0.25))
    n = int(stream.rate_hz * length_s)
    for i in range(0, len(stream.t) - n, step):
        sl = slice(i, i + n)
        if np.sqrt(np.mean(rot_norm[sl] ** 2)) < max_rot_rms and vertical[sl].min() > upright:
            return (stream.t[i], stream.t[i + n - 1])
    return None


# AirPods (CMHeadphoneMotionManager) device axes, from recordings: x right, y forward
# (tilted ~30 deg down in the ear), z up. Its reference frame has an arbitrary heading,
# so the head gets its own R_MI, assuming the subject looks straight ahead at calibration.
AIRPODS_FORWARD = np.array([0.0, 1.0, 0.0])


def calibrate(
    stream: DeviceStream, window, pocket_screen="leg", forward_device=None
) -> Calibration:
    """Pocket phone by default; pass `forward_device` (device-frame forward axis) for other devices."""
    sel = stream.window(*window)
    if sel.sum() < 10:
        raise ValueError(f"Calibration window {window} has only {sel.sum()} samples")
    rots = Rotation.from_quat(stream.quat[sel])
    R_IS = rots.mean().as_matrix()

    up = np.array([0.0, 0.0, 1.0])
    if forward_device is not None:
        forward = R_IS @ forward_device
    else:
        screen_normal = R_IS @ np.array([0.0, 0.0, 1.0])
        forward = -screen_normal if pocket_screen == "leg" else screen_normal
    horizontal = forward - up * forward.dot(up)
    horizontal_fraction = float(np.linalg.norm(horizontal))
    forward = horizontal / horizontal_fraction
    left = np.cross(up, forward)
    R_MI = np.stack([left, up, forward])
    device2bone = (R_MI @ R_IS).T

    acc_world = rots.apply(-G * stream.user_acc[sel])
    acc_offset = (R_MI @ acc_world.T).T.mean(axis=0)

    gravity_body = (R_MI @ rots.apply(G * stream.gravity[sel]).T).T.mean(axis=0)
    rot_rms = float(np.sqrt(np.mean(np.sum(stream.rot_rate[sel] ** 2, axis=1))))
    checks = {
        "window_s": round(float(window[1] - window[0]), 2),
        "still_rot_rms_rad_s": round(rot_rms, 3),
        "gravity_body_m_s2": np.round(gravity_body, 3).tolist(),  # expect (0, -9.81, 0)
        "heading_horizontal_fraction": round(horizontal_fraction, 3),  # expect > 0.7
        "acc_offset_m_s2": np.round(acc_offset, 3).tolist(),  # expect near 0
        "R_MI_det": round(float(np.linalg.det(R_MI)), 6),  # expect +1
        "quat_norm_max_err": round(float(np.abs(np.linalg.norm(stream.quat, axis=1) - 1).max()), 6),
        "R_IS_gravity_err": round(
            float(np.abs(Rotation.from_quat(stream.quat).apply(stream.gravity) - [0, 0, -1]).max()),
            4,
        ),
    }
    checks["passed"] = bool(
        rot_rms < 0.2
        and abs(gravity_body[1] + G) < 0.3
        and np.hypot(gravity_body[0], gravity_body[2]) < 0.3
        and horizontal_fraction > 0.7
        and abs(checks["R_MI_det"] - 1) < 1e-6
        and checks["quat_norm_max_err"] < 1e-3
        and checks["R_IS_gravity_err"] < 0.01
    )
    return Calibration(
        R_MI=R_MI,
        device2bone=device2bone,
        acc_offset=acc_offset,
        window=window,
        pocket_screen=pocket_screen,
        checks=checks,
    )


def to_body(cal: Calibration, res: Resampled):
    """Per-frame body-frame acceleration (m/s^2) and bone orientation (3x3)."""
    R_IS = res.rot.as_matrix()  # (N, 3, 3)
    ori = cal.R_MI @ R_IS @ cal.device2bone
    acc = (cal.R_MI @ res.rot.apply(-G * res.user_acc).T).T - cal.acc_offset
    return acc, ori


def thigh_pitch_deg(ori):
    """Forward swing of the bone's long axis (-y at calibration) in the sagittal plane.
    Positive = knee forward (hip flexion)."""
    axis = ori @ np.array([0.0, -1.0, 0.0])
    return np.degrees(np.arctan2(axis[:, 2], -axis[:, 1]))


def mediolateral_check(cal: Calibration, stream: DeviceStream, min_rot=1.0):
    """Model-free heading check: during brisk thigh motion the main rotation axis is
    left-right. Returns the angle (deg, 0-90) between it and the calibrated left axis."""
    rots = Rotation.from_quat(stream.quat)
    omega_body = (cal.R_MI @ rots.apply(stream.rot_rate).T).T
    moving = np.linalg.norm(stream.rot_rate, axis=1) > min_rot
    if moving.sum() < 30:
        return None
    horiz = omega_body[moving][:, [0, 2]]
    _, _, vt = np.linalg.svd(horiz - horiz.mean(axis=0), full_matrices=False)
    axis = vt[0]
    return round(float(np.degrees(np.arccos(min(1.0, abs(axis[0]))))), 1)
