# Contributing

How we work. Short version: **read the plan → implement on a branch → check → push, and update
the plan.** Commits use Conventional Commit messages; branches are squash-merged into `main`.

## One-time setup

```bash
python3 -m venv .venv-tools
.venv-tools/bin/pip install -r requirements-dev.txt
.venv-tools/bin/pre-commit install
tools/setup_upstream.sh
```

- `.venv-tools` holds only the commit-check tools. The ML environment stays in `code/.venv`
  (see `code/README.md`); don't install the tools there, it breaks `lightning`'s pins.
- `tools/setup_upstream.sh` clones MobilePoser and IMUCoCo at their pinned commits and applies
  `patches/`. Then download their licensed files (SMPL, weights, datasets) as their READMEs say.
- iOS app: `cd code/MotionStreamer && xcodegen generate`. The `.xcodeproj` is generated, not committed.

## Development loop

Every work session, by a person or by Claude, follows the same three steps.

```
 ① PLAN ─────────────────▶ ② IMPLEMENT ────────────────▶ ③ CHECK + PUSH
 read Status in             branch feat/stage-N-…          tools/check.sh
 docs/dev-plan.md           tests first, then code         update the one doc that owns
 pick the next task         small commits                  the topic; update Status
       ▲                                                   commit + push the branch
       └──────────────────── next session ◀──────────────────────────┘
```

### ① Plan: stay on track
1. `git switch main && git pull`, then open [`docs/dev-plan.md`](docs/dev-plan.md#status) **Status**.
2. Take the **Next action**. If it isn't in the current stage's task list, stop and update the plan
   first: new work goes into a stage (or [`docs/decisions.md`](docs/decisions.md) if it's a decision).
3. Branch: `feat/stage-N-<name>` (or `fix/…`, `docs/…`, `test/…`, `exp/…`, `chore/…`).

### ② Implement
1. Write the stage's tests first (IDs from [`docs/test-plan.md`](docs/test-plan.md)); watch them fail.
2. Write the code until they pass. Commit small, each commit building and passing checks.
3. Stay inside the current stage. Anything else you notice goes into the plan as a task, not into
   this branch.

### ③ Check, tidy, push
1. Run **`tools/check.sh`** (all pre-commit checks + tests). Fix everything it reports.
2. Docs stay short: change the **one file that owns the topic** (see the table in
   [`README.md`](README.md)); delete text that's no longer true instead of adding notes about it.
3. Update **Status** in `docs/dev-plan.md` (stage, next action, blockers, date) and tick finished
   goals. Log experiments and device tests in `EXPERIMENT_LOG.md` with the commit hash.
4. Commit and **push the branch at the end of every session**, even mid-stage, so nothing lives
   only on one laptop.
5. When the stage's gate passes twice in a row: open a pull request (template), the other person
   reviews, **squash-merge**, delete the branch.

`main` is protected by a local hook (`no-commit-to-branch`); GitHub's server-side protection isn't
available for private repos on the free plan.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), checked on every commit:

```
<type>(<optional scope>): <what changed, imperative, ≤ 72 chars>

<optional body: why, and anything a reviewer must know>
```

| Type | For |
|---|---|
| `feat` | New behaviour (app, pipeline) |
| `fix` | Bug fix |
| `docs` | Docs only |
| `test` | Tests only |
| `refactor` | Same behaviour, cleaner code |
| `perf` | Faster or lighter |
| `build` / `ci` | Build setup, XcodeGen, GitHub Actions |
| `chore` | Tooling, dependencies |
| `exp` | Experiment scripts and their logged results |
| `data` | Annotations, data-format specs (never the data itself) |

Scopes we use: `app`, `watch`, `recorder`, `ingest`, `live`, `experiments`, `design`.
Examples: `feat(recorder): rotate chunk files every 60 s` · `fix(app): reset calibration timer on Stop`.

No AI co-author lines or "Generated with" footers in commits or pull requests.

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
| message | Conventional Commit format |

If a hook changes files, review the change, `git add` it and commit again.
GitHub Actions runs the same checks on every pull request (Swift checks run locally only).

## Code standards

- **Python:** ruff + ruff-format settings in `pyproject.toml`; target Python 3.9 (the ML env).
  Type hints on new functions. Scripts take paths as arguments; no hard-coded user paths.
- **Swift:** `.swift-format` (4 spaces, 120 chars). New logic goes into testable code behind the
  protocols in [`docs/test-plan.md`](docs/test-plan.md) §0, not into views.
- **Comments** explain *why*, not *what*. Keep the existing doc-comment style.
- **Tests:** IDs from [`docs/test-plan.md`](docs/test-plan.md); name tests after them
  (e.g. `test_R3_chunk_close`). A stage's gate must pass before the next stage starts.

## What goes in git, and what doesn't

| In git | Not in git (shared drive) |
|---|---|
| Code, configs, docs, design and test plans | `code/recordings/` (personal motion data) |
| Small results: `results/**/*.md`, `*.json` | Videos, plots' raw arrays (`.npz`), model outputs |
| Annotations (`experiments/annotations/`) | MobilePoser / IMUCoCo repos, SMPL, weights, datasets |
| Patches to upstream repos (`patches/`) | Virtual environments, Xcode build output |

- Recordings use participant codes (`P01`), never names.
- Never commit secrets, Apple signing files or API keys.

## Upstream model repos

Edit the code in `code/MobilePoser`, then refresh the patch:
`git -C code/MobilePoser -c core.fileMode=false diff > patches/mobileposer.patch`.
