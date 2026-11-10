"""Where RimWorld keeps its files, and the setting names that override each place.

The Windows places were seen on a Steam install (November 2026). The Linux and macOS places are the usual Unity
and Steam ones and have not been checked on those systems.
"""
from __future__ import annotations

from pathlib import Path
import sys

from ...paths import resolve
from .mods import default_workshop

# (settings key, environment variable): the same names phobos-rimworld's .local/install-settings.json uses.
GAME = ("rimworldPath", "RIMWORLD_PATH")
WORKSHOP = ("workshopPath", "RIMWORLD_WORKSHOP_PATH")
LOGS = ("rimworldLogsPath", "RIMWORLD_LOGS_PATH")
SAVES = ("rimworldSavesPath", "RIMWORLD_SAVES_PATH")
CONFIG = ("rimworldConfigPath", "RIMWORLD_CONFIG_PATH")
LOG_NAME = "Player.log"
PREVIOUS_LOG_NAME = "Player-prev.log"


def default_game(platform=None, home=None):
    platform = platform or sys.platform
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        return Path(r"C:\Program Files (x86)\Steam\steamapps\common\RimWorld")
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "RimWorld"
    return home / ".local" / "share" / "Steam" / "steamapps" / "common" / "RimWorld"


def default_user_data(platform=None, home=None):
    """The folder holding Saves, Config and the logs."""
    platform = platform or sys.platform
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        return home / "AppData" / "LocalLow" / "Ludeon Studios" / "RimWorld by Ludeon Studios"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "RimWorld"
    return home / ".config" / "unity3d" / "Ludeon Studios" / "RimWorld by Ludeon Studios"


def default_logs(platform=None, home=None):
    """1.7 writes its logs to a Logs folder; 1.6 wrote them beside Saves and Config."""
    user_data = default_user_data(platform, home)
    logs = user_data / "Logs"
    return logs if logs.is_dir() or not user_data.is_dir() else user_data


def game_path(explicit=None, environ=None, settings_file=None):
    return resolve(*GAME, default_game(), explicit, environ, settings_file)


def workshop_path(game, explicit=None, environ=None, settings_file=None):
    return resolve(*WORKSHOP, default_workshop(game), explicit, environ, settings_file)


def logs_path(explicit=None, environ=None, settings_file=None):
    return resolve(*LOGS, default_logs(), explicit, environ, settings_file)


def saves_path(explicit=None, environ=None, settings_file=None):
    return resolve(*SAVES, default_user_data() / "Saves", explicit, environ, settings_file)


def config_path(explicit=None, environ=None, settings_file=None):
    """The folder holding ModsConfig.xml."""
    return resolve(*CONFIG, default_user_data() / "Config", explicit, environ, settings_file)


# A file of every Def with patches applied, written by a running game on request. phobos-rimworld's D'thorga Framework
# writes it beside the Config folder; another mod may write the same shape anywhere and name it with these settings.
PATCHED_DEFS = ("rimworldPatchedDefsPath", "RIMWORLD_PATCHED_DEFS")
PATCHED_DEFS_DEFAULT = ("PhobosPatchedDefs", "PatchedDefs.xml")


def patched_defs_path(explicit=None, environ=None, settings_file=None):
    """The patched-Defs file: the one named, or where D'thorga Framework writes it. It may not exist."""
    default = Path(config_path(None, environ, settings_file)).parent.joinpath(*PATCHED_DEFS_DEFAULT)
    return resolve(*PATCHED_DEFS, default, explicit, environ, settings_file)


# The colony mood file: every colonist's thoughts as the game added them up at the last save. phobos-rimworld's D'thorga
# Framework writes it beside the Config folder (its setting "Write a colony mood file at each save").
COLONY_MOOD = ("rimworldColonyMoodPath", "RIMWORLD_COLONY_MOOD")
COLONY_MOOD_DEFAULT = ("PhobosSnapshots", "ColonyMood.xml")


def colony_mood_path(explicit=None, environ=None, settings_file=None):
    """The colony mood file: the one named, or where D'thorga Framework writes it. It may not exist."""
    default = Path(config_path(None, environ, settings_file)).parent.joinpath(*COLONY_MOOD_DEFAULT)
    return resolve(*COLONY_MOOD, default, explicit, environ, settings_file)
