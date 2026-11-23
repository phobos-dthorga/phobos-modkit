"""Game adapters: public file-format knowledge for one game each, in our own words."""


def publish_adapters():
    """{Steam app ID: Adapter} for every game whose mods the Workshop publishing tools can read: one per
    games/<game>/workshop.json, a game file of data (steam/publish/game_data.py, 1.97.0)."""
    from pathlib import Path
    from ..steam.publish.game_data import load_folder
    return load_folder(Path(__file__).parent, __name__)


# The games whose lists of active mods the mod-list check reads (1.72.0): (id, name, Steam app ID, module with adapter()).
MOD_LIST_GAMES = (
    ("rimworld", "RimWorld", 294100, ".rimworld.mod_list"),
    ("project-zomboid", "Project Zomboid", 108600, ".zomboid.mod_list"),
)


def _plain(text):
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def mod_list_game(name=None, app_id=None):
    """(id, name, app ID, module) of the game named or numbered, or None when the check cannot read its list yet."""
    for row in MOD_LIST_GAMES:
        if (app_id and int(app_id) == row[2]) or (name and _plain(name) in (_plain(row[0]), _plain(row[1]))):
            return row
    return None


def mod_list_adapter(row, environ=None, settings=None, data=None, steam=None):
    from importlib import import_module
    return import_module(row[3], __name__).adapter(environ, settings, data, steam)


# The games whose own .NET assemblies a code tool may read for the method bodies a reference package leaves empty (1.116.0,
# `connections calls`' rings through the game's code): (id, module with real_assemblies(environ)). A next game adds a row.
REAL_ASSEMBLY_GAMES = (
    ("rimworld", ".rimworld.code_bodies"),
)


def real_assemblies(game, environ=None):
    """The game's own .NET assemblies on this computer, for their method bodies; empty when no game is named, the game has no
    reader of them yet, or it is not installed here."""
    from importlib import import_module
    for row in REAL_ASSEMBLY_GAMES:
        if game and _plain(game) == _plain(row[0]):
            try:
                return list(import_module(row[1], __name__).real_assemblies(environ))
            except (OSError, ValueError):
                return []
    return []
