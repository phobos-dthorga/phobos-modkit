"""Machine paths, resolved by one precedence everywhere: argument, environment variable, settings file, default."""
from __future__ import annotations

import json
import os
from pathlib import Path


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
