"""OpenSense IMU inverse kinematics for one player. Runs in the OpenSim env, not .venv:

    ~/micromamba-envs/opensim/bin/python experiments/E07_pose_methods/opensense_ik.py <player>

Called by opensense.py (see there for the method). Standalone on purpose: no package imports, so
it runs under Python 3.11 + opensim 4.6. Writes results/<player>/opensense/:
    orient_seg<k>.sto            OpenSense orientations (quaternions, ground frame, t - t0)
    model_imu.osim               the OpenCap scaled model with the IMU frames placed
    ik_<variant>.mot             IK coordinates (degrees), all segments
    ik_<variant>.npz             coords, coord_names, R_torso/R_humerus/R_radius (ground), ok
"""

import sys
from pathlib import Path

import numpy as np
import opensim as osim
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[2]
RES = Path(__file__).resolve().parent / "results"
MODEL = ROOT / (
    "data/external/20261028/opencap/OpenCapData_d94b2489-31c0-44f0-8f3f-8eab9f3dcce0/"
    "OpenSimData/Model/LaiUhlrich2022_scaled.osim"
)

# virtual IMU -> (aligned.npz key, model body)
IMUS = {
    "torso_imu": ("trunk_R", "torso"),
    "humerus_r_imu": ("upper_R", "humerus_r"),
    "radius_r_imu": ("watch_R", "radius_r"),
    "femur_r_imu": ("phone_R", "femur_r"),
}
VARIANTS = {
    "opensense_trunk_upper_watch_phone": [
        "torso_imu",
        "humerus_r_imu",
        "radius_r_imu",
        "femur_r_imu",
    ],
    "opensense_trunk_watch_phone": ["torso_imu", "radius_r_imu", "femur_r_imu"],
    "opensense_watch_phone": ["radius_r_imu", "femur_r_imu"],
}
# Right arm only: pelvis, right hip and lumbar locked too, so the torso stays in the hold pose and
# only the shoulder (3), elbow and pronation are solved (5 DOF). "trunk" variants feed the arm
# sensors relative to the chest sensor (R_trunk^T R), i.e. ground = the moving trunk frame.
ARM_VARIANTS = {
    "opensense_arm_watch": (["radius_r_imu"], False),
    "opensense_arm_upper_watch": (["humerus_r_imu", "radius_r_imu"], False),
    "opensense_arm_trunk_watch": (["radius_r_imu"], True),
    "opensense_arm_trunk_upper_watch": (["humerus_r_imu", "radius_r_imu"], True),
}
LOCK_ARM_ONLY = ["pelvis_tilt", "pelvis_list", "pelvis_rotation", "hip_flexion_r",
                 "hip_adduction_r", "hip_rotation_r", "lumbar_extension", "lumbar_bending",
                 "lumbar_rotation"]  # fmt: skip
# Calibration pose = the Calibrate hold: standing, arms hanging, palms facing the thighs.
# Model default (all 0) is the anatomical pose (palms forward); neutral forearm is pro_sup = 90 deg.
CAL_POSE_DEG = {"pro_sup_r": 90.0, "pro_sup_l": 90.0}
# Coordinates no sensor can see (and pelvis translation, which orientations cannot fix): locked.
LOCK = [
    "pelvis_tx",
    "pelvis_ty",
    "pelvis_tz",
    "knee_angle_r",
    "ankle_angle_r",
    "subtalar_angle_r",
    "mtp_angle_r",
    "hip_flexion_l",
    "hip_adduction_l",
    "hip_rotation_l",
    "knee_angle_l",
    "ankle_angle_l",
    "subtalar_angle_l",
    "mtp_angle_l",
    "arm_flex_l",
    "arm_add_l",
    "arm_rot_l",
    "elbow_flex_l",
    "pro_sup_l",
]


def mat(R):
    return np.array([[R.get(i, j) for j in range(3)] for i in range(3)])


def set_pose(model, s, pose_deg):
    cs = model.getCoordinateSet()
    for i in range(cs.getSize()):
        c = cs.get(i)
        if c.getName().endswith("_beta"):
            continue
        v = pose_deg.get(
            c.getName(),
            np.degrees(c.getDefaultValue()) if c.getMotionType() == 1 else c.getDefaultValue(),
        )
        c.setValue(s, np.radians(v) if c.getMotionType() == 1 else v, False)
    model.assemble(s)


def place_imus(out):
    """Model with each IMU frame fixed on its body so that, in the calibration pose, the IMU frame
    is aligned with ground (= the hold's body frame, the virtual IMUs' definition)."""
    model = osim.Model(str(MODEL))
    s = model.initSystem()
    set_pose(model, s, CAL_POSE_DEG)
    model.realizePosition(s)
    for name, (_, body) in IMUS.items():
        b = model.getBodySet().get(body)
        R_gb = mat(b.getTransformInGround(s).R())
        R_bi = R_gb.T  # body <- imu, with R_g_imu = I at calibration
        rot = osim.Rotation(osim.Mat33(*R_bi.ravel()))
        f = osim.PhysicalOffsetFrame(name, b, osim.Transform(rot, osim.Vec3(0)))
        b.addComponent(f)
    model.finalizeConnections()
    model.printToXML(str(out))
    return out


def write_sto(path, t, quats, labels):
    """quats: dict label -> (n, 4) [w, x, y, z]."""
    with open(path, "w") as f:
        f.write(
            "DataRate=30.000000\nDataType=Quaternion\nversion=3\nOpenSimVersion=4.6\nendheader\n"
        )
        f.write("time\t" + "\t".join(labels) + "\n")
        for i, ti in enumerate(t):
            f.write(
                f"{ti:.6f}\t"
                + "\t".join(",".join(f"{v:.8f}" for v in quats[l][i]) for l in labels)
                + "\n"
            )
    table = osim.TimeSeriesTableQuaternion(str(path))
    return table


def run_ik(model_path, table, labels, t, extra_lock=()):
    model = osim.Model(str(model_path))
    s = model.initSystem()
    cs = model.getCoordinateSet()
    set_pose(model, s, CAL_POSE_DEG)
    for n in [*LOCK, *extra_lock]:
        cs.get(n).setLocked(s, True)

    sub = osim.TimeSeriesTableQuaternion(table)
    for l in list(sub.getColumnLabels()):
        if l not in labels:
            sub.removeColumn(l)
    weights = osim.OrientationWeightSet()
    for l in labels:
        weights.cloneAndAppend(osim.OrientationWeight(l, 1.0))
    rot_table = osim.OpenSenseUtilities.convertQuaternionsToRotations(sub)
    oref = osim.OrientationsReference(rot_table, weights)
    solver = osim.InverseKinematicsSolver(
        model, osim.MarkersReference(), oref, osim.SimTKArrayCoordinateReference()
    )
    solver.setAccuracy(1e-6)

    t = np.array(rot_table.getIndependentColumn())  # exact keys the reference looks up
    names = [cs.get(i).getName() for i in range(cs.getSize())]
    rot = [cs.get(i).getMotionType() == 1 for i in range(cs.getSize())]
    bodies = {b: model.getBodySet().get(b) for b in ("torso", "humerus_r", "radius_r")}
    n = len(t)
    coords = np.full((n, len(names)), np.nan)
    Rs = {b: np.full((n, 3, 3), np.nan) for b in bodies}
    ok = np.zeros(n, bool)
    s.setTime(float(t[0]))
    solver.assemble(s)
    need_assemble = False
    for i, ti in enumerate(t):
        s.setTime(float(ti))
        try:
            if need_assemble:
                solver.assemble(s)
                need_assemble = False
            else:
                solver.track(s)
        except Exception as e:  # noqa: BLE001
            print(f"  IK failed at t={ti:.2f}: {str(e)[:80]}")
            need_assemble = True
            continue
        model.realizePosition(s)
        coords[i] = [
            np.degrees(cs.get(j).getValue(s)) if rot[j] else cs.get(j).getValue(s)
            for j in range(len(names))
        ]
        for b, body in bodies.items():
            Rs[b][i] = mat(body.getTransformInGround(s).R())
        ok[i] = True
    return names, coords, Rs, ok


def write_mot(path, t, names, coords):
    with open(path, "w") as f:
        f.write(
            f"Coordinates\nversion=1\nnRows={len(t)}\nnColumns={len(names) + 1}\ninDegrees=yes\nendheader\n"
        )
        f.write("time\t" + "\t".join(names) + "\n")
        for ti, row in zip(t, coords):
            f.write(f"{ti:.4f}\t" + "\t".join(f"{v:.5f}" for v in row) + "\n")


def main(player):
    out = RES / player / "opensense"
    out.mkdir(parents=True, exist_ok=True)
    d = np.load(RES / player / "dataset.npz", allow_pickle=True)
    a = np.load(RES / player / "aligned.npz", allow_pickle=True)
    t_all, seg = d["t"], d["seg"]
    model_path = place_imus(out / "model_imu.osim")
    n = len(t_all)
    results = {}
    for k in np.unique(seg):
        idx = np.where(seg == k)[0]
        t = t_all[idx] - t_all[idx[0]]
        # ground for this segment: the hold's body frame (x forward, y up, z right); its heading is
        # the pocket phone's at the segment's first frame (= the hold; phone_R there is pure heading)
        B = a["phone_R"][idx[0]]
        quats = {}
        for name, (key, _) in IMUS.items():
            R = np.einsum("ij,njk->nik", B.T, a[key][idx])  # world<-seg -> hold body frame<-seg
            q = Rotation.from_matrix(R).as_quat()  # x, y, z, w
            quats[name] = np.c_[q[:, 3], q[:, :3]]
        labels = list(IMUS)
        table = write_sto(out / f"orient_seg{k}.sto", t, quats, labels)
        runs = [(var, used, (), table) for var, used in VARIANTS.items()]
        if ARM_VARIANTS:
            rel = {}  # arm sensors relative to the chest sensor (identity at the hold)
            for name, (key, _) in IMUS.items():
                if key in a.files and "trunk_R" in a.files:
                    R = np.einsum("nji,njk->nik", a["trunk_R"][idx], a[key][idx])
                    q = Rotation.from_matrix(R).as_quat()
                    rel[name] = np.c_[q[:, 3], q[:, :3]]
            table_rel = (write_sto(out / f"orient_rel_seg{k}.sto", t, rel, list(rel))
                         if rel else None)  # fmt: skip
            for var, (used, trunk_rel) in ARM_VARIANTS.items():
                if all(u in quats for u in used) and (not trunk_rel or table_rel is not None):
                    runs.append((var, used, LOCK_ARM_ONLY, table_rel if trunk_rel else table))
        for var, used, lock, tab in runs:
            print(f"{player} seg {k} {var}: {len(idx)} frames")
            names, coords, Rs, ok = run_ik(model_path, tab, used, t, lock)
            r = results.setdefault(
                var,
                {
                    "coords": np.full((n, len(names)), np.nan),
                    "names": names,
                    "ok": np.zeros(n, bool),
                    **{f"R_{b}": np.full((n, 3, 3), np.nan) for b in Rs},
                },
            )
            r["coords"][idx], r["ok"][idx] = coords, ok
            for b in Rs:
                r[f"R_{b}"][idx] = Rs[b]
    for var, r in results.items():
        write_mot(out / f"ik_{var}.mot", t_all - t_all[0], r["names"], r["coords"])
        np.savez_compressed(
            out / f"ik_{var}.npz",
            coords=r["coords"],
            coord_names=np.array(r["names"]),
            ok=r["ok"],
            R_torso=r["R_torso"],
            R_humerus=r["R_humerus_r"],
            R_radius=r["R_radius_r"],
        )
        print(var, "ok frames", r["ok"].mean())


if __name__ == "__main__" and "--arm-only" in sys.argv:
    VARIANTS = {}  # noqa: F811 - only the right-arm-only variants
if __name__ == "__main__":
    main(sys.argv[1])
