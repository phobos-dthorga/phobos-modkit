"""Where games and the programs beside them keep the player's own files: saves, settings, logs (1.71.0). Game-free.

One row per folder, each a setting with a default where the game puts it on Windows, so a game's list of safe copies, or any later
tool, can name the folder by its key and work on a new PC with nothing set. Adding a game is one row here. RimWorld's own folders
are its game module's (games/rimworld/paths.py), which the kit had already.
"""
from __future__ import annotations

from pathlib import Path


def _home(environ):
    return Path(environ.get("USERPROFILE") or Path.home())


def _local(environ):
    return Path(environ["LOCALAPPDATA"]) if environ.get("LOCALAPPDATA") else _home(environ) / "AppData" / "Local"


# (key, environment variable, game, what it is, the default as a function of the environment)
FOLDERS = (
    ("rimsortPath", "PHOBOS_RIMSORT", "rimworld", "RimSort's own folder: its settings, your rules and each instance's mod notes",
     lambda environ: _local(environ) / "RimSort"),
    ("ostranautsDataPath", "PHOBOS_OSTRANAUTS_DATA", "ostranauts", "Where Ostranauts keeps its saves, settings and Player.log",
     lambda environ: _home(environ) / "AppData" / "LocalLow" / "Blue Bottle Games" / "Ostranauts"),
    ("kenshiDataPath", "PHOBOS_KENSHI_DATA", "kenshi", "Where Kenshi keeps its saves", lambda environ: _local(environ) / "kenshi"),
    ("zomboidDataPath", "PHOBOS_ZOMBOID_DATA", "project-zomboid",
     "Where Project Zomboid keeps its saves, settings, logs and local mods", lambda environ: _home(environ) / "Zomboid"),
)
