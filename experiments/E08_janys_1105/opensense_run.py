"""OpenSense IK (Watch + phone) on the 11/05 test set with E07's IK script, unchanged except for
its inputs: E08's results folder, and only the two Apple sensors. Runs in the OpenSim env:

    ~/micromamba-envs/opensim/bin/python experiments/E08_janys_1105/opensense_run.py [--arm-only]
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "E07_pose_methods"))
import opensense_ik as ik  # noqa: E402

ik.RES = HERE / "results"
ik.IMUS = {k: v for k, v in ik.IMUS.items() if k in ("radius_r_imu", "femur_r_imu")}
ik.VARIANTS = {"opensense_watch_phone": ["radius_r_imu", "femur_r_imu"]}
if "--arm-only" in sys.argv:  # right arm only (5 DOF), Watch on the forearm
    ik.VARIANTS = {}

if __name__ == "__main__":
    ik.main("janys")
