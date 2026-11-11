"""Live viewer and receiver: packets without a session ID and background renders.

Found on device 2026-10-19: the app's sensor packets (audio level, magnetometer, barometer) had no
session ID, so the viewer switched between the real session and "unknown" ~20 times a second,
started a render at every switch and cleared its samples, and calibration never had data.
"""

import pipeline.live.receiver as receiver
from pipeline.live.live_viewer import Receiver


def imu(device, t, session="S1", loc=None, first_index=0):
    return {
        "first_index": first_index,
        "rate_hz": 60,
        "type": "imu",
        "device": device,
        "loc": loc or {"phone": "right_pocket", "watch": "left_wrist", "airpods": "head"}[device],
        "session": session,
        "s": [[t + k / 60] + [0.0] * 13 for k in range(5)],
    }


def test_packets_without_a_session_join_the_current_one():
    assert receiver.session_of({"session": "S1"}, None) == "S1"
    assert receiver.session_of({"type": "audio_level"}, "S1") == "S1"
    assert receiver.session_of({"type": "audio_level"}, None) is None


def test_viewer_keeps_its_session_and_samples_through_sensor_packets(tmp_path, monkeypatch):
    renders = []
    monkeypatch.setattr(receiver, "start_render", renders.append)
    r = Receiver(0, tmp_path)
    r.handle_packet(
        {"type": "audio_level", "device": "phone", "t": 99.9}, 0.0
    )  # before any session
    assert r.session is None
    for k in range(40):
        r.handle_packet(imu("phone", 100 + k / 12, first_index=5 * k), 0.0)
        r.handle_packet({"type": "audio_level", "device": "phone", "t": 100 + k / 12}, 0.0)
    assert r.session.id == "S1"
    assert renders == []
    assert len(r.stream("right_pocket").t) == 200
    assert not (tmp_path / "unknown").exists()


def test_only_one_render_runs_at_a_time(tmp_path, monkeypatch):
    started = []

    class Running:
        def __init__(self, cmd, **kwargs):
            started.append(cmd)

        def poll(self):
            return None  # still running

    monkeypatch.setattr(receiver.subprocess, "Popen", Running)
    monkeypatch.setattr(receiver, "_render", None)
    monkeypatch.setattr(receiver, "VENV_PYTHON", tmp_path / "python")  # CI has no .venv
    (tmp_path / "python").touch()
    for k in range(5):
        (tmp_path / f"s{k}").mkdir()
        receiver.start_render(tmp_path / f"s{k}")
    assert len(started) == 1


def test_opensim_segments_start_at_identity_in_the_body_frame():
    import numpy as np
    from scipy.spatial.transform import Rotation

    from pipeline.live.opensim_live import body_frame, segment_quat

    # phone calibration: forward = world +y, up = world +z (CoreMotion), left = -x
    R_MI = np.array([[-1.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]])  # rows: left, up, forward
    M = body_frame(R_MI)  # world -> OpenSim body (x forward, y up, z right)
    assert np.allclose(M @ [0, 1.0, 0], [1, 0, 0]) and np.allclose(M @ [1.0, 0, 0], [0, 0, 1])
    R_hold = Rotation.from_euler("xyz", [10, 20, 30], degrees=True).as_matrix()
    assert np.allclose(segment_quat(M, R_hold, R_hold), [1, 0, 0, 0])  # w, x, y, z
    # turning 90 deg about the world vertical after the hold = 90 deg about the body's y axis
    R_now = Rotation.from_euler("z", 90, degrees=True).as_matrix() @ R_hold
    q = segment_quat(M, R_now, R_hold)
    assert np.allclose(Rotation.from_quat([*q[1:], q[0]]).as_rotvec(), [0, np.pi / 2, 0])
