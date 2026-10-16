# Instructions for Claude

Follow the development loop in [`CONTRIBUTING.md`](CONTRIBUTING.md#development-loop) every session:

1. **Plan:** read Status in [`docs/dev-plan.md`](docs/dev-plan.md#status) first. Work only on the
   current stage's next action; put anything else into the plan instead of doing it.
2. **Implement** on a `feat/stage-N-<name>` branch, tests first.
3. **Check and push:** run `tools/check.sh`, update the one doc that owns the topic (map in
   [`README.md`](README.md)), update Status, commit, push the branch.

Rules:
- Commit messages: Conventional Commits. **No AI co-author lines or "Generated with" footers.**
- Never commit on `main`; never commit recordings, videos, weights or SMPL files.
- Keep docs short: edit or delete stale text instead of appending notes. Decisions go in
  [`docs/decisions.md`](docs/decisions.md), device facts in [`docs/device-research.md`](docs/device-research.md).
- Python tools for checks live in `.venv-tools`; the ML environment is `code/.venv` (Python 3.9).
- Device tests in the background run with Xcode detached ([`docs/test-plan.md`](docs/test-plan.md) §4).
