# Contributing

How we keep this repo clean and consistent. Short version: **branch → small commits with
Conventional Commit messages → checks pass → pull request → squash-merge into `main`.**

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

## Workflow

```
 main ──●────────────────●────────────────●──▶   always works; never commit to it directly
         \              / squash-merge   /
          ●──●──●──●───●  feat/watch-chunks
```

1. **Branch from `main`:** `feat/…`, `fix/…`, `docs/…`, `test/…`, `exp/…` (experiments), `chore/…`.
2. **Commit small and often.** Each commit builds and passes the checks.
3. **Open a pull request.** Fill in the template; link the design section or test IDs.
4. **The other person reviews**, then **squash-merge**. Delete the branch.

`main` is protected by a local hook (`no-commit-to-branch`). GitHub's server-side branch protection
isn't available for private repos on the free plan, so this rule is on us.

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
| private keys | Blocks committed keys |
| branch | Blocks commits directly on `main` |
| message | Conventional Commit format |

If a hook changes files, review the change, `git add` it and commit again.
GitHub Actions runs the same checks on every pull request (Swift checks run locally only).

## Code standards

- **Python:** ruff + ruff-format settings in `pyproject.toml`; target Python 3.9 (the ML env).
  Type hints on new functions. Scripts take paths as arguments; no hard-coded user paths.
- **Swift:** `.swift-format` (4 spaces, 120 chars). New logic goes into testable code behind the
  protocols in `TEST_PLAN.md` §0, not into views.
- **Comments** explain *why*, not *what*. Keep the existing doc-comment style.
- **Tests:** follow `code/MotionStreamer/TEST_PLAN.md`. A build step's tests must pass before the
  next step starts (gates G0-G10). Name tests after their IDs (e.g. `test_R3_chunk_close`).

## What goes in git, and what doesn't

| In git | Not in git (shared drive) |
|---|---|
| Code, configs, docs, design and test plans | `code/recordings/` (personal motion data) |
| Small results: `results/**/*.md`, `*.json` | Videos, plots' raw arrays (`.npz`), model outputs |
| Annotations (`experiments/annotations/`) | MobilePoser / IMUCoCo repos, SMPL, weights, datasets |
| Patches to upstream repos (`patches/`) | Virtual environments, Xcode build output |

- Recordings use participant codes (`P01`), never names.
- Never commit secrets, Apple signing files or API keys.

## Logs and docs

- **`EXPERIMENT_LOG.md`:** every experiment run and every device-test round, with the commit hash.
- **Design or behaviour change:** update `FIELD_RECORDING_DESIGN.md` / `TEST_PLAN.md` in the same PR.
- **Upstream change:** edit the code in `code/MobilePoser`, then refresh the patch:
  `git -C code/MobilePoser -c core.fileMode=false diff > patches/mobileposer.patch`.
