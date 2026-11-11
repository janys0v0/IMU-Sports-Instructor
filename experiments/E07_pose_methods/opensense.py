"""OpenSim OpenSense IMU inverse kinematics on our virtual IMUs (aligned.npz), scored like the other
methods against OpenCap.

    .venv/bin/python -m experiments.E07_pose_methods.opensense            # IK + save
    .venv/bin/python -m experiments.E07_pose_methods.opensense --save     # save only (IK done)

OpenSim 4.6 (osx-arm64, conda channel opensim-org) lives in its own env, outside .venv:
    curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest | tar -xvj -C ~/micromamba-bin bin/micromamba
    MAMBA_ROOT_PREFIX=~/micromamba ~/micromamba-bin/bin/micromamba create -y -p ~/micromamba-envs/opensim \
        -c opensim-org -c conda-forge python=3.11 opensim=4.6 numpy=2.4 scipy
opensense_ik.py runs there (one subprocess per player) and writes results/<player>/opensense/.

Method:
- Model: OpenCap's scaled LaiUhlrich2022 for the 10/28 session (same model and joint ranges as the
  ground truth's IK; one model for both players). Pelvis translation and joints no sensor sees
  (left side, right knee and below) are locked; everything else is free within its clamped range.
- Ground: per Calibrate segment, the hold's body frame (x forward, y up, z right; OpenSim's
  convention), heading from the pocket phone at the segment's first frame (= the hold). Each
  virtual IMU (segment rotation, identity in the body frame at the hold) becomes
  R_ground_imu = B^T R_world_seg with B = phone_R at that frame; this replaces the Rx(-90 deg)
  world -> ground turn plus IMUPlacer's base heading. Written as orient_seg<k>.sto (quaternions).
- Calibration: IMUs placed directly on their bodies (no IMUPlacer) so that each IMU frame equals
  ground in the calibration pose = the hold: model default (standing, arms down, elbow 0) with
  pro_sup_r = 90 deg (palms facing the thighs; the model's 0 is palms forward).
- IK: OrientationsReference + InverseKinematicsSolver (what IMUInverseKinematicsTool runs), all
  weights 1, accuracy 1e-6, tracked frame to frame from the hold pose; a failed frame is invalid
  and the next is re-assembled.
- Variants: all four IMUs; no upper-arm IMU; Apple only (Watch on radius_r, phone on femur_r).
Outputs: hum / fore = torso^T (-y) of humerus_r / radius_r, elbow = elbow_flex_r, plus all
coordinates (degrees) as coords / coord_names.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np

from .common import OUT, angle_between, load, save
from .data import PLAYERS

OPENSIM_PY = Path.home() / "micromamba-envs/opensim/bin/python"
IK_SCRIPT = Path(__file__).resolve().parent / "opensense_ik.py"
VARIANTS = [
    "opensense_trunk_upper_watch_phone",
    "opensense_trunk_watch_phone",
    "opensense_watch_phone",
]
ARM = ["arm_flex_r", "arm_add_r", "arm_rot_r", "elbow_flex_r", "pro_sup_r"]


def unit(v):
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def save_player(p):
    d = load(p)
    ikn = list(d["ik_names"])
    for var in VARIANTS:
        z = np.load(OUT / p / "opensense" / f"ik_{var}.npz", allow_pickle=True)
        names = list(z["coord_names"])
        Rt, Rh, Rr = z["R_torso"], z["R_humerus"], z["R_radius"]
        hum = unit(np.einsum("nji,nj->ni", Rt, -Rh[:, :, 1]))
        fore = unit(np.einsum("nji,nj->ni", Rt, -Rr[:, :, 1]))
        valid = z["ok"] & np.isfinite(hum).all(1) & np.isfinite(fore).all(1)
        elbow = z["coords"][:, names.index("elbow_flex_r")]
        save(
            p,
            var,
            hum,
            fore,
            elbow=elbow,
            valid=valid,
            coords=z["coords"],
            coord_names=np.array(names),
        )
        m = valid & d["gt_valid"]
        # arm coordinates have +-10 rad ranges and can wind by 360 deg: compare wrapped
        errs = {
            c: np.median(
                np.abs(
                    (z["coords"][m, names.index(c)] - d["gt_ik"][m, ikn.index(c)] + 180) % 360 - 180
                )
            )
            for c in ARM
        }
        print(
            f"{p:6s} {var:36s} valid {valid.mean():.3f}  fore {np.median(angle_between(fore[m], d['gt_fore'][m])):5.1f}  "
            + "  ".join(f"{c} {e:5.1f}" for c, e in errs.items())
        )


def main():
    if "--save" not in sys.argv:
        procs = [subprocess.Popen([str(OPENSIM_PY), str(IK_SCRIPT), p]) for p in PLAYERS]
        if any(pr.wait() for pr in procs):
            raise SystemExit("OpenSense IK failed")
    for p in PLAYERS:
        save_player(p)


if __name__ == "__main__":
    main()
