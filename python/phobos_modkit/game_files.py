"""game-files: what a game itself writes and what Steam records about it, for any Steam game (1.46.0).

    game-files report --name NAME [--app-id N] [--data DIR] [--saves DIR] [--screenshots DIR] [--since TIME]
    game-files steam-games                       every game Steam has installed on this PC
    game-files screenshots --name NAME [--app-id N] [--data DIR] [--screenshots DIR]   only the screenshots, quickly (1.59.0)

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

from . import cache as derived
from .manifest import READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE = 0, 2
STEAM = ("steamPath", "PHOBOS_STEAM")
PICTURES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})
SAVE_FOLDERS = ("Saves", "saves", "save", "Save")
SHOT_FOLDERS = ("Screenshots", "screenshots", "Screenshot")
AUTOSAVE = re.compile(r"auto", re.IGNORECASE)
LISTED = 200
SHOTS_LISTED = 2000   # screenshots one `screenshots` answer lists (1.59.0); the counts cover every one
# The launches kept per game (1.51.0): Steam records only the latest, so while a game runs "since you last played" would mean
# since this launch. Each report remembers the launch it sees; --since previous then means the one before.
LAUNCHES_KEPT = 30
PREVIOUS = "previous"
WORKSHOP_TITLE_FILES = (("About/About.xml", re.compile(r"<name>\s*(.*?)\s*</name>", re.S)),
                        ("mod.info", re.compile(r"^name\s*=\s*(.+)$", re.M)))
TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')
# Guessing a game's data folder (1.58.0; agent defaults, the owner confirms each guess when adding a game in D'thorga Companion).
DOCUMENTS = "PHOBOS_DOCUMENTS"
SHELL_FOLDERS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
GUESSES_KEPT = 3
MIN_WORD = 7          # letters a last word needs before a folder named for it alone counts ("Zomboid"; not "Engine", "Studio")
MIN_FIRST = 8         # letters a first word needs for a folder starting with it ("Automation"; not "Project", "Euro")
MIN_BARE = 8          # letters a name needs, digits aside, before its numbering may differ ("FarmingSimulator2025")
MIN_TAIL, MAX_TAIL = 3, 6    # letters a folder may add after the game's first word ("AutomationGame"; not "Projects")
# Folders never looked inside for a game's: temporary files, and mod managers' and engines' own copies named for games
# (Vortex\farmingsimulator25 outranked Farming Simulator's real folder on the owner's PC).
NOT_MAKERS = frozenset({"temp", "tmp", "cache", "packages", "vortex", "modorganizer", "modorganizer2", "nexusmodmanager",
                        "unrealengine", "unity", "nvidia", "nvidiacorporation", "microsoft", "google", "mozilla"})
SIDE_FOLDERS = frozenset({"mods", "mod", "backup", "backups", "old", "tools", "editor", "server", "dedicatedserver"})


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

def documents_folder(environ=None):
    """The person's Documents folder where Windows keeps it, which may be moved off the home folder (the owner's is in their
    SynologyDrive, 20 Nov 2026, so Documents\\My Games was never found). PHOBOS_DOCUMENTS names it; else Windows' own record of
    it, read only for this process's environment; None when neither says."""
    environ = os.environ if environ is None else environ
    if environ.get(DOCUMENTS):
        return Path(environ[DOCUMENTS])
    if sys.platform != "win32" or environ is not os.environ:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SHELL_FOLDERS) as key:
            value, _ = winreg.QueryValueEx(key, "Personal")
    except OSError:
        return None
    return Path(os.path.expandvars(value)) if value else None


def _homes(environ=None):
    environ = os.environ if environ is None else environ
    home = Path(environ.get("USERPROFILE") or environ.get("HOME") or Path.home())
    documents = documents_folder(environ)
    found = [home / "AppData" / "LocalLow",
             *([documents / "My Games", documents] if documents else []),
             home / "Documents" / "My Games", home / "AppData" / "Local", home / "AppData" / "Roaming", home / "Documents",
             home / ".config" / "unity3d", home / ".local" / "share", home]
    unique = []
    for folder in found:
        if folder.is_dir() and folder not in unique:
            unique.append(folder)
    return unique


def _key(text):
    return re.sub(r"[^a-z0-9]", "", str(text).casefold())


def _match(folder_name, name):
    """How a folder's name matches a game's: (score, reason in words), or None. Higher is surer (1.58.0)."""
    folder, wanted = _key(folder_name), _key(name)
    if not folder or not wanted:
        return None
    if folder == wanted:
        return 100, "named for the game"
    if folder.startswith(wanted):
        tail = folder[len(wanted):]
        if tail in SIDE_FOLDERS:                                  # My Games\Project Zomboid (mods): the person's own, not the game's
            return 40, f"named for the game's {tail}"
        return 90, "named for the game, with more after"
    bare_folder, bare_wanted = re.sub(r"[0-9]", "", folder), re.sub(r"[0-9]", "", wanted)
    if len(bare_wanted) >= MIN_BARE and bare_folder == bare_wanted:
        return 80, "named for the game, numbered differently"     # Farming Simulator 25: FarmingSimulator2025
    words = [_key(w) for w in str(name).split() if _key(w)]
    if len(folder) >= MIN_WORD and len(words) > 1 and words[-1] == folder:
        return 70, "named for the game's last word"               # Project Zomboid: Zomboid
    if words and len(words[0]) >= MIN_FIRST and folder.startswith(words[0]) and \
            MIN_TAIL <= len(folder) - len(words[0]) <= MAX_TAIL:
        return 60, "starts with the game's first word"            # Automation - The Car Company Tycoon Game: AutomationGame
    return None


def _folders(folder):
    """The folders directly in a folder, by name; scandir, so Windows answers each without a second look (AppData\\Local holds
    80,000 folders one level down on the owner's PC)."""
    try:
        with os.scandir(folder) as entries:
            found = [Path(e.path) for e in entries if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    return sorted(found, key=lambda f: f.name.casefold())


def _scan(environ=None):
    """Every folder in the usual homes, and every folder one level inside each (a maker's folder holding the game's), read once:
    [(path, name, maker or None)]. Hidden folders, temporary files and mod managers' copies are not looked inside."""
    found = []
    for home in _homes(environ):
        children = _folders(home)
        found.extend((child, child.name, None) for child in children)
        for maker in children:
            if maker.name.startswith(".") or _key(maker.name) in NOT_MAKERS:
                continue
            found.extend((child, child.name, maker.name) for child in _folders(maker))
    return found


def guess_candidates(name, environ=None, scanned=None):
    """Up to GUESSES_KEPT folders that may be the game's data folder, surest first, each {path, score, reason}. A folder inside a
    maker's folder scores a little lower than one named for the game in a home itself. `scanned` reuses one `_scan`."""
    found = {}
    for path, folder_name, maker in (_scan(environ) if scanned is None else scanned):
        matched = _match(folder_name, name)
        if matched is None:
            continue
        score, reason = matched
        if maker is not None:
            score, reason = score - 5, f"{reason}, inside {maker}"
        key = str(path)
        if key not in found or found[key]["score"] < score:
            found[key] = {"path": key, "score": score, "reason": reason}
    ranked = sorted(found.values(), key=lambda c: -c["score"])            # stable: the homes' order breaks ties
    return ranked[:GUESSES_KEPT]


def guess_data(name, environ=None):
    """The game's data folder, guessed from the usual homes by its name: the surest of `guess_candidates`, as a folder named for it,
    or for its maker with one inside named for it (LocalLow\\Ludeon Studios\\RimWorld by Ludeon Studios). None when nothing matches."""
    found = guess_candidates(name, environ)
    return Path(found[0]["path"]) if found else None


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


def launches_file(app_id, environ=None):
    return derived.folder("game-files", None, environ) / f"launches-{app_id}.json"


def remember_launch(app_id, last_played, environ=None):
    """Every launch of the game this kit has seen, oldest first, with this one added; kept in the kit's cache."""
    import json
    path = launches_file(app_id, environ)
    try:
        seen = [int(t) for t in json.loads(path.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        seen = []
    if last_played and last_played not in seen:
        seen = sorted(seen + [last_played])[-LAUNCHES_KEPT:]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(seen), encoding="utf-8")
        except OSError:
            pass                                    # only a memory: the next report tries again
    return seen


def previous_launch(seen, last_played):
    """The launch before the latest, as far as the kit has seen; None when it has seen no earlier one."""
    earlier = [t for t in seen if last_played and t < last_played]
    return earlier[-1] if earlier else None


def _since(text):
    if not text:
        return None
    if text == PREVIOUS:
        return PREVIOUS
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"--since {text!r} is not a time (2026-11-19 or 2026-11-19T10:00)") from None
    return int((when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp())


def shots_only(name, app_id=None, data=None, shots_folder=None, environ=None):
    """Only the screenshots (1.59.0), for D'thorga Companion's gallery: the same folders the report reads, without sizing the
    data folder (gigabytes on the owner's RimWorld) or the saves. Up to SHOTS_LISTED, newest first."""
    steam = steam_root(environ)
    game = find_game(steam, name, app_id)
    data = Path(data) if data else guess_data(name, environ)
    own_shots = Path(shots_folder) if shots_folder else _first_child(data, SHOT_FOLDERS)
    folders = [own_shots, *steam_screenshots(steam, game["appId"] if game else app_id)]
    found = screenshots(folders)
    return {"name": name, "folders": [str(f) for f in folders if f is not None and Path(f).is_dir()],
            "list": found[:SHOTS_LISTED], "count": len(found), "bytes": sum(s["bytes"] for s in found)}


def report(name, app_id=None, data=None, saves_folder=None, shots_folder=None, since=None, environ=None):
    """Everything the four parts show, as one dict."""
    steam = steam_root(environ)
    game = find_game(steam, name, app_id)
    data = Path(data) if data else guess_data(name, environ)
    saves_folder = Path(saves_folder) if saves_folder else _first_child(data, SAVE_FOLDERS)
    own_shots = Path(shots_folder) if shots_folder else _first_child(data, SHOT_FOLDERS)
    shot_folders = [own_shots, *steam_screenshots(steam, game["appId"] if game else app_id)]
    items = workshop_items(game) if game else []
    last_played = (game or {}).get("lastPlayed")
    seen = remember_launch(game["appId"], last_played, environ) if game else []
    previous = previous_launch(seen, last_played)
    if since == PREVIOUS:
        since_seconds = previous or last_played
    else:
        since_seconds = since if since is not None else last_played
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
                    "sincePrevious": since == PREVIOUS and previous is not None, "previousLaunchAt": _when(previous),
                    "launchesSeen": len(seen),
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
    r.add_argument("--since", help="list Workshop items updated since this time (default: the last launch); 'previous' for the "
                                   "launch before the last, as far as the kit has seen (1.51.0: while the game runs)")
    s = sub.add_parser("steam-games", help="every game Steam has installed on this PC")
    g = sub.add_parser("screenshots", help="only one game's screenshots, quickly: the same folders as the report")
    g.add_argument("--name", required=True, help="the game's name, as Steam shows it")
    g.add_argument("--app-id", type=int, help="its Steam app ID, when its name is not enough")
    g.add_argument("--data", help="its data folder (default: guessed from its name)")
    g.add_argument("--screenshots", help="its own screenshots folder (default: inside the data folder)")
    for parser in (r, s, g):
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
        scanned = _scan(environ)
        for game in games:
            game["dataGuesses"] = guess_candidates(game["name"], environ, scanned)
        found = Report(f"Steam games installed: {len(games)}")
        found.section("Games", Table(["App", "Name", "Build", "Last played", "Size", "Data folder (surest guess)"],
                                     [[str(g["appId"]), g["name"], g["buildId"] or "", _when(g["lastPlayed"])[:10],
                                       _size_words(g["sizeOnDisk"]),
                                       g["dataGuesses"][0]["path"] if g["dataGuesses"] else "none found"] for g in games]))
        out.write((envelope_text("game-files", found, redact, {"games": games}) if args.json
                   else render_markdown(found, redact)) + "\n")
        return EXIT_OK
    if args.report == "screenshots":
        shots = shots_only(args.name, args.app_id, args.data, args.screenshots, environ)
        found = Report(f"{args.name}: {shots['count']} screenshots, {_size_words(shots['bytes'])}")
        found.section("Newest", Bullets([f"{_when(s['taken'])[:16]}  {s['name']}" for s in shots["list"][:20]]
                                        if shots["folders"] else ["No screenshots folder found: give --data or --screenshots."]))
        out.write((envelope_text("game-files", found, redact, shots) if args.json else render_markdown(found, redact)) + "\n")
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
                        "steam-games": {"note": "every game Steam has installed on this PC"},
                        "screenshots": {"note": "only one game's screenshots, quickly, for a gallery"}}}
