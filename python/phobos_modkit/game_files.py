"""game-files: what a game itself writes and what Steam records about it, for any Steam game (1.46.0).

    game-files report --name NAME [--app-id N] [--data DIR] [--saves DIR] [--screenshots DIR] [--since TIME]
    game-files steam-games                       every game Steam has installed on this PC

One report, in four parts, read only:

- **What changed since you last played**: the game's build and when Steam last updated it, and every Workshop item updated since
  the last launch (Steam's own LastPlayed), or since --since.
- **Saves**: each save in the saves folder, newest first, with its size; autosaves marked.
- **Screenshots**: the game's own and Steam's (userdata/<id>/760/remote/<appid>/screenshots), newest first.
- **Space**: the install, the Workshop items, and each folder of the game's data folder, largest first.

The game is found in Steam's libraries by --app-id, else by its name. Each place is the one given, else guessed: the data folder
from the usual homes of game data (LocalLow, Documents\\My Games, AppData, the home folder) by the game's name; saves and screenshots
inside it. A place not found is said so in words, never shown as an empty list (D'thorga Companion's docs/later.md, item 5).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys

from .manifest import READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE = 0, 2
STEAM = ("steamPath", "PHOBOS_STEAM")
PICTURES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})
SAVE_FOLDERS = ("Saves", "saves", "save", "Save")
SHOT_FOLDERS = ("Screenshots", "screenshots", "Screenshot")
AUTOSAVE = re.compile(r"auto", re.IGNORECASE)
LISTED = 200
WORKSHOP_TITLE_FILES = (("About/About.xml", re.compile(r"<name>\s*(.*?)\s*</name>", re.S)),
                        ("mod.info", re.compile(r"^name\s*=\s*(.+)$", re.M)))
TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


# ---------------------------------------------------------------- Steam's own records

def parse_vdf(text):
    """Valve's key-value text (libraryfolders.vdf, appmanifest_*.acf) as nested dicts."""
    stack, current, key = [], {}, None
    for quoted, brace in TOKEN.findall(text):
        if brace == "{":
            child = {}
            current[key] = child
            stack.append(current)
            current, key = child, None
        elif brace == "}":
            current = stack.pop() if stack else current
        elif key is None:
            key = quoted.replace("\\\\", "\\")
        else:
            current[key] = quoted.replace("\\\\", "\\")
            key = None
    return current


def _read_vdf(path):
    try:
        return parse_vdf(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def steam_root(environ=None):
    from .paths import resolve
    environ = os.environ if environ is None else environ
    if sys.platform == "win32":
        default = Path(environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
    elif sys.platform == "darwin":
        default = Path.home() / "Library" / "Application Support" / "Steam"
    else:
        default = Path.home() / ".steam" / "steam"
    return resolve(*STEAM, default, None, environ)


def libraries(steam):
    """Every Steam library folder, the main one first."""
    found = [Path(steam)]
    folders = _read_vdf(Path(steam) / "steamapps" / "libraryfolders.vdf").get("libraryfolders", {})
    for entry in folders.values() if isinstance(folders, dict) else []:
        if isinstance(entry, dict) and entry.get("path") and Path(entry["path"]) not in found:
            found.append(Path(entry["path"]))
    return [f for f in found if (f / "steamapps").is_dir()]


def installed_games(steam):
    """Every game Steam has installed: appid, name, install folder, library, build, last update and launch, size."""
    games = []
    for library in libraries(steam):
        for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
            state = _read_vdf(manifest).get("AppState", {})
            if not isinstance(state, dict) or not state.get("appid"):
                continue
            games.append({"appId": int(state["appid"]), "name": state.get("name", ""), "library": str(library),
                          "install": str(library / "steamapps" / "common" / state.get("installdir", "")),
                          "buildId": state.get("buildid"), "lastUpdated": _int(state.get("LastUpdated")),
                          "lastPlayed": _int(state.get("LastPlayed")), "sizeOnDisk": _int(state.get("SizeOnDisk"))})
    return games


def _int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def find_game(steam, name=None, app_id=None):
    """The installed game by app ID, else by name (ignoring case); None when Steam has no such game installed."""
    games = installed_games(steam)
    if app_id:
        return next((g for g in games if g["appId"] == int(app_id)), None)
    wanted = " ".join(str(name or "").split()).casefold()
    return (next((g for g in games if g["name"].casefold() == wanted), None)
            or next((g for g in games if wanted and g["name"].casefold().startswith(wanted)), None))


def _workshop_title(folder):
    for relative, pattern in WORKSHOP_TITLE_FILES:
        try:
            found = pattern.search((folder / relative).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if found:
            return " ".join(found.group(1).split())[:200]
    return None


def workshop_items(game):
    """Every Workshop item installed for the game: id, title where its files name one, size and when it was last updated."""
    library = Path(game["library"]) / "steamapps" / "workshop"
    record = _read_vdf(library / f"appworkshop_{game['appId']}.acf").get("AppWorkshop", {})
    installed = record.get("WorkshopItemsInstalled", {}) if isinstance(record, dict) else {}
    items = []
    for item_id, item in (installed.items() if isinstance(installed, dict) else []):
        if not isinstance(item, dict):
            continue
        folder = library / "content" / str(game["appId"]) / item_id
        items.append({"id": item_id, "title": _workshop_title(folder), "bytes": _int(item.get("size")) or 0,
                      "updated": _int(item.get("timeupdated"))})
    return items


# ---------------------------------------------------------------- the game's own files

def _homes(environ=None):
    environ = os.environ if environ is None else environ
    home = Path(environ.get("USERPROFILE") or environ.get("HOME") or Path.home())
    found = [home / "AppData" / "LocalLow", home / "Documents" / "My Games", home / "AppData" / "Local",
             home / "AppData" / "Roaming", home / "Documents", home / ".config" / "unity3d", home / ".local" / "share", home]
    return [h for h in found if h.is_dir()]


def _key(text):
    return re.sub(r"[^a-z0-9]", "", str(text).casefold())


def guess_data(name, environ=None):
    """The game's data folder, guessed from the usual homes by its name: a folder named for it, or for its maker with one inside
    named for it (LocalLow\\Ludeon Studios\\RimWorld by Ludeon Studios). None when nothing matches."""
    wanted = _key(name)
    if not wanted:
        return None
    for home in _homes(environ):
        try:
            children = [c for c in home.iterdir() if c.is_dir()]
        except OSError:
            continue
        for child in children:
            if _key(child.name) == wanted or _key(child.name).startswith(wanted):
                return child
        for maker in children:
            try:
                inner = [c for c in maker.iterdir() if c.is_dir()]
            except OSError:
                continue
            for child in inner:
                if _key(child.name).startswith(wanted):
                    return child
    return None


def _first_child(folder, names):
    if folder is None:
        return None
    return next((folder / n for n in names if (folder / n).is_dir()), None)


def _size(path):
    """(files, bytes) under a path."""
    path = Path(path)
    if path.is_file():
        return 1, path.stat().st_size
    files = size = 0
    for root, _, names in os.walk(path):
        for name in names:
            try:
                size += os.stat(os.path.join(root, name)).st_size
                files += 1
            except OSError:
                continue
    return files, size


def _is_group(folder):
    """A folder of saves rather than a save: it holds only folders (Project Zomboid's Saves/Sandbox/<save>)."""
    try:
        children = list(folder.iterdir())
    except OSError:
        return False
    return bool(children) and all(c.is_dir() for c in children) and all(
        any(g.is_dir() for g in c.iterdir()) or any(g.is_file() for g in c.iterdir()) for c in children[:3]) and not any(
        c.is_file() for c in children)


def saves(folder):
    """Each save, newest first: name, bytes, when modified, whether it looks like an autosave. A save may be a file or a folder;
    a folder holding only folders is a group of saves, each named "group / save"."""
    if folder is None or not Path(folder).is_dir():
        return []
    entries = []
    for child in Path(folder).iterdir():
        if child.is_dir() and _is_group(child) and all(_is_group(c) is False for c in child.iterdir()):
            entries.extend((f"{child.name} / {save.name}", save) for save in child.iterdir())
        else:
            entries.append((child.stem if child.is_file() else child.name, child))
    found = []
    for name, child in entries:
        files, size = _size(child)
        found.append({"name": name, "file": child.name, "bytes": size, "modified": int(child.stat().st_mtime),
                      "auto": bool(AUTOSAVE.search(child.name)), "folder": child.is_dir()})
    return sorted(found, key=lambda s: s["modified"], reverse=True)


def screenshots(folders):
    """Every picture in the folders, newest first: path, bytes, when taken."""
    found = []
    for folder in folders:
        if folder is None or not Path(folder).is_dir():
            continue
        for picture in Path(folder).iterdir():
            if picture.is_file() and picture.suffix.lower() in PICTURES:
                stat = picture.stat()
                found.append({"path": str(picture), "name": picture.name, "bytes": stat.st_size,
                              "taken": int(stat.st_mtime), "source": str(folder)})
    return sorted(found, key=lambda s: s["taken"], reverse=True)


def steam_screenshots(steam, app_id):
    """Steam's own screenshot folders for the game, one per Steam account on this PC."""
    return sorted(Path(steam).glob(f"userdata/*/760/remote/{app_id}/screenshots")) if app_id else []


def space(data):
    """Each folder and file directly in the data folder, largest first."""
    if data is None or not Path(data).is_dir():
        return []
    found = []
    for child in Path(data).iterdir():
        files, size = _size(child)
        found.append({"name": child.name, "files": files, "bytes": size, "folder": child.is_dir()})
    return sorted(found, key=lambda s: s["bytes"], reverse=True)


# ---------------------------------------------------------------- the report

def _when(seconds):
    if not seconds:
        return ""
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def _since(text):
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"--since {text!r} is not a time (2026-11-19 or 2026-11-19T10:00)") from None
    return int((when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp())


def report(name, app_id=None, data=None, saves_folder=None, shots_folder=None, since=None, environ=None):
    """Everything the four parts show, as one dict."""
    steam = steam_root(environ)
    game = find_game(steam, name, app_id)
    data = Path(data) if data else guess_data(name, environ)
    saves_folder = Path(saves_folder) if saves_folder else _first_child(data, SAVE_FOLDERS)
    own_shots = Path(shots_folder) if shots_folder else _first_child(data, SHOT_FOLDERS)
    shot_folders = [own_shots, *steam_screenshots(steam, game["appId"] if game else app_id)]
    items = workshop_items(game) if game else []
    since_seconds = since if since is not None else (game or {}).get("lastPlayed")
    updated = sorted([i for i in items if since_seconds and (i["updated"] or 0) > since_seconds],
                     key=lambda i: i["updated"], reverse=True)
    for item in items:
        item["updatedAt"] = _when(item["updated"])
    found_saves = saves(saves_folder)
    found_shots = screenshots(shot_folders)
    found_space = space(data)
    workshop_bytes = sum(i["bytes"] for i in items)
    return {
        "name": name, "steam": str(steam), "game": game and {**game, "lastUpdatedAt": _when(game["lastUpdated"]),
                                                              "lastPlayedAt": _when(game["lastPlayed"])},
        "places": {"data": str(data) if data else None, "saves": str(saves_folder) if saves_folder else None,
                   "screenshots": [str(f) for f in shot_folders if f is not None and Path(f).is_dir()]},
        "changed": {"since": _when(since_seconds), "sinceLastPlayed": since is None,
                    "gameUpdated": bool(game and since_seconds and (game["lastUpdated"] or 0) > since_seconds),
                    "workshop": updated[:LISTED], "workshopCount": len(updated), "workshopInstalled": len(items)},
        "saves": {"list": found_saves[:LISTED], "count": len(found_saves), "bytes": sum(s["bytes"] for s in found_saves),
                  "autosaves": sum(1 for s in found_saves if s["auto"])},
        "screenshots": {"list": found_shots[:LISTED], "count": len(found_shots), "bytes": sum(s["bytes"] for s in found_shots)},
        "space": {"data": found_space, "dataBytes": sum(s["bytes"] for s in found_space),
                  "install": (game or {}).get("sizeOnDisk"), "workshop": workshop_bytes},
    }


def _size_words(size):
    if size is None:
        return "?"
    for unit, scale in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= scale:
            return f"{size / scale:,.1f} {unit}"
    return f"{size} B"


def _parser():
    p = argparse.ArgumentParser(prog="game-files", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    r = sub.add_parser("report", help="what changed since you last played, saves, screenshots and space, for one game")
    r.add_argument("--name", required=True, help="the game's name, as Steam shows it")
    r.add_argument("--app-id", type=int, help="its Steam app ID, when its name is not enough")
    r.add_argument("--data", help="its data folder (default: guessed from its name)")
    r.add_argument("--saves", help="its saves folder (default: inside the data folder)")
    r.add_argument("--screenshots", help="its own screenshots folder (default: inside the data folder)")
    r.add_argument("--since", help="list Workshop items updated since this time (default: the last launch)")
    s = sub.add_parser("steam-games", help="every game Steam has installed on this PC")
    for parser in (r, s):
        parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        since = _since(getattr(args, "since", None))
    except SystemExit as stop:
        if isinstance(stop.code, str):
            out.write(stop.code + "\n")
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.report == "steam-games":
        games = installed_games(steam_root(environ))
        found = Report(f"Steam games installed: {len(games)}")
        found.section("Games", Table(["App", "Name", "Build", "Last played", "Size"],
                                     [[str(g["appId"]), g["name"], g["buildId"] or "", _when(g["lastPlayed"])[:10],
                                       _size_words(g["sizeOnDisk"])] for g in games]))
        out.write((envelope_text("game-files", found, redact, {"games": games}) if args.json
                   else render_markdown(found, redact)) + "\n")
        return EXIT_OK
    data = report(args.name, args.app_id, args.data, args.saves, args.screenshots, since, environ)
    game = data["game"]
    found = Report(f"{args.name}: what it writes, and what Steam records")
    changed = data["changed"]
    if game is None:
        found.section("What changed", Bullets(["Steam has no installed game by that name; give --app-id."]))
    else:
        lines = [f"Build {game['buildId']}, updated by Steam {game['lastUpdatedAt'][:16]}"
                 + (" (since you last played)" if changed["gameUpdated"] else ""),
                 f"{changed['workshopCount']} of {changed['workshopInstalled']} Workshop items updated since {changed['since'][:16]}"]
        lines += [f"{i['title'] or i['id']}: {i['updatedAt'][:16]}" for i in changed["workshop"][:20]]
        found.section("What changed since you last played", Bullets(lines))
    if data["places"]["saves"]:
        found.section("Saves", Table(["Save", "Size", "Modified", "Auto"],
                                     [[s["name"], _size_words(s["bytes"]), _when(s["modified"])[:16], "yes" if s["auto"] else ""]
                                      for s in data["saves"]["list"][:20]]))
    else:
        found.section("Saves", Bullets(["No saves folder found: give --saves."]))
    shots = data["screenshots"]
    found.section("Screenshots", Bullets([f"{shots['count']} pictures, {_size_words(shots['bytes'])}"
                                          if data["places"]["screenshots"] else "No screenshots folder found."]))
    if data["places"]["data"]:
        found.section("Space", Table(["Folder", "Files", "Size"],
                                     [[s["name"], s["files"], _size_words(s["bytes"])] for s in data["space"]["data"][:15]]))
    else:
        found.section("Space", Bullets(["No data folder found: give --data."]))
    out.write((envelope_text("game-files", found, redact, data) if args.json else render_markdown(found, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"report": {"note": "what changed since you last played, saves, screenshots and space, for one game"},
                        "steam-games": {"note": "every game Steam has installed on this PC"}}}
