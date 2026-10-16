#!/usr/bin/env bash
# Swift line coverage of MotionStreamerCore against the exit criteria (docs/plan/test-plan.md §3):
# core >= 85 %, recorder + journal + recovery >= 95 %.
set -euo pipefail
cd "$(dirname "$0")/../apps/MotionStreamer/Core"
swift test --enable-code-coverage > /dev/null
python3 - <<'PY'
import json, sys
d = json.load(open(".build/debug/codecov/MotionStreamerCore.json"))
tot, rec = [0, 0], [0, 0]
for f in d["data"][0]["files"]:
    name = f["filename"]
    if "/Sources/MotionStreamerCore/" not in name:
        continue
    lines = f["summary"]["lines"]
    tot[0] += lines["covered"]; tot[1] += lines["count"]
    if "/Recorder/" in name:
        rec[0] += lines["covered"]; rec[1] += lines["count"]
core, recorder = 100 * tot[0] / tot[1], 100 * rec[0] / rec[1]
print(f"core {core:.1f} % (>= 85)   recorder + journal + recovery {recorder:.1f} % (>= 95)")
sys.exit(0 if core >= 85 and recorder >= 95 else 1)
PY
