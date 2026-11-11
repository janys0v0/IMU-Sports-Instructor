#!/usr/bin/env bash
# All automated tests: the Swift core package and the Python pipeline.
# Usage: tools/run_tests.sh [--python-only | --swift-only]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-.venv/bin/python}"
# Swift tests export sample sessions here for the Python format checks (R8, S4).
export MSC_EXPORT_DIR="${MSC_EXPORT_DIR:-${TMPDIR:-/tmp}/motionstreamer-export}"
[ -x "$PY" ] || PY=python3

if [ "${1:-}" != "--python-only" ]; then
    echo "== swift test (apps/MotionStreamer/Core)"
    log="$(mktemp)"
    status=0
    swift test --package-path apps/MotionStreamer/Core > "$log" 2>&1 || status=$?
    grep -E ": error: " "$log" || true          # every failing assertion, in full
    grep -E "Executed .* tests" "$log" | tail -1
    rm -f "$log"
    test "$status" -eq 0
fi

if [ "${1:-}" != "--swift-only" ]; then
    echo "== pytest (tests/)"
    "$PY" -W ignore -m pytest -q tests
fi
