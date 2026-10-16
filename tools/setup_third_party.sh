#!/usr/bin/env bash
# Clone the third-party model repos at their pinned commits and apply our patches.
# Licensed files (SMPL body model, weights, datasets) are NOT downloaded: follow each repo's README.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

setup() {
    local name="$1" url="$2" commit="$3" patch="${4:-}"
    local dir="$ROOT/third_party/$name"
    if [ ! -d "$dir/.git" ]; then
        git clone "$url" "$dir"
    fi
    git -C "$dir" fetch --quiet origin
    git -C "$dir" checkout --quiet "$commit"
    if [ -n "$patch" ]; then
        if git -C "$dir" apply --check "$ROOT/$patch" 2>/dev/null; then
            git -C "$dir" apply "$ROOT/$patch"
            echo "$name: patch applied"
        elif git -C "$dir" apply --reverse --check "$ROOT/$patch" 2>/dev/null; then
            echo "$name: patch already applied"
        else
            echo "$name: patch does not apply cleanly" >&2
            exit 1
        fi
    fi
    echo "$name: at $(git -C "$dir" rev-parse --short HEAD)"
}

setup MobilePoser https://github.com/SPICExLAB/MobilePoser.git 513e76a88ef310e12b51da6d30f44a819e68d331 third_party/patches/mobileposer.patch
setup IMUCoCo https://github.com/cmusmashlab/IMUCoCo.git d7dd17c70abccfc63935ce9e25452c6d312df630

echo
echo "Next: download the licensed files each repo needs (SMPL model, weights, datasets) as its README says."
