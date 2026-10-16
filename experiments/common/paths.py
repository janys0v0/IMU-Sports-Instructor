"""Locations used by the experiments (project-wide ones come from pipeline.paths)."""

from pathlib import Path

from pipeline.paths import IMUCOCO_DIR, MOBILEPOSER_DIR, RECORDINGS, ROOT  # noqa: F401

EXPERIMENTS = Path(__file__).resolve().parents[1]
ANNOTATIONS = EXPERIMENTS / "annotations"
EXPERIMENT_LOG = ROOT / "EXPERIMENT_LOG.md"


def session_dir(name_or_path) -> Path:
    """Accept a session id (20261008-153213-P01) or a path to its folder."""
    p = Path(name_or_path)
    return p.resolve() if p.exists() else RECORDINGS / str(name_or_path)


def results_dir(experiment_file, session) -> Path:
    """<experiment folder>/results/<session id>/, created on demand."""
    out = Path(experiment_file).resolve().parent / "results" / Path(session).name
    out.mkdir(parents=True, exist_ok=True)
    return out
