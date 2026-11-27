"""RimWorld's own programs, for `programs status`: the texture encoder, todds."""
from __future__ import annotations

from pathlib import Path

from ...programs import Found, Program
from .textures import DEFAULT_TODDS, TODDS_RELEASE, standalone_todds, todds_path


def _todds(environ):
    found = todds_path(environ=environ)
    if not found:
        return Found(False, None, f"not found: put todds.exe from the release's Windows zip in {standalone_todds(environ).parent}, "
                                  "or name it with toddsPath in the settings")
    return Found(True, str(found), "RimSort's copy: keep a copy of your own before RimSort goes"
                 if Path(found) == DEFAULT_TODDS else "found")


PROGRAMS = [
    Program("todds", "The texture encoder (todds)", "Encoding mods' textures, on the Mods page",
            "todds 0.4.1 (MPL-2.0): unzip todds.exe from todds_Windows_0.4.1.zip into %LOCALAPPDATA%\\Programs\\todds. "
            "RimSort ships the same file", _todds, url=TODDS_RELEASE),
]
