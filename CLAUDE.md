# Instructions for Claude

Follow the development loop in [`CONTRIBUTING.md`](CONTRIBUTING.md#development-loop) every session:

1. **Plan:** read Status in [`docs/plan/dev-plan.md`](docs/plan/dev-plan.md#status) first. Work only on the
   current stage's next action; put anything else into the plan instead of doing it.
2. **Implement** on a `feat/stage-N-<desc>` branch, tests first.
3. **Check and push:** run `tools/check.sh`, update the one doc that owns the topic (map in
   [`README.md`](README.md)), update Status, commit, push the branch.

Rules:
- Branches, commits and PRs follow [`CONTRIBUTING.md`](CONTRIBUTING.md#commit-branch-and-pr-format) (checked by `tools/check_format.py`). **No AI co-author lines or "Generated with" footers.**
- Never commit on `main`; never commit recordings, videos, weights or SMPL files.
- Keep docs short: edit or delete stale text instead of appending notes. Decisions go in
  [`docs/plan/decisions.md`](docs/plan/decisions.md), device facts in [`docs/research/device-research.md`](docs/research/device-research.md).
- Python tools for checks live in `.venv-tools`; the ML environment is `.venv` (Python 3.9). Run Python as `.venv/bin/python -m pipeline.…` / `-m experiments.…` from the repo root.
- Device tests in the background run with Xcode detached ([`docs/plan/test-plan.md`](docs/plan/test-plan.md) §4).
