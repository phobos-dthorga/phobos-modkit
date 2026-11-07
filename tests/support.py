"""Shared test setup: the package on the import path, and the fixtures folder. Nothing reads a real install."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))


def fixture_text(relative):
    return (FIXTURES / relative).read_text(encoding="utf-8")
