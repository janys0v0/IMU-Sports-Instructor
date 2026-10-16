"""Run IMUCoCo (Zhou et al., UIST 2025; code/IMUCoCo) offline on a session's calibrated devices.

Mirrors start_inference() in code/IMUCoCo/live_demo.py, without the viewer or network:
- each device is placed on the zero-pose SMPL mesh at the vertex MobilePoser's virtual sensors use
  (mobileposer/process.py vi_mask), so both models see the same placements;
- inputs per frame and device: bone orientation (6D) + acceleration (m/s^2) in the SMPL body
  frame, at 60 Hz (IMUCoCo's training rate; acc = finite differences * 3600 in data_generation.py);
- the joint-feature model (IMUCoCo) runs frame by frame into the DTP poser, as in the live demo.
Output is downsampled to 30 Hz so it lines up with MobilePoser's frames.

Weights (code/IMUCoCo/saved_checkpoints/, from the links in the IMUCoCo README) are loaded with
weights_only=True: tensors only, no code in the files is executed.
"""

import os
import sys

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from common import paths  # noqa: E402
from common.mobileposer_runner import Output  # noqa: E402

IMUCOCO_DIR = paths.CODE / "IMUCoCo"
RATE = 60
# Virtual-sensor vertices from MobilePoser (process.py vi_mask): lw, rw, lp, rp, head.
SENSOR_VERTEX = {
    "left_wrist": 1961,
    "right_wrist": 5424,
    "left_pocket": 876,
    "right_pocket": 4362,
    "head": 411,
}

_models = None


def _load():
    """Build IMUCoCo + poser as live_demo.start_inference() does. Imports need its working directory."""
    global _models
    if _models is not None:
        return _models
    cwd = os.getcwd()
    os.chdir(IMUCOCO_DIR)  # imu_config loads smpl/SMPL_MALE.pkl; path_config paths are relative
    sys.path.insert(0, str(IMUCOCO_DIR))
    import path_config
    import torch
    from models.dtp import Poser
    from models.imucoco import IMUCoCo
    from utils import imu_config

    vertex_cat = torch.tensor(imu_config.vertex_coordinates_with_category).float()
    joint_cat = torch.tensor(imu_config.joint_coordinates_with_category).float()
    cmax, cmin = vertex_cat[:, 1:].max(dim=0).values, vertex_cat[:, 1:].min(dim=0).values
    coco = IMUCoCo(
        coordinate_origins=joint_cat,
        coordinate_max=cmax,
        coordinate_min=cmin,
        smpl_mesh_coordinates=vertex_cat,
        n_hidden=128,
        n_kr_hidden=32,
        n_mfe_layers=2,
        n_jnm_layers=3,
        n_sce_freq=4,
        n_sce_emb=40,
        online_mode=True,
        joint_node_allocation_map=path_config.saved_imucoco_loss_map_path,
        joint_node_max_err_tolerance=-1,
    )
    poser = Poser(
        joint_feature_dim=128,
        n_hidden=300,
        n_glb=40,
        num_layer=3,
        n_total_devices=24,
        load_tran_module=True,
    )
    coco.load_offline_state_dict_to_online_model(
        torch.load(path_config.saved_imucoco_checkpoint_path, map_location="cpu", weights_only=True)
    )
    poser.load_state_dict(
        torch.load(path_config.saved_hpe_checkpoint_path, map_location="cpu", weights_only=True),
        strict=False,
    )
    coco.eval()
    poser.eval()
    coco.prepare_parallel_sce_implementation()
    coco.prepare_parallel_joint_node_implementation()
    _, zero_verts = imu_config.body_model.get_zero_pose_joint_and_vertex()
    os.chdir(cwd)
    _models = (coco, poser, imu_config.body_model, zero_verts)
    return _models


def run(session, locs) -> Output:
    """IMUCoCo on the given device locations of a session loaded at 60 Hz (load_session(..., rate=60))."""
    import torch

    coco, poser, body, zero_verts = _load()
    coco.set_current_device_coordinates(
        torch.stack([zero_verts[SENSOR_VERTEX[l]] for l in locs]).float()
    )
    coco.buffer_placement_codes_with_current_devices(parallel=True)
    t_pose_r6d = torch.eye(3).expand(24, 3, 3).unsqueeze(0)[:, :, :, :2].transpose(2, 3).flatten(2)
    parts = []
    for seg in session.segments:
        ori = torch.from_numpy(
            np.stack([seg.devices[l].ori for l in locs], 1)
        ).float()  # (T, D, 3, 3)
        acc = torch.from_numpy(np.stack([seg.devices[l].acc for l in locs], 1)).float()  # (T, D, 3)
        imu = torch.cat([ori[..., :2].transpose(-1, -2).flatten(-2), acc], dim=-1)  # (T, D, 9)
        h_mfe = h_jnm = tran = None
        h_pose = poser.init_hidden_states(v_init=torch.zeros(1, 24, 3), glb_init=t_pose_r6d)
        poses, trans = [], []
        with torch.no_grad():
            for k in range(len(imu)):
                feat, h_mfe, h_jnm = coco.inference_time_forward_mesh_online(
                    imu[k : k + 1].unsqueeze(0), h_mfe, h_jnm
                )
                pose, _, tran, h_pose = poser.forward_online(
                    feat, h_pose, current_tran=tran, compute_tran="transpose"
                )
                poses.append(pose[0, -1])
                trans.append(tran.reshape(-1, 3)[-1])
        pose = torch.stack(poses)[::2]  # 60 -> 30 Hz on the same time grid
        tran = torch.stack(trans)[::2]
        glb, joints = body.forward_kinematics(pose)[:2]
        parts.append(Output(seg.t[::2], pose.numpy(), glb.numpy(), joints.numpy(), tran.numpy()))
    return Output(
        *(np.concatenate([getattr(p, f) for p in parts]) for f in Output.__dataclass_fields__)
    )
