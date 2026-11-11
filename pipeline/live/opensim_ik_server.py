"""Live OpenSense IK server: one IK solve per frame, shown in OpenSim's own 3D view.

Runs in the OpenSim env, not .venv; `pipeline/live/opensim_live.py` starts it and talks to it
over stdin/stdout, one JSON object per line:

    in:  {"cmd": "calibrate"}                      model back to the hold pose
         {"t": 12.3, "q": {"radius_r_imu": [w, x, y, z], "femur_r_imu": [...]}}
    out: {"ok": true, "ms": 4.8, "elbow": .., "pro_sup": .., "elevation": .., "plane": ..}

Each orientation is the segment's rotation since the Calibrate hold, in the hold's body frame
(x forward, y up, z right), as in the offline IK (experiments/E07_pose_methods/opensense_ik.py,
whose model, IMU placement, calibration pose and locked coordinates this reuses).

    ~/micromamba-envs/opensim/bin/python pipeline/live/opensim_ik_server.py [--no-viz]
"""

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("SIMBODY_HOME", str(Path(sys.executable).parents[1] / "simbody"))
import opensim as osim  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "opensense_ik", ROOT / "experiments" / "E07_pose_methods" / "opensense_ik.py"
)
osik = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(osik)

VIZ_HZ = 15.0  # a redraw takes ~50 ms; IK still runs on every frame


class Solver:
    def __init__(self, viz=True):
        osim.Logger.setLevelString("error")  # its log goes to stdout, which is our reply channel
        out = Path(tempfile.mkdtemp(prefix="opensim_live_"))
        path = osik.place_imus(out / "model_imu.osim")
        osim.ModelVisualizer.addDirToGeometrySearchPaths(str(osik.MODEL.parent / "Geometry"))
        self.model = osim.Model(str(path))
        self.model.setUseVisualizer(viz)
        self.s = self.model.initSystem()
        self.cs = self.model.getCoordinateSet()
        for name in osik.LOCK:
            self.cs.get(name).setLocked(self.s, True)
        self.bodies = {
            b: self.model.getBodySet().get(b) for b in ("torso", "humerus_r", "radius_r")
        }
        self.viz = self.model.getVisualizer() if viz else None
        self.last_show = 0.0
        self.calibrate()

    def calibrate(self):
        for name in osik.LOCK:
            self.cs.get(name).setLocked(self.s, False)
        osik.set_pose(self.model, self.s, osik.CAL_POSE_DEG)
        for name in osik.LOCK:
            self.cs.get(name).setLocked(self.s, True)
        self.show(force=True)

    def solve(self, quats):
        labels = sorted(quats)
        row = osim.RowVectorRotation(len(labels))
        for j, lab in enumerate(labels):
            row.updElt(0, j).setRotationFromQuaternion(osim.Quaternion(*quats[lab]))
        table = osim.TimeSeriesTableRotation()
        table.setColumnLabels(labels)
        table.appendRow(0.0, row)
        weights = osim.OrientationWeightSet()
        for lab in labels:
            weights.cloneAndAppend(osim.OrientationWeight(lab, 1.0))
        oref = osim.OrientationsReference(table, weights)
        solver = osim.InverseKinematicsSolver(
            self.model, osim.MarkersReference(), oref, osim.SimTKArrayCoordinateReference()
        )
        solver.setAccuracy(1e-4)
        self.s.setTime(0.0)
        solver.assemble(self.s)  # warm start: the state keeps the previous frame's pose
        self.model.realizePosition(self.s)
        self.show()
        return self.readout()

    def readout(self):
        deg = lambda n: float(np.degrees(self.cs.get(n).getValue(self.s)))  # noqa: E731
        R = {b: osik.mat(body.getTransformInGround(self.s).R()) for b, body in self.bodies.items()}
        h = R["torso"].T @ (-R["humerus_r"][:, 1])  # upper arm, trunk frame (x fwd, y up, z right)
        return {
            "elbow": deg("elbow_flex_r"),
            "pro_sup": deg("pro_sup_r"),
            "elevation": float(np.degrees(np.arccos(np.clip(-h[1], -1, 1)))),
            "plane": float(np.degrees(np.arctan2(h[2], h[0]))),
        }

    def show(self, force=False):
        now = time.monotonic()
        if self.viz is not None and (force or now - self.last_show >= 1 / VIZ_HZ):
            self.viz.show(self.s)
            self.last_show = now


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-viz", action="store_true", help="no 3D window (for tests)")
    args = parser.parse_args()
    solver = Solver(viz=not args.no_viz)
    lock = threading.Lock()
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        with lock:
            if msg.get("cmd") == "calibrate":
                solver.calibrate()
                out = {"ok": True, "calibrated": True}
            elif "q" in msg:
                t0 = time.perf_counter()
                try:
                    out = {"ok": True, **solver.solve(msg["q"])}
                except Exception as e:  # noqa: BLE001  IK can fail on a bad frame; keep going
                    out = {"ok": False, "error": str(e)[:120]}
                out["ms"] = round((time.perf_counter() - t0) * 1000, 2)
            else:
                out = {"ok": False, "error": "unknown message"}
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
