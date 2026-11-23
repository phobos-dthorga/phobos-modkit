"""A mod's settings as its source declares them, for doc-tables' `mod-settings` kind (1.108.0). Game-free.

A game adapter reads them (RimWorld's: `games/rimworld/mod_settings.py`) and returns these; the core only lays them out.
What a next game needs is a `mod_settings(root, options)` in `games/<game>/mod_settings.py` that returns a `SettingsRead`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Setting:
    key: str                        # the name the setting is saved under
    label: str = None               # as the settings window shows it; None when it could not be read
    label_key: str = None           # the translation key the label comes from, when there is one
    description: str = None         # its tooltip or description text, when the code or the language files give one
    default: str = ""               # as a player sees it ("On", "Off", an option's label, a number)
    page: str = ""                  # the settings page it is drawn on, when the code has pages
    section: str = ""               # the heading it is drawn under on that page
    file: str = ""                  # where the window draws it (or, when it is not drawn, where it is saved)
    line: int = 0
    shown: bool = True              # whether the reader found it drawn in the settings window
    note: str = ""                  # anything else worth a reader's eye (a new player's different starting value)


@dataclass
class SettingsRead:
    settings: list = field(default_factory=list)     # Setting, in the order the window draws them, then those not drawn
    unresolved: list = field(default_factory=list)   # what could not be read, in words, for the command's report
