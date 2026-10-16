#!/usr/bin/env bash
# Every check before pushing: formatting, lint, doc links, and tests (once they exist).
# Usage: tools/check.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== pre-commit (all files)"
.venv-tools/bin/pre-commit run --all-files

if [ -x tools/run_tests.sh ]; then
    echo "== tests"
    tools/run_tests.sh
else
    echo "== tests: none yet (tools/run_tests.sh arrives in stage 0)"
fi

echo "== all checks passed"
