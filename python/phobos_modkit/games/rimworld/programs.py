"""RimWorld's own programs, for `programs status`: RimSort's texture encoder."""
from __future__ import annotations

from ...programs import Found, Program
from .textures import todds_path


def _todds(environ):
    found = todds_path(environ=environ)
    return (Found(True, str(found), "found") if found
            else Found(False, None, "not at RimSort's usual place, RIMSORT_TODDS or toddsPath in the settings"))


PROGRAMS = [
    Program("todds", "RimSort's texture encoder (todds)", "Encoding mods' textures, on the Mods page",
            "Comes with RimSort, https://github.com/RimSort/RimSort", _todds,
            url="https://github.com/RimSort/RimSort"),
]
