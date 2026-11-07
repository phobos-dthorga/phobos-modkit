"""Machine paths, resolved by one precedence everywhere: argument, environment variable, settings file, default."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

CACHE = ("modkitCachePath", "PHOBOS_MODKIT_CACHE")
DEFAULT_CACHE = Path(tempfile.gettempdir()) / "phobos-modkit"


def resolve(key, env_var, default, explicit=None, environ=None, settings_file=None):
    """The path to use for one setting, or None when nothing names one.

    Precedence: an explicit argument; then the environment variable env_var; then the value of key in the JSON
    settings file (a game repository's ignored local settings); then default.
    """
    environ = os.environ if environ is None else environ
    if explicit:
        return Path(explicit)
    if env_var and environ.get(env_var):
        return Path(environ[env_var])
    if settings_file is not None:
        settings_file = Path(settings_file)
        if settings_file.is_file():
            with open(settings_file, encoding="utf-8") as fh:
                configured = json.load(fh).get(key)
            if configured:
                return Path(configured)
    return Path(default) if default is not None else None


def cache_root(explicit=None, environ=None, settings_file=None):
    """Where the kit keeps derived data such as save indexes. The default is under the system's temp folder,
    which cloud-sync tools usually leave alone: indexes hold data from the user's saves."""
    return resolve(*CACHE, DEFAULT_CACHE, explicit, environ, settings_file)
