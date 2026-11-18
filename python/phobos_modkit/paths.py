"""Machine paths, resolved by one precedence everywhere: argument, environment variable, the repository's settings file, the
central settings file, default.

The central settings file is the owner's one place for settings that hold for every repository and every game (owner, 19 Nov
2026: "a central settings page where everything or at least, most, of these sorts of things are managed"). It lives in D'thorga
Companion's own folder (settings.json), or where PHOBOS_SETTINGS names; the Companion's Settings page and `settings set` write it,
and every tool reads it through resolve(). A repository's own settings file still wins over it, so one repository can differ.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

CACHE = ("modkitCachePath", "PHOBOS_MODKIT_CACHE")
DEFAULT_CACHE = Path(tempfile.gettempdir()) / "phobos-modkit"
COMPANION_ID = "org.phobosdthorga.companion"
CENTRAL_VARIABLE = "PHOBOS_SETTINGS"
CENTRAL_NAME = "settings.json"


def companion_data(environ=None):
    """D'thorga Companion's own data folder, where Tauri keeps an app's local data."""
    environ = os.environ if environ is None else environ
    if sys.platform == "win32" and environ.get("LOCALAPPDATA"):
        return Path(environ["LOCALAPPDATA"]) / COMPANION_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / COMPANION_ID
    return Path(environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / COMPANION_ID


def central_settings_file(environ=None):
    """The central settings file: PHOBOS_SETTINGS, else settings.json in D'thorga Companion's folder. It may not exist."""
    environ = os.environ if environ is None else environ
    named = environ.get(CENTRAL_VARIABLE)
    return Path(named) if named else companion_data(environ) / CENTRAL_NAME


def read_settings_file(path):
    """A settings file's values as a dict; {} when it is missing or unreadable, so a broken file never stops a tool."""
    try:
        with open(path, encoding="utf-8") as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def resolve(key, env_var, default, explicit=None, environ=None, settings_file=None):
    """The path to use for one setting, or None when nothing names one.

    Precedence: an explicit argument; then the environment variable env_var; then the value of key in the JSON
    settings file (a game repository's ignored local settings); then the central settings file; then default.
    """
    environ = os.environ if environ is None else environ
    found = where(key, env_var, explicit, environ, settings_file)
    if found is not None:
        return Path(found[1])
    return Path(default) if default is not None else None


def where(key, env_var, explicit=None, environ=None, settings_file=None):
    """(layer, value) for the layer that sets this setting: "argument", "environment", "repository" or "central"; None when
    none does and the default applies."""
    environ = os.environ if environ is None else environ
    if explicit:
        return "argument", str(explicit)
    if env_var and environ.get(env_var):
        return "environment", environ[env_var]
    if settings_file is not None and Path(settings_file).is_file():
        configured = read_settings_file(settings_file).get(key)
        if configured:
            return "repository", str(configured)
    if key:
        configured = read_settings_file(central_settings_file(environ)).get(key)
        if configured:
            return "central", str(configured)
    return None


def cache_root(explicit=None, environ=None, settings_file=None):
    """Where the kit keeps derived data such as save indexes. The default is under the system's temp folder,
    which cloud-sync tools usually leave alone: indexes hold data from the user's saves."""
    return resolve(*CACHE, DEFAULT_CACHE, explicit, environ, settings_file)
