"""Project locations, and sys.path entries for the live pipeline (code/live, code/receiver)."""

import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parent
EXPERIMENTS = COMMON.parent
CODE = EXPERIMENTS.parent
PROJECT = CODE.parent
RECORDINGS = CODE / "recordings"
ANNOTATIONS = EXPERIMENTS / "annotations"
MOBILEPOSER_DIR = CODE / "MobilePoser" / "mobileposer"
EXPERIMENT_LOG = PROJECT / "EXPERIMENT_LOG.md"

for p in (CODE / "live", CODE / "receiver"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def session_dir(name_or_path) -> Path:
    """Accept a session id (20261008-153213-P01) or a path to its folder."""
    p = Path(name_or_path)
    return p.resolve() if p.exists() else RECORDINGS / str(name_or_path)


def results_dir(experiment_file, session) -> Path:
    """<experiment folder>/results/<session id>/, created on demand."""
    out = Path(experiment_file).resolve().parent / "results" / Path(session).name
    out.mkdir(parents=True, exist_ok=True)
    return out
