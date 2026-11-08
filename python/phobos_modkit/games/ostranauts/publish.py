"""Ostranauts' side of Workshop publishing.

Format facts, in our words: a mod folder holds mod_info.json, a JSON list whose first object names the mod in
strName and gives its version in strModVersion; the cover is preview.png at the top of the uploaded folder. Steam
app 1022980.

What a phobos-ostranauts package must hold (BepInEx plugin folders, read-only data headers, sounds) is that
project's policy, not a format fact: its wrapper passes it in as the project's payload hook.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...steam.publish.project import Adapter, ModInfo, PublishError

APP_ID = "1022980"


class Ostranauts(Adapter):
    name = "ostranauts"
    app_id = APP_ID
    metadata = "mod_info.json"
    preview = "preview.png"

    def read(self, folder):
        path = Path(folder) / self.metadata
        try:
            info = json.loads(path.read_text(encoding="utf-8-sig"))[0]
            return ModInfo(info["strName"], info["strModVersion"])
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            raise PublishError(f"Unreadable {path}: {error}") from None
