# Contributing

How we work. Short version: **read the plan → implement on a branch → check → push, and update
the plan.** Branches, commits and pull requests share one [format](#commit-branch-and-pr-format);
pull requests are squash-merged into `main`.

## One-time setup

```bash
python3 -m venv .venv-tools
.venv-tools/bin/pip install -r requirements-dev.txt
.venv-tools/bin/pre-commit install
git config commit.template .gitmessage   # prefilled commit message
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # ML environment
tools/setup_third_party.sh
```

- `.venv-tools` holds only the commit-check tools; `.venv` is the ML environment (Python 3.9).
  Don't install the tools into `.venv`: it breaks `lightning`'s pins.
- `tools/setup_third_party.sh` clones MobilePoser and IMUCoCo into `third_party/` at their pinned
  commits and applies `third_party/patches/`. Then download their licensed files (SMPL, weights,
  datasets) as [`third_party/README.md`](third_party/README.md) says.
- iOS app: `cd apps/MotionStreamer && xcodegen generate`. The `.xcodeproj` is generated, not committed.

## Development loop

Every work session, by a person or by Claude, follows the same three steps.

```
 ① PLAN ─────────────────▶ ② IMPLEMENT ────────────────▶ ③ CHECK + PUSH
 read Status in             branch feat/stage-N-…          tools/check.sh
 docs/plan/dev-plan.md           tests first, then code         update the one doc that owns
 pick the next task         small commits                  the topic; update Status
       ▲                                                   commit + push the branch
       └──────────────────── next session ◀──────────────────────────┘
```

### ① Plan: stay on track
1. `git switch main && git pull`, then open [`docs/plan/dev-plan.md`](docs/plan/dev-plan.md#status) **Status**.
2. Take the **Next action**. If it isn't in the current stage's task list, stop and update the plan
   first: new work goes into a stage (or [`docs/plan/decisions.md`](docs/plan/decisions.md) if it's a decision).
3. Branch: `feat/stage-N-<desc>` for stage work, otherwise `<type>/<desc>` ([format](#commit-branch-and-pr-format)).

### ② Implement
1. Write the stage's tests first (IDs from [`docs/plan/test-plan.md`](docs/plan/test-plan.md)); watch them fail.
2. Write the code until they pass. Commit small, each commit building and passing checks.
3. Stay inside the current stage. Anything else you notice goes into the plan as a task, not into
   this branch.

### ③ Check, tidy, push
1. Run **`tools/check.sh`** (all pre-commit checks + tests). Fix everything it reports.
2. Docs stay short: change the **one file that owns the topic** (see the table in
   [`README.md`](README.md)); delete text that's no longer true instead of adding notes about it.
3. Update **Status** in `docs/plan/dev-plan.md` (stage, next action, blockers, date) and tick finished
   goals. Log experiments and device tests in `EXPERIMENT_LOG.md` with the commit hash.
4. Commit and **push the branch at the end of every session**, even mid-stage, so nothing lives
   only on one laptop.
5. When the stage's gate passes twice in a row: open a pull request (template), the other person
   reviews, **squash-merge**, delete the branch.

`main` is protected by a local hook (`no-commit-to-branch`); GitHub's server-side protection isn't
available for private repos on the free plan.

## Commit, branch and PR format

One vocabulary for every name, so a branch, its commits and its pull request read the same way.
`tools/check_format.py` is the only place the rules are encoded.

| Word | Values |
|---|---|
| **type** | `feat` new behaviour · `fix` bug fix · `refactor` same behaviour, cleaner · `perf` faster or lighter · `test` tests only · `docs` docs only · `exp` experiment · `data` annotations or formats · `build` build setup · `ci` GitHub Actions · `chore` tooling or dependencies |
| **scope** (optional) | `app` `watch` `recorder` `ingest` `preprocessing` `pose` `live` `analysis` `experiments` `design` `plan` `tools` `deps` `third-party` |
| **desc** | lowercase, imperative, no final period |

| Thing | Format | Example |
|---|---|---|
| Branch | `<type>/<kebab-desc>`, ≤ 40 chars; stage work starts with `stage-N-` | `feat/stage-1-phone-recorder` · `fix/calibration-timer` |
| Throwaway branch | `spike/<kebab-desc>`; never merged, no pull request | `spike/background-check` |
| Commit subject | `<type>(<scope>): <desc>`, ≤ 72 chars | `feat(recorder): rotate chunk files every 60 s` |
| Commit body (optional) | Blank line, then *why* in plain sentences, wrapped at 72 | `Power-off lost buffered data; fsync limits loss to 1 s.` |
| PR title | Same as a commit subject, **same type as its branch** | `feat(recorder): save sessions as 60 s chunks with a journal` |
| PR description | Sections **Why · What changed · How it was checked · Plan** (the template) | — |
| Commit on `main` | Squash merge: PR title → subject, PR description → body | one commit per PR |

Never: AI co-author lines, "Generated with" footers, or commits directly on `main`.

**Enforced by:** the `commit-msg` and branch-name hooks on every commit; GitHub Actions on every
pull request (branch, title, description, and that the title's type matches the branch's).
`git commit` opens `.gitmessage` as a prefilled template.

## Checks on every commit

`pre-commit` runs these automatically on the files you commit. Run on everything with
`.venv-tools/bin/pre-commit run --all-files`.

| Check | What it does |
|---|---|
| ruff | Python lint (imports, bugs, modern syntax), auto-fixes safe issues |
| ruff-format | Python formatting (100-char lines) |
| swift-format | Swift formatting + strict lint, using Xcode's built-in `swift-format` (`.swift-format`) |
| hygiene | Trailing spaces, final newline, LF line endings, valid YAML/JSON/TOML, merge markers |
| large files | Blocks any file > 1 MB |
| no data files | Blocks recordings, videos, `.npz`, weights, `.pkl`, `.jsonl`, `.bin` |
| doc links | Every local link and `#heading` in Markdown must exist |
| private keys | Blocks committed keys |
| branch | Blocks commits directly on `main` |
| branch / message | Branch name and commit message follow the format above |

If a hook changes files, review the change, `git add` it and commit again.
GitHub Actions runs the same checks on every pull request (Swift checks run locally only).

## Code standards

- **Python:** ruff + ruff-format settings in `pyproject.toml`; target Python 3.9 (the ML env).
  Type hints on new functions. Scripts take paths as arguments; no hard-coded user paths.
- **Swift:** `.swift-format` (4 spaces, 120 chars). New logic goes into testable code behind the
  protocols in [`docs/plan/test-plan.md`](docs/plan/test-plan.md) §0, not into views.
- **Comments** explain *why*, not *what*. Keep the existing doc-comment style.
- **Tests:** IDs from [`docs/plan/test-plan.md`](docs/plan/test-plan.md); name tests after them
  (e.g. `test_R3_chunk_close`). A stage's gate must pass before the next stage starts.

## What goes in git, and what doesn't

| In git | Not in git (shared drive) |
|---|---|
| Code, configs, docs, design and test plans | `data/` (recordings: personal motion data) |
| Small results: `results/**/*.md`, `*.json` | Videos, plots' raw arrays (`.npz`), model outputs |
| Annotations (`experiments/annotations/`) | MobilePoser / IMUCoCo repos, SMPL, weights, datasets |
| Patches to third-party repos (`third_party/patches/`) | Virtual environments, Xcode build output |

- Recordings use participant codes (`P01`), never names.
- Never commit secrets, Apple signing files or API keys.

## Where new code goes

| Kind of code | Folder |
|---|---|
| iPhone / Watch app | `apps/MotionStreamer/` |
| Loading, resampling, calibrating recordings | `pipeline/preprocessing/` |
| Running models, rendering | `pipeline/pose/` |
| Checking and merging field sessions (`ingest_field.py`) | `pipeline/ingest/` |
| Anything that talks UDP to the app | `pipeline/live/` |
| Plots and metrics on one recording | `pipeline/analysis/` |
| A study with a question and results | `experiments/ENN_name/` (see [`experiments/README.md`](experiments/README.md)) |
| Developer scripts | `tools/` |
| Changes to MobilePoser / IMUCoCo | edit in `third_party/`, then refresh the patch ([`third_party/README.md`](third_party/README.md)) |
