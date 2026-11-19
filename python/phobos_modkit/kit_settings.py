"""The settings the tools read: each one's name, what it is for, its value and where that value comes from.

Every path a tool reads goes through phobos_modkit.paths.resolve, by one precedence: an argument, an environment variable, the
repository's settings file, the central settings file, a default. This module lists the settings the kit knows, adds those a
repository declares for its own scripts (config/settings.json), says which layer sets each one now, and writes the central file:
the one place for settings that hold for every repository and every game (owner, 19 Nov 2026).

A repository's config/settings.json:

    {"schemaVersion": 1, "settings": [
      {"key": "artWorkPath", "env": "PHOBOS_ART_WORK", "kind": "folder",
       "description": "Where the art tools keep their masks, parts and staging"}]}
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from . import paths

KINDS = ("folder", "file")
REPOSITORY_SETTINGS = Path("config") / "settings.json"
LOCAL_SETTINGS = Path(".local") / "install-settings.json"
MAX_VALUE = 500


class SettingsError(ValueError):
    """A request this module refuses, with the reason in words."""


@dataclass
class Setting:
    key: str
    env: str
    description: str
    kind: str = "folder"
    game: str = None                  # None for a setting of every game
    default: object = None            # a function of environ giving the default path, or None when there is none
    declared_by: str = "phobos-modkit"


def _known():
    """The settings the kit itself reads, each from the module that owns it."""
    from . import assembly_archive, history, records
    from .code import compare
    from .games.rimworld import paths as rimworld
    from .games.rimworld import textures
    from .testpass_cli import DECISIONS, VERDICTS

    def default_of(function):
        return lambda environ: function()

    return [
        Setting(*history.LOG, "Where the record of what happened on this PC is kept: installs, go-backs, backups, builds, encoded "
                "textures", "folder", default=lambda environ: paths.companion_data(environ) / "history"),
        Setting(*records.BACKUP, "Where copies of the Companion's own records go: choose a folder your NAS or other backup keeps",
                "folder"),
        Setting(*paths.CACHE, "Where the tools keep what they work out from your files: save indexes, cached pages, the "
                "changelogs' history", "folder", default=lambda environ: paths.DEFAULT_CACHE),
        Setting(*VERDICTS, "Where your test verdicts are kept (one file for each repository)", "folder",
                default=lambda environ: paths.companion_data(environ) / "test-verdicts"),
        Setting(*DECISIONS, "Where your word on notes no test row names is kept", "folder",
                default=lambda environ: paths.companion_data(environ) / "test-key-decisions"),
        Setting(*assembly_archive.ARCHIVE, "Where every kept version of the game's and tied mods' assemblies is stored", "folder"),
        Setting(*compare.DECOMPILER, "The decompiler used to compare two builds (ilspycmd)", "file"),
        Setting(*rimworld.GAME, "The RimWorld folder", "folder", "rimworld", default_of(rimworld.default_game)),
        Setting(*rimworld.WORKSHOP, "RimWorld's Steam Workshop folder", "folder", "rimworld"),
        Setting(*rimworld.LOGS, "Where RimWorld writes Player.log", "folder", "rimworld", default_of(rimworld.default_logs)),
        Setting(*rimworld.SAVES, "Where RimWorld keeps its saves", "folder", "rimworld",
                lambda environ: rimworld.default_user_data() / "Saves"),
        Setting(*rimworld.CONFIG, "Where RimWorld keeps ModsConfig.xml and mod settings", "folder", "rimworld",
                lambda environ: rimworld.default_user_data() / "Config"),
        Setting(*rimworld.PATCHED_DEFS, "The patched-Defs file D'thorga Framework writes on request", "file", "rimworld"),
        Setting(*rimworld.COLONY_MOOD, "The colony mood file D'thorga Framework writes at each save", "folder", "rimworld"),
        Setting(*rimworld.SEEN_IN_PLAY, "The seen-in-play notes D'thorga Framework writes", "file", "rimworld"),
        Setting(*textures.TODDS, "RimSort's texture encoder (todds.exe)", "file", "rimworld", lambda environ: textures.DEFAULT_TODDS),
    ]


def declared(root):
    """The settings a repository declares for its own scripts; [] without config/settings.json. Raises on a malformed one."""
    path = Path(root) / REPOSITORY_SETTINGS
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SettingsError(f"{path} could not be read: {error}") from None
    found = []
    for item in data.get("settings", []):
        if not item.get("key") or item.get("kind", "folder") not in KINDS:
            raise SettingsError(f"{path} has a setting with no key or an unknown kind: {item}")
        found.append(Setting(item["key"], item.get("env", ""), item.get("description", ""), item.get("kind", "folder"),
                             item.get("game"), declared_by=Path(root).resolve().name))
    return found


def registry(roots=()):
    """Every setting: the kit's, then each repository's own, each key once (the first to declare it)."""
    found, seen = [], set()
    for setting in _known() + [s for root in roots for s in declared(root)]:
        if setting.key not in seen:
            seen.add(setting.key)
            found.append(setting)
    return found


def repository_settings_file(root):
    """The settings file a repository keeps for itself: the one its installs.json names, else .local/install-settings.json."""
    root = Path(root)
    try:
        named = json.loads((root / "config" / "installs.json").read_text(encoding="utf-8")).get("settings")
    except (OSError, ValueError):
        named = None
    return root / (named or LOCAL_SETTINGS)


@dataclass
class Reading:
    setting: Setting
    value: str = None                 # the value in force; None when nothing names one
    layer: str = "default"            # "environment", "repository", "central" or "default"
    repository: str = None            # which repository's file set it, when the layer is "repository"
    central: str = None               # the central file's value, whether or not it is in force
    default: str = None
    exists: bool = None               # whether the value names something on this PC
    overridden: list = field(default_factory=list)   # repositories whose own file sets it otherwise


def read(roots=(), environ=None):
    """How every setting stands now. With repositories named, a repository's own file is shown as the layer in force for the
    first repository that sets it, and every other repository that sets it differently is listed."""
    import os
    environ = os.environ if environ is None else environ
    central = paths.read_settings_file(paths.central_settings_file(environ))
    readings = []
    for setting in registry(roots):
        default = setting.default(environ) if setting.default else None
        reading = Reading(setting, central=central.get(setting.key) or None, default=str(default) if default else None)
        found = paths.where(setting.key, setting.env, None, environ, None)
        for root in roots:
            own = paths.read_settings_file(repository_settings_file(root)).get(setting.key)
            if own:
                reading.overridden.append({"repository": Path(root).resolve().name, "value": str(own)})
        if found and found[0] == "environment":
            reading.value, reading.layer = found[1], "environment"
        elif reading.overridden:
            reading.value, reading.layer = reading.overridden[0]["value"], "repository"
            reading.repository = reading.overridden[0]["repository"]
        elif found:
            reading.value, reading.layer = found[1], found[0]
        elif default:
            reading.value = str(default)
        if reading.value:
            reading.exists = Path(reading.value).exists()
        readings.append(reading)
    return readings


def set_central(key, value, roots=(), environ=None):
    """Sets (or, with value None, clears) one setting in the central file. Only a known setting, and only a full path."""
    known = {s.key: s for s in registry(roots)}
    if key not in known:
        raise SettingsError(f"{key!r} is not a setting the tools read.")
    path = paths.central_settings_file(environ)
    current = paths.read_settings_file(path)
    if value is None:
        current.pop(key, None)
    else:
        value = str(value).strip()
        if not value or len(value) > MAX_VALUE or "\n" in value or not Path(value).is_absolute():
            raise SettingsError("A setting's value is a full path, such as K:\\phobos-modkit\\history.")
        current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(dict(sorted(current.items())), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
