"""RimWorld's Defs and patches across the active mods, indexed into SQLite in the kit's cache.

The index holds every top-level Def the active mods' load folders hold (as written: other mods' patches are not
applied) and every patch operation with an xpath. For each Def type and name it marks the definition the game keeps:
in the 1.7 DefDatabase a later mod's Def replaces an earlier mod's with the same type and name, and a second Def of
that name inside one mod is skipped (summarised from the game code, November 2026). Abstract Defs and Defs whose
MayRequire is not met never load. Defs the game makes in code from other Defs (stone floors, carpets) are added as
rows marked `implied` (phobos_modkit.games.rimworld.implied). For ParentName, a child takes the same-Named parent from the latest mod at or
before its own in load order (the game's XmlInheritance); `registers` marks the nodes that can be parents.

Provenance (phobos_modkit.cache): ModsConfig.xml, Steam's Workshop manifest and the game's Version.txt by size and
time, a fingerprint of every XML file in the game's Mods folder, and the kit's version. Changing any rebuilds the
index on its next use. A Workshop file edited by hand, without Steam, is not noticed: use --rebuild.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET

from ... import __version__
from ... import cache as derived
from . import implied as generated
from .loading import bare_id, load_folders, may_load, may_register_parent, read_mods_config, resolve_active, xml_files
from .mods import ModIndex, default_roots

CACHE_FOLDER = "rimworld-defs"
INDEX_NAME = "defs.sqlite"
INDEX_FORMAT = "3"   # raise when the tables change
MANIFEST_NAME = "appworkshop_294100.acf"
DEF_NAME_IN_XPATH = re.compile(r"""defName\s*=\s*["']([^"']+)["']""")
DEF_TYPE_IN_XPATH = re.compile(r"^/?Defs/([A-Za-z_*][\w.]*)")

TABLES = """
CREATE TABLE mod (position INTEGER PRIMARY KEY, listed_id TEXT NOT NULL, package_id TEXT, name TEXT, source TEXT,
                  workshop_id TEXT, folder TEXT, load_folders TEXT, installed INTEGER NOT NULL,
                  defs INTEGER NOT NULL DEFAULT 0, patches INTEGER NOT NULL DEFAULT 0);
CREATE TABLE def (id INTEGER PRIMARY KEY, mod_position INTEGER NOT NULL, def_type TEXT NOT NULL, def_name TEXT,
                  name TEXT, parent TEXT, abstract INTEGER NOT NULL, class TEXT, label TEXT, may_require TEXT,
                  may_require_any TEXT, loads INTEGER NOT NULL, wins INTEGER NOT NULL DEFAULT 0,
                  registers INTEGER NOT NULL,
                  load_folder TEXT NOT NULL, file TEXT NOT NULL, element_index INTEGER NOT NULL,
                  implied INTEGER NOT NULL DEFAULT 0, made_from TEXT);
CREATE TABLE patch (id INTEGER PRIMARY KEY, mod_position INTEGER NOT NULL, operation TEXT, xpath TEXT NOT NULL,
                    def_type TEXT, find_mods TEXT, may_require TEXT, load_folder TEXT NOT NULL, file TEXT NOT NULL);
CREATE TABLE patch_target (patch_id INTEGER NOT NULL, def_name TEXT NOT NULL);
CREATE TABLE problem (mod_position INTEGER, kind TEXT NOT NULL, file TEXT, message TEXT NOT NULL);
CREATE VIEW def_view AS
    SELECT d.*, m.name AS mod_name, m.package_id FROM def d JOIN mod m ON m.position = d.mod_position;
CREATE VIEW patch_view AS
    SELECT p.*, m.name AS mod_name, m.package_id FROM patch p JOIN mod m ON m.position = p.mod_position;
"""
INDEXES = """
CREATE INDEX def__def_name ON def (def_name);
CREATE INDEX def__name ON def (name);
CREATE INDEX def__type_name ON def (def_type, def_name);
CREATE INDEX patch_target__def_name ON patch_target (def_name);
"""
WINNERS = """
UPDATE def SET wins = 1 WHERE id IN (
    SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY def_type, def_name
                                                 ORDER BY mod_position DESC, id ASC) AS rank
                    FROM def WHERE loads = 1 AND def_name IS NOT NULL)
    WHERE rank = 1)
"""


class DefsError(RuntimeError):
    pass


@dataclass
class Install:
    game: Path
    workshop: Path
    config: Path

    @property
    def mods_config(self):
        return Path(self.config) / "ModsConfig.xml"

    @property
    def manifest(self):
        return Path(self.workshop).parents[1] / MANIFEST_NAME

    @property
    def version_file(self):
        return Path(self.game) / "Version.txt"


@dataclass
class Built:
    index: Path
    mods: int
    defs: int
    patches: int
    problems: int
    seconds: float
    implied: int = 0


def index_path(cache):
    return Path(cache) / INDEX_NAME


def _local_fingerprint(game):
    """A hash of every XML file's path, size and time in the game's Mods folder: the mods a modder edits in place."""
    digest = hashlib.sha256()
    mods = Path(game) / "Mods"
    if mods.is_dir():
        for folder, dirs, files in os.walk(mods):
            dirs.sort()
            for name in sorted(files):
                if name.lower().endswith(".xml"):
                    path = Path(folder) / name
                    info = path.stat()
                    digest.update(f"{path.relative_to(mods).as_posix()}|{info.st_size}|{info.st_mtime_ns}\n".encode())
    return digest.hexdigest()[:derived.DIGEST_LENGTH]


def provenance(install):
    """The meta keys a current index of this install carries."""
    if not install.mods_config.is_file():
        raise DefsError(f"No ModsConfig.xml in {install.config}. Name the folder with --config.")
    keys = {"index_format": INDEX_FORMAT, "kit_version": __version__, **derived.file_stamp(install.mods_config,
                                                                                         "modsconfig")}
    for path, prefix in ((install.manifest, "workshop_manifest"), (install.version_file, "game_version_file")):
        if path.is_file():
            keys.update(derived.file_stamp(path, prefix))
    keys["local_mods_sha"] = _local_fingerprint(install.game)
    return keys


def _text(element, tag):
    found = element.find(tag)
    text = (found.text or "").strip() if found is not None else ""
    return text or None


def _parse(path):
    try:
        return ET.parse(path).getroot(), None
    except (ET.ParseError, OSError, UnicodeDecodeError) as problem:
        return None, str(problem)


def patch_operations(root):
    """(operation class, xpath, enclosing FindMod mods, MayRequire) for every element with an <xpath> in a patch."""
    found = []

    def walk(element, find_mods):
        cls = element.get("Class") or ""
        if cls.endswith("PatchOperationFindMod"):
            find_mods = find_mods + [li.text.strip() for li in element.findall("mods/li") if li.text]
        xpath = element.find("xpath")
        if xpath is not None and (xpath.text or "").strip():
            found.append((cls or element.tag, xpath.text.strip(), ", ".join(find_mods),
                          element.get("MayRequire") or ""))
        for child in element:
            if isinstance(child.tag, str) and child.tag != "xpath":
                walk(child, find_mods)

    for operation in root:
        if isinstance(operation.tag, str):
            walk(operation, [])
    return found


def build(install, cache, scan=None):
    """Index every active mod's Defs and patches into cache/defs.sqlite. Returns Built; raises DefsError."""
    started = time.monotonic()
    meta = provenance(install)
    version, full_version, active_ids = read_mods_config(install.mods_config)
    installed = (scan or (lambda: ModIndex.scan(default_roots(install.game, install.workshop)).mods))()
    active = resolve_active(installed, active_ids)
    active_bare = {bare_id(a.listed_id) for a in active}
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    index = index_path(cache)
    partial = index.with_suffix(".partial")
    derived.remove(partial)
    counts = {"defs": 0, "patches": 0, "problems": 0}
    facts = generated.Facts()
    with closing(sqlite3.connect(partial)) as conn:
        conn.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;" + TABLES)

        def problem(position, kind, file, message):
            conn.execute("INSERT INTO problem VALUES (?, ?, ?, ?)", (position, kind, file, message))
            counts["problems"] += 1

        for a in active:
            mod = a.mod
            if mod is None:
                conn.execute("INSERT INTO mod (position, listed_id, installed) VALUES (?, ?, 0)",
                             (a.position, a.listed_id))
                problem(a.position, "missing", None, f"{a.listed_id} is active in ModsConfig.xml but not installed")
                continue
            folders = load_folders(mod.folder, version, active_bare)
            rel = lambda folder: folder.relative_to(mod.folder).as_posix() if folder != mod.folder else ""
            defs = patches = 0
            def_files, skipped_defs = xml_files(folders, "Defs")
            patch_files, skipped_patches = xml_files(folders, "Patches")
            for skipped, winner in skipped_defs + skipped_patches:
                problem(a.position, "shadowed", skipped.relative_to(mod.folder).as_posix(),
                        f"never loaded: the game loads {winner.relative_to(mod.folder).as_posix()} instead")
            for folder, path in def_files:
                root, error = _parse(folder / path)
                if root is None:
                    problem(a.position, "unreadable", f"{rel(folder)}/{path}".lstrip("/"), error)
                    continue
                if root.tag != "Defs":
                    continue
                rows = []
                for position, element in enumerate(e for e in root if isinstance(e.tag, str)):
                    abstract = (element.get("Abstract") or "").lower() == "true"
                    def_name = _text(element, "defName")
                    loads = int(not abstract and def_name is not None and may_load(element, active_bare))
                    registers = int(bool(element.get("Name")) and may_register_parent(element, active_bare))
                    facts.add((a.position, rel(folder), path, position), element, registers)
                    rows.append((a.position, element.tag, def_name, element.get("Name"), element.get("ParentName"),
                                 int(abstract), element.get("Class"), _text(element, "label"),
                                 element.get("MayRequire"), element.get("MayRequireAnyOf"), loads, registers,
                                 rel(folder), path, position))
                conn.executemany("INSERT INTO def (mod_position, def_type, def_name, name, parent, abstract, class, "
                                 "label, may_require, may_require_any, loads, registers, load_folder, file, "
                                 "element_index) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
                defs += len(rows)
            for folder, path in patch_files:
                root, error = _parse(folder / path)
                if root is None:
                    problem(a.position, "unreadable", f"{rel(folder)}/{path}".lstrip("/"), error)
                    continue
                for operation, xpath, find_mods, may_require in patch_operations(root):
                    type_match = DEF_TYPE_IN_XPATH.match(xpath)
                    cursor = conn.execute("INSERT INTO patch (mod_position, operation, xpath, def_type, find_mods, "
                                          "may_require, load_folder, file) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                          (a.position, operation, xpath, type_match.group(1) if type_match else None,
                                           find_mods or None, may_require or None, rel(folder), path))
                    conn.executemany("INSERT INTO patch_target VALUES (?, ?)",
                                     [(cursor.lastrowid, n) for n in dict.fromkeys(DEF_NAME_IN_XPATH.findall(xpath))])
                    patches += 1
            conn.execute("INSERT INTO mod VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                         (a.position, a.listed_id, mod.package_id, mod.name, mod.source, mod.workshop_id or None,
                          str(mod.folder), ", ".join(rel(f) or "(root)" for f in folders), defs, patches))
            counts["defs"] += defs
            counts["patches"] += patches
        conn.executescript(WINNERS)
        made = generated.generate(conn, facts)
        conn.executemany("INSERT INTO def (mod_position, def_type, def_name, abstract, loads, registers, load_folder, "
                         "file, element_index, implied, made_from) VALUES (?, ?, ?, 0, 1, 0, '', ?, -1, 1, ?)",
                         [(position, def_type, name, f"(made by the game from {source})", source)
                          for def_type, name, position, source in made])
        conn.executescript("UPDATE def SET wins = 0;" + WINNERS + ";" + INDEXES)
        derived.write_meta(conn, {**meta, "game_version": version, "game_version_full": full_version,
                                  "source": "ModsConfig.xml", "active_mods": len(active)})
        conn.commit()
    derived.remove(index)
    os.replace(partial, index)
    return Built(index, len(active), counts["defs"], counts["patches"], counts["problems"],
                 time.monotonic() - started, len(made))


def ensure(install, cache, rebuild=False, scan=None):
    """(index path, Built or None): the current index, built only when missing or stale."""
    index = index_path(cache)
    if not rebuild and derived.is_current(index, provenance(install)):
        return index, None
    built = build(install, cache, scan)
    return built.index, built


def element_xml(index_row_folder, load_folder, file, element_index):
    """The XML of one indexed Def as its file holds it now, or None when the file no longer has it."""
    path = Path(index_row_folder) / load_folder / file if load_folder else Path(index_row_folder) / file
    root, _ = _parse(path)
    if root is None:
        return None
    elements = [e for e in root if isinstance(e.tag, str)]
    if element_index >= len(elements):
        return None
    ET.indent(elements[element_index])
    return ET.tostring(elements[element_index], encoding="unicode").strip()
