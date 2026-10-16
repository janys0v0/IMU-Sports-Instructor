"""Stage 5 gate (G5), Mac side: tests C7-C9 for the multi-calibration in calibration.py."""

import json
import os
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from pipeline.preprocessing.calibration import (
    bone_orientation,
    calibrate,
    calibrate_all,
    calibration_windows,
)
from pipeline.preprocessing.motion_io import DeviceStream, load_recording
from tests.conftest import recording_dir

# Phone upright in a front pocket: device y up, screen (z) facing forward along world x.
POSE = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


def drifting_phone(minutes=10, drift_deg_per_min=8.0, rate=50):
    """Standing still for the whole session while the heading reference drifts steadily."""
    t = np.arange(0, minutes * 60, 1 / rate)
    yaw = Rotation.from_euler("z", drift_deg_per_min / 60 * t, degrees=True)
    R_IS = yaw * Rotation.from_matrix(POSE)
    gravity = R_IS.inv().apply([0, 0, -1])
    n = len(t)
    stream = DeviceStream(
        device="phone", loc="right_pocket", t=t, quat=R_IS.as_quat(), user_acc=np.zeros((n, 3)),
        gravity=gravity, rot_rate=np.zeros((n, 3)), boot_to_unix=0.0, ref_frame="xMagneticNorthZVertical",
    )  # fmt: skip
    return stream


def worst_angle(ori):
    return float(np.degrees(Rotation.from_matrix(ori).magnitude()).max())


def test_C8_blend_removes_steady_drift():
    stream = drifting_phone()
    windows = [(t, t + 3) for t in (10, 150, 300, 450, 590)]
    cals = calibrate_all(stream, windows, pocket_screen="outward")
    assert len(cals) == 5
    blended = bone_orientation(cals, stream.t, stream.quat)
    inside = (stream.t >= 11.5) & (stream.t <= 591.5)
    assert worst_angle(blended[inside]) < 1.0
    single = bone_orientation(cals[:1], stream.t, stream.quat)
    assert worst_angle(single) > 60, "one calibration lets 8°/min drift build up"


def test_C9_piecewise_across_a_segment_break_holds_the_last_calibration():
    stream = drifting_phone()
    cals = calibrate_all(
        stream, [(50, 53), (250, 253), (350, 353), (550, 553)], pocket_screen="outward"
    )
    segments = [(0, 300), (300, 600)]
    t = np.array([320.0, 340.0])
    k = np.searchsorted(stream.t, t)
    ori = bone_orientation(cals, stream.t[k], stream.quat[k], segments=segments)
    hold = bone_orientation(cals[1:2], stream.t[k], stream.quat[k])
    np.testing.assert_allclose(ori, hold, atol=1e-9)  # uses the calibration at 250 s, not a blend
    blended = bone_orientation(cals, stream.t[k], stream.quat[k])
    assert not np.allclose(ori, blended), "without the break it would blend towards 350 s"


def test_reference_session_windows_are_found():
    rec = load_recording(recording_dir("20261008-153213-P01"))
    assert len(calibration_windows(rec)) == 1


def test_C7_phone_check_agrees_with_mac_calibration():
    export = Path(os.environ.get("MSC_EXPORT_DIR", "/nonexistent")) / "c7_phone_check.json"
    if not export.exists():
        pytest.skip("no exported phone check (run tools/run_tests.sh)")
    phone_check = json.loads(export.read_text())
    rec = load_recording(recording_dir("20261008-153213-P01"))
    stream = next(s for s in rec.streams.values() if s.device == "phone")
    window = tuple(phone_check["window"])
    cal = calibrate(stream, window, pocket_screen="leg")
    assert phone_check["passed"] == cal.checks["passed"]
    sel = stream.window(*window)
    mac = Rotation.from_quat(stream.quat[sel]).mean()
    phone = Rotation.from_quat(phone_check["attitude"])
    assert np.degrees((mac.inv() * phone).magnitude()) < 0.5
