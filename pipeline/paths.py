"""Project locations, shared by the pipeline and the experiments."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "data" / "recordings"
MOBILEPOSER_DIR = ROOT / "third_party" / "MobilePoser" / "mobileposer"
IMUCOCO_DIR = ROOT / "third_party" / "IMUCoCo"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
THRESHOLDS = (
    ROOT
    / "apps"
    / "MotionStreamer"
    / "Core"
    / "Sources"
    / "MotionStreamerCore"
    / "Resources"
    / "quality_thresholds.json"
)
