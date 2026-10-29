"""E06: commercial IMUs turned into the same orientation streams as the Apple devices."""

import numpy as np
from scipy.spatial.transform import Rotation

from experiments.E06_side_by_side import commercial as C


def test_tilt_and_heading_from_gravity_and_north():
    # Sensor lying flat, its x axis pointing east: earth x (north) is the sensor's +y... rotated.
    true = Rotation.from_euler(
        "z", -90, degrees=True
    )  # sensor -> earth: sensor x points to -y (east)
    up_sensor = true.inv().apply([0, 0, 1])
    north_field = true.inv().apply([20.0, 0, -40.0])  # northern hemisphere: field points down
    est = C.tilt_heading(up_sensor * C.G, north_field)
    assert est.inv().__mul__(true).magnitude() < 1e-6


def test_madgwick_follows_a_rotation_and_keeps_tilt():
    rate = 200.0
    t = np.arange(0, 5, 1 / rate)
    w = np.tile([0.0, 0.0, np.radians(90)], (len(t), 1))  # 90 deg/s about vertical, flat sensor
    acc = np.tile([0.0, 0.0, C.G], (len(t), 1))
    q = C.madgwick(t, w, acc, Rotation.identity())
    yaw = q[-1].as_euler("zyx", degrees=True)[0]
    assert abs(((yaw - 450) + 180) % 360 - 180) < 2
    assert abs(q[-1].apply([0, 0, 1])[2] - 1) < 1e-3


def test_magnetometer_axes_are_mapped_to_the_gyro_frame():
    raw = np.array([[1.0, 2.0, 3.0]])
    assert np.allclose(C.mag_to_gyro_axes(raw), [[2.0, 1.0, -3.0]])


def test_stream_uses_the_apple_conventions():
    rate = 200.0
    t = 1_000.0 + np.arange(0, 4, 1 / rate)
    raw = C.Raw(
        sid="s",
        t=t,
        acc=np.tile([0.0, 0.0, C.G], (len(t), 1)),
        gyro=np.zeros((len(t), 3)),
        mag_t=t,
        mag=np.tile([20.0, 0.0, -40.0], (len(t), 1)),
    )
    s = C.device_stream(raw, hold=(1000.5, 1001.5), t_end=1003.5, unix_to_phone=-900.0)
    assert np.allclose(s.t[0], 100.5 - C.PRE_HOLD_S, atol=0.01)
    assert np.allclose(s.gravity[0], [0, 0, -1], atol=1e-3)  # points down, in g
    assert np.allclose(s.user_acc[0], [0, 0, 0], atol=1e-3)  # at rest
    assert s.ref_frame == "xMagneticNorthZVertical"


def test_heading_comes_from_field_samples_after_the_hold():
    # Field only from 2 s on (the log drops samples during the hold); sensor still, facing west.
    rate = 200.0
    t = 1_000.0 + np.arange(0, 6, 1 / rate)
    true = Rotation.from_euler("z", 90, degrees=True)  # sensor x points west
    field_sensor = true.inv().apply([20.0, 0, -40.0])
    raw = C.Raw("s", t, np.tile([0.0, 0.0, C.G], (len(t), 1)), np.zeros((len(t), 3)),
                t[t > 1002.0], np.tile(field_sensor, ((t > 1002.0).sum(), 1)))  # fmt: skip
    s = C.device_stream(raw, hold=(1000.5, 1001.5), t_end=1005.5, unix_to_phone=0.0)
    est = Rotation.from_quat(s.quat[-1])
    assert (est.inv() * true).magnitude() < np.radians(1)
