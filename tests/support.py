"""Shared test setup: the package on the import path, and the fixtures folder. Nothing reads a real install."""
import atexit
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))


# Nothing a test does may reach the owner's own files: the history log and the central settings file point at a folder of the
# test run's own, for every test that does not name its own environment. A test that passes environ={} names these itself
# (isolated_environ), since an empty environment falls back to the home folder.
_RUN_FOLDER = Path(tempfile.mkdtemp(prefix="phobos-modkit-tests-"))
os.environ["PHOBOS_HISTORY"] = str(_RUN_FOLDER / "history")
os.environ["PHOBOS_SETTINGS"] = str(_RUN_FOLDER / "settings.json")
atexit.register(shutil.rmtree, _RUN_FOLDER, ignore_errors=True)


def isolated_environ(tmp=None, **extra):
    """An environment for a test that points the history log and the central settings file into tmp (or the run's folder)."""
    folder = Path(tmp) if tmp else _RUN_FOLDER
    return {"PHOBOS_HISTORY": str(folder / "history"), "PHOBOS_SETTINGS": str(folder / "settings.json"), **extra}


def fixture_text(relative):
    return (FIXTURES / relative).read_text(encoding="utf-8")
