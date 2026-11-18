"""RimWorld's part of the install helper (phobos_modkit.installs): where installed mods live, a mod's name and version, and the
processes that mean the game is running."""
from __future__ import annotations

from pathlib import Path

from .mods import _about_root, _text
from .paths import game_path

# RimWorld.exe is 1.7 on Windows (seen in tasklist, 30 Oct 2026); RimWorldWin64.exe was 1.6. The others are the usual Unity names.
PROCESSES = ("RimWorld.exe", "RimWorldWin64.exe", "RimWorldWin.exe", "RimWorldLinux", "RimWorldLinux.x86_64", "RimWorldMac")


def installed_mods(settings=None, environ=None):
    """The game's own Mods folder, where locally installed mods live."""
    return Path(game_path(None, environ, settings)) / "Mods"


def identity(folder):
    """(name, version) from a mod's About/About.xml; empty strings for what it does not say."""
    root = _about_root(Path(folder))
    if root is None:
        return "", ""
    return _text(root, "name"), _text(root, "modVersion")
