"""OpenSense IK (Watch + phone) on the 11/05 test set with E07's IK script, unchanged except for
its inputs: E08's results folder, and only the two Apple sensors. Runs in the OpenSim env:

    ~/micromamba-envs/opensim/bin/python experiments/E08_new_day/opensense_run.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "E07_pose_methods"))
import opensense_ik as ik  # noqa: E402

ik.RES = HERE / "results"
ik.IMUS = {k: v for k, v in ik.IMUS.items() if k in ("radius_r_imu", "femur_r_imu")}
ik.VARIANTS = {"opensense_watch_phone": ["radius_r_imu", "femur_r_imu"]}

if __name__ == "__main__":
    ik.main("janys")
