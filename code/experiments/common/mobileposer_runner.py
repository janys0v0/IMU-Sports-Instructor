"""Run MobilePoser (offline) on a chosen subset of a session's devices.

Devices left out get zero inputs, which is how MobilePoser masks missing devices in training.
MobilePoser was trained only on the device combinations in mobileposer.config.amass.combos
(every one includes a pocket phone); `is_trained_combo` tells an experiment which ones are.
"""

import os
from dataclasses import dataclass

import numpy as np
from replay import model_input  # noqa: E402  (live/)

from . import paths
from .session import SHORT, SLOTS, Session


@dataclass
class Output:
    t: np.ndarray  # (n,) seconds after Start
    pose: np.ndarray  # (n, 24, 3, 3) local joint rotations
    glb: np.ndarray  # (n, 24, 3, 3) global joint rotations
    joints: np.ndarray  # (n, 24, 3) joint positions, root at origin
    tran: np.ndarray  # (n, 3) root translation


_model = None


def model():
    global _model
    if _model is None:
        os.chdir(
            paths.MOBILEPOSER_DIR
        )  # MobilePoser resolves weights/SMPL relative to the working directory
        import torch

        torch.set_num_threads(4)
        from mobileposer.config import paths as mp_paths
        from mobileposer.utils.model_utils import load_model

        _model = load_model(mp_paths.weights_file).eval()
    return _model


def combo_name(locs):
    order = ["lw", "rw", "lp", "rp", "h"]
    return "_".join(sorted((SHORT[l] for l in locs), key=order.index))


def is_trained_combo(locs):
    from mobileposer.config import amass

    model()  # makes the mobileposer package importable from its directory
    return combo_name(locs) in amass.combos


def run(session: Session, locs) -> Output:
    """MobilePoser on the given device locations, segment by segment, joined in time."""
    import torch

    m = model()
    parts = []
    for seg in session.segments:
        missing = [l for l in locs if l not in seg.devices]
        if missing:
            raise ValueError(f"{session.name}: {missing} not calibrated in every segment")
        first, *rest = locs
        d0 = seg.devices[first]
        x = model_input(
            d0.acc,
            d0.ori,
            SLOTS[first],
            [(seg.devices[l].acc, seg.devices[l].ori, SLOTS[l]) for l in rest],
        )
        m.reset()
        with torch.no_grad():
            pose, _, tran, _ = m.forward_offline(torch.from_numpy(x).float().unsqueeze(0), [len(x)])
        pose = pose.view(-1, 24, 3, 3).cpu()
        glb, joints = m.bodymodel.forward_kinematics(pose)[:2]
        parts.append(
            Output(seg.t, pose.numpy(), glb.numpy(), joints.numpy(), tran.view(-1, 3).cpu().numpy())
        )
    return Output(
        *(np.concatenate([getattr(p, f) for p in parts]) for f in Output.__dataclass_fields__)
    )


def body_model():
    return model().bodymodel
