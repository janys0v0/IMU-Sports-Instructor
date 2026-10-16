#!/usr/bin/env python3
"""Check branch names, commit messages and pull requests against the project format.

The rules are in CONTRIBUTING.md, "Commit, branch and PR format"; this file is the only place
that encodes them.

Usage:
    tools/check_format.py MSG_FILE              commit message (commit-msg hook)
    tools/check_format.py --branch [NAME]       branch name (default: current branch)
    tools/check_format.py --title TITLE         pull request title
    tools/check_format.py --pr-body FILE        pull request description
    tools/check_format.py --pr BRANCH TITLE FILE   all three for a pull request, plus type match
"""

import re
import subprocess
import sys

TYPES = ["feat", "fix", "docs", "test", "refactor", "perf", "build", "ci", "chore", "exp", "data"]
SCOPES = [
    "app", "watch", "recorder", "ingest", "preprocessing", "pose", "live", "analysis",
    "experiments", "design", "plan", "tools", "deps", "third-party",
]  # fmt: skip
BRANCH_TYPES = TYPES + ["spike"]  # spike/ branches are throwaway and never merged
PROTECTED = ["main"]
PR_SECTIONS = ["## Why", "## What changed", "## How it was checked", "## Plan"]
MAX_BRANCH = 40
MAX_SUBJECT = 72
MAX_BODY = 72

SUBJECT = re.compile(r"^(?P<type>[a-z]+)(\((?P<scope>[a-z-]+)\))?(?P<bang>!)?: (?P<desc>.+)$")
BRANCH = re.compile(r"^(?P<type>[a-z]+)/(?P<desc>[a-z0-9]+(-[a-z0-9]+)*)$")
FORBIDDEN = re.compile(
    r"co-authored-by:.*(claude|anthropic|copilot|chatgpt|openai)|generated with", re.IGNORECASE
)
SKIP_SUBJECTS = ("Merge ", "Revert ", "fixup! ", "squash! ", "amend! ")


def check_branch(name: str) -> list:
    if name in PROTECTED or name == "HEAD":
        return []
    m = BRANCH.match(name)
    if not m:
        return [f'branch must look like "type/kebab-desc", got: {name!r}']
    errors = []
    if m["type"] not in BRANCH_TYPES:
        errors.append(f"branch type {m['type']!r} not in: {', '.join(BRANCH_TYPES)}")
    if len(name) > MAX_BRANCH:
        errors.append(f"branch name is {len(name)} characters; max {MAX_BRANCH}")
    return errors


def check_subject(subject: str) -> list:
    m = SUBJECT.match(subject)
    if not m:
        return [f'subject must look like "type(scope): desc", got: {subject!r}']
    errors = []
    if m["type"] not in TYPES:
        errors.append(f"type {m['type']!r} not in: {', '.join(TYPES)}")
    if m["scope"] and m["scope"] not in SCOPES:
        errors.append(f"scope {m['scope']!r} not in: {', '.join(SCOPES)}")
    desc = m["desc"]
    if desc[0].isupper():
        errors.append("description must start with a lowercase letter")
    if desc.endswith("."):
        errors.append("description must not end with a period")
    if len(subject) > MAX_SUBJECT:
        errors.append(f"subject is {len(subject)} characters; max {MAX_SUBJECT}")
    return errors


def check_message(text: str) -> list:
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ["empty message"]
    if lines[0].startswith(SKIP_SUBJECTS):
        return []
    errors = check_subject(lines[0])
    if len(lines) > 1 and lines[1].strip():
        errors.append("leave a blank line between the subject and the body")
    for n, line in enumerate(lines[2:], start=3):
        if len(line) > MAX_BODY and "://" not in line:
            errors.append(f"body line {n} is {len(line)} characters; wrap at {MAX_BODY}")
    if FORBIDDEN.search(text):
        errors.append('no AI co-author lines or "Generated with" footers')
    return errors


def check_pr_body(text: str) -> list:
    errors = [f"description is missing the section {s!r}" for s in PR_SECTIONS if s not in text]
    if FORBIDDEN.search(text):
        errors.append('no AI co-author lines or "Generated with" footers')
    return errors


def check_pr(branch: str, title: str, body: str) -> list:
    errors = check_branch(branch) + check_subject(title) + check_pr_body(body)
    b, t = BRANCH.match(branch), SUBJECT.match(title)
    if b and t and b["type"] != t["type"] and b["type"] != "spike":
        errors.append(f"PR title type {t['type']!r} must match branch type {b['type']!r}")
    if b and b["type"] == "spike":
        errors.append("spike/ branches are throwaway; don't open a pull request from them")
    return errors


def current_branch() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv: list) -> int:
    if argv[:1] == ["--branch"] and len(argv) <= 2:
        errors = check_branch(argv[1] if len(argv) == 2 else current_branch())
    elif argv[:1] == ["--title"] and len(argv) == 2:
        errors = check_subject(argv[1])
    elif argv[:1] == ["--pr-body"] and len(argv) == 2:
        errors = check_pr_body(read(argv[1]))
    elif argv[:1] == ["--pr"] and len(argv) == 4:
        errors = check_pr(argv[1], argv[2], read(argv[3]))
    elif len(argv) == 1 and not argv[0].startswith("--"):
        errors = check_message(read(argv[0]))
    else:
        print(__doc__)
        return 2
    for e in errors:
        print(f"✗ {e}")
    if errors:
        print("Format: CONTRIBUTING.md, section 'Commit, branch and PR format'.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
