#!/usr/bin/env python3
"""Fail if a Markdown file links to a local file or heading that doesn't exist.

Usage: tools/check_doc_links.py [FILE.md ...]   (default: every tracked .md file)
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#terminal/", "#local_")


def slug(heading: str) -> str:
    """GitHub-style anchor for a heading."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set:
    return {
        slug(line.lstrip("#"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("#")
    }


def check(md: Path) -> list:
    errors = []
    for target in LINK.findall(md.read_text(encoding="utf-8")):
        if target.startswith(SKIP_PREFIXES):
            continue
        file_part, _, anchor = target.partition("#")
        file_part = file_part.split(":")[0]  # allow file.swift:42 line links
        dest = (md.parent / file_part).resolve() if file_part else md
        if not dest.exists():
            errors.append(f"{md.relative_to(ROOT)}: missing file {target}")
        elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
            errors.append(f"{md.relative_to(ROOT)}: missing heading {target}")
    return errors


def main() -> int:
    files = [Path(f).resolve() for f in sys.argv[1:]] or [
        ROOT / f
        for f in subprocess.run(
            ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    ]
    errors = [e for f in files if f.suffix == ".md" for e in check(f)]
    print("\n".join(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
