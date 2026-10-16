# Third-party models

Upstream model repos used by `pipeline/` and `experiments/`. They are **not in git**:
`tools/setup_third_party.sh` clones each at its pinned commit and applies `patches/`.

| Repo | Pinned commit | Patch | Used by |
|---|---|---|---|
| [MobilePoser](https://github.com/SPICExLAB/MobilePoser) (UIST 2024) | `513e76a` | `patches/mobileposer.patch` | `pipeline/pose/`, experiments E00-E03 |
| [IMUCoCo](https://github.com/cmusmashlab/IMUCoCo) (UIST 2025) | `d7dd17c` | — | experiment E02 |

## Licensed files (download by hand)

Their licenses don't allow redistribution, so each machine downloads them once.

**MobilePoser** (paths relative to `MobilePoser/mobileposer/`, its working directory):
- `smpl/basicmodel_m.pkl`: SMPL male model (register at smpl.is.tue.mpg.de)
- `checkpoints/weights.pth`: pretrained weights, from the MobilePoser README
- `data/raw/IMUPoser/P1..P10`: IMUPoser dataset, only for experiment E00
- Install: `.venv/bin/pip install -e third_party/MobilePoser --config-settings editable_mode=compat`
  (install notes: [`experiments/E00_mobileposer_reproduction/README.md`](../experiments/E00_mobileposer_reproduction/README.md))

**IMUCoCo** (paths relative to `IMUCoCo/`):
- `saved_checkpoints/`: `imucoco_best.pth`, `poser_dtp_best.pth`, `all_error_loss_map.pth`, from
  `https://synergylabs.org/haozhe/<file>`
- `smpl/SMPL_MALE.pkl`: symlink to `../../MobilePoser/mobileposer/smpl/basicmodel_m.pkl`

## Changing a third-party repo

Edit the code in `third_party/MobilePoser`, then refresh the patch:

```bash
git -C third_party/MobilePoser -c core.fileMode=false diff > third_party/patches/mobileposer.patch
```

Our current MobilePoser changes: a local IMUPoser dataset path, resetting the velocity RNN and
foot positions between sequences, and applying sigmoid to contact logits as the offline path does.
