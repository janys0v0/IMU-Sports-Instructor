#!/usr/bin/env python3
"""Speak the whole voice script with the Mac's speech synthesizer into one audio file (test V9).

Usage: tools/make_voice_sample.py [OUT.aiff] [--landmark "the net"]
Plays a clean calibration (C1-C11), the failure and reminder phrases, then every alert, with short
pauses between phrases, so both of you can listen for clarity and pacing.
"""

import argparse
import json
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "apps/MotionStreamer/Core/Sources/MotionStreamerCore/Resources/voice_prompts.json"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", nargs="?", default="voice_sample.aiff")
    parser.add_argument("--landmark", default="the net")
    args = parser.parse_args()
    s = json.loads(SCRIPT.read_text())
    cal = s["calibration"]

    def fill(text, **kw):
        for k, v in ({"landmark": args.landmark} | kw).items():
            text = text.replace("{" + k + "}", v)
        return text

    clean = ["C1", "C2", "C3", "C4", "C6", "C7", "C9", "C10", "C11"]
    phrases = [fill(cal[c]) for c in clean]
    phrases += [fill(cal["C5"]), fill(cal["C8"])]
    phrases += [fill(cal["C12a"], reason=r) for r in s["reasons"].values()] + [
        cal["C12b"],
        cal["C12_final"],
    ]
    phrases += [fill(t) for t in s["reminder"].values()] + [s["audibility"]]
    for alert in s["alerts"].values():
        phrases.append(fill(alert["text"], trial="four", reason="The AirPods were missing for twelve seconds.",
                            device="The watch"))  # fmt: skip
    text = " [[slnc 900]] ".join(phrases)
    subprocess.run(["say", "-r", "170", "-o", args.out, text], check=True)
    print(f"wrote {args.out}: {len(phrases)} phrases")


if __name__ == "__main__":
    main()
