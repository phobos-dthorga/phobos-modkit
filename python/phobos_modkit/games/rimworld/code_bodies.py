"""RimWorld's own assemblies, read for the method bodies the RimWorld reference package mods build against leaves empty
(1.116.0): `connections calls` follows a change's call into the game (`base.AvailableReport()`) to the game's call back into
the mod (`AvailableOnNow`), so a ring through the game's code is seen. Read as files, never loaded or run.
"""
from __future__ import annotations

from . import paths
from .targets_cli import game_assemblies


def real_assemblies(environ=None):
    """The game's managed assemblies where it is installed (the settings, else Steam's default folder); empty when it is not."""
    game = paths.game_path(None, environ, None)
    return game_assemblies(game) if game else []
