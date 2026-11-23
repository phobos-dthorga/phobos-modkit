"""The owner's games list, as D'thorga Companion keeps it (games.json): each game and the repository folders it lists (1.109.0).

Moved out of safe_copies_daily, which read it first (1.71.0), when the MCP server needed it too. Game-free: a game is an id and a
name, and its repositories are folders, absolute or under the list's `root`.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .paths import companion_data, resolve

GAMES = ("companionGamesPath", "PHOBOS_COMPANION_GAMES")


class GamesListError(ValueError):
    """The games list could not be read, with the reason in words."""


@dataclass(frozen=True)
class Listed:
    """One repository on the games list: its folder, and the game that lists it."""
    folder: Path
    game: str
    game_name: str

    @property
    def name(self):
        return self.folder.name


def games_file(explicit=None, environ=None):
    """The owner's games list: the argument, PHOBOS_COMPANION_GAMES (as D'thorga Companion reads it), the setting, or the
    Companion's own folder."""
    return resolve(*GAMES, companion_data(environ) / "games.json", explicit, environ)


def entries(path):
    """Every repository on a games list, each folder once (under the first game that lists it), in the list's order."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise GamesListError(f"the games list {path} could not be read: {error}") from None
    if not isinstance(data, dict):
        raise GamesListError(f"the games list {path} is not an object")
    root = Path(data["root"]) if data.get("root") else None
    found, seen = [], set()
    for game in data.get("games", []):
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("id") or "")
        for entry in game.get("repositories", []):
            if not isinstance(entry, str) or not entry:
                continue
            folder = Path(entry) if Path(entry).is_absolute() or root is None else root / entry
            if folder not in seen:
                seen.add(folder)
                found.append(Listed(folder, game_id, str(game.get("name") or game_id)))
    return found


def repositories(path):
    """Every repository folder on a games list, each once, in the list's order."""
    return [entry.folder for entry in entries(path)]
