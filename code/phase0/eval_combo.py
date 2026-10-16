"""Evaluate MobilePoser on one device combination (no model code changes).

Run from MobilePoser/mobileposer/:
    python ../../phase0/eval_combo.py --combo lw_rp --dataset imuposer
"""

from argparse import ArgumentParser

import mobileposer.data as data_mod
from evaluate import evaluate_pose
from mobileposer.config import amass
from mobileposer.utils.model_utils import load_model

parser = ArgumentParser()
parser.add_argument("--model", default="checkpoints/weights.pth")
parser.add_argument("--dataset", default="imuposer")
parser.add_argument("--combo", default="lw_rp", choices=list(amass.combos))
args = parser.parse_args()

# Restrict the dataset to a single device combination.
amass.combos = {args.combo: amass.combos[args.combo]}

model = load_model(args.model)
dataset = data_mod.PoseDataset(fold="test", evaluate=args.dataset)
print(f"Evaluation: {args.dataset}, combo {args.combo}, {len(dataset)} sequences")
evaluate_pose(model, dataset, evaluate_tran=True)
