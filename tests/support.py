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
    """An environment for a test that points the history log, the central settings file and D'thorga Companion's own data folder
    into tmp (or the run's folder). Without LOCALAPPDATA and XDG_DATA_HOME, `paths.companion_data` falls back to the home folder,
    so a test reaching the Companion's folder wrote there (seen 23 Nov 2026: safe-copies' run-all record, where two runs at once
    collided). Since 1.103.0 the kit's cache too (PHOBOS_MODKIT_CACHE): the gate runs the tests on two Pythons side by side, and
    installs' backup peeks, unpacked into the shared cache, were deleted by one run under the other (seen 23 Nov 2026)."""
    folder = Path(tmp) if tmp else _RUN_FOLDER
    return {"PHOBOS_HISTORY": str(folder / "history"), "PHOBOS_SETTINGS": str(folder / "settings.json"),
            "LOCALAPPDATA": str(folder / "local-app-data"), "XDG_DATA_HOME": str(folder / "data-home"),
            "PHOBOS_MODKIT_CACHE": str(folder / "modkit-cache"), **extra}


def fixture_text(relative):
    return (FIXTURES / relative).read_text(encoding="utf-8")
