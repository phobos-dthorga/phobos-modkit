"""Defs with every XML patch applied, from a file a running game wrote, compared with the Defs as written.

The game patches the combined XML of every active mod and then lets it go, so a static index (defs.py) can only show Defs
as their mods wrote them. A mod can keep that document and write it out (phobos-rimworld's D'thorga Framework does, on a
developer's request): a <Defs> root holding every Def node after all patches, before inheritance, with gameVersion,
written and activeMods attributes on the root. This module streams such a file into SQLite in the kit's cache, and builds
the report that shows one Def as patched and what the patches changed.
"""
from __future__ import annotations

from contextlib import closing
import difflib
from pathlib import Path
import sqlite3
import time
import xml.etree.ElementTree as ET

from ... import __version__
from ... import cache as derived
from ...report import Code, Report
from .defs import element_xml, local_mods_changed_since

INDEX_NAME = "patched-defs.sqlite"
INDEX_FORMAT = "1"
FOLDERS_NAMED = 5
SCHEMA = """
CREATE TABLE pdef (id INTEGER PRIMARY KEY, def_type TEXT NOT NULL, def_name TEXT, name TEXT, parent TEXT,
                   abstract INTEGER NOT NULL, xml TEXT NOT NULL);
CREATE INDEX pdef_name ON pdef (def_name COLLATE NOCASE);
CREATE INDEX pdef_abstract_name ON pdef (name COLLATE NOCASE);
"""


class PatchedError(ValueError):
    pass


def tidy(element):
    """One Def's XML in a fixed layout (two-space indents, no stray whitespace), so two copies compare line by line."""
    for node in element.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    ET.indent(element)
    return ET.tostring(element, encoding="unicode").strip()


def provenance(dump):
    return {"index_format": INDEX_FORMAT, "kit_version": __version__, **derived.file_stamp(dump, "dump")}


def ensure(dump, cache):
    """The index of a patched-Defs file, built when missing or when the file changed. Returns (path, seconds or None)."""
    dump = Path(dump)
    if not dump.is_file():
        raise PatchedError(f"No patched-Defs file at {dump}. A mod has to write one from a running game first (in "
                           "phobos-rimworld, D'thorga Framework's dev setting); then name it with --dump.")
    target = Path(cache) / INDEX_NAME
    expected = provenance(dump)
    if derived.is_current(target, expected):
        return target, None
    started = time.monotonic()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".building")
    derived.remove(temporary)
    root_attributes, count = {}, 0
    with closing(sqlite3.connect(temporary)) as conn:
        conn.executescript(SCHEMA)
        depth = 0
        try:
            for event, element in ET.iterparse(str(dump), events=("start", "end")):
                if event == "start":
                    depth += 1
                    if depth == 1:
                        root_attributes = dict(element.attrib)
                    continue
                depth -= 1
                if depth != 1:
                    continue
                conn.execute("INSERT INTO pdef (def_type, def_name, name, parent, abstract, xml) VALUES (?, ?, ?, ?, ?, ?)",
                             (element.tag, (element.findtext("defName") or "").strip() or None, element.get("Name"),
                              element.get("ParentName"), int((element.get("Abstract") or "").lower() == "true"),
                              tidy(element)))
                count += 1
                element.clear()
        except ET.ParseError as error:
            raise PatchedError(f"{dump} is not readable XML ({error}); write it again from the game") from None
        derived.write_meta(conn, {**expected, **{f"dump_{k}": v for k, v in root_attributes.items()}, "defs": count})
        conn.commit()
    derived.remove(target)
    temporary.replace(target)
    return target, time.monotonic() - started


def _written(conn, def_type, name, abstract):
    """The definition the game keeps, as written, from the Def index: (xml, mod name) or None."""
    column = "d.name" if abstract else "d.def_name"
    row = conn.execute(f"""SELECT m.folder, d.load_folder, d.file, d.element_index, COALESCE(m.name, m.listed_id)
                           FROM def d JOIN mod m ON m.position = d.mod_position
                           WHERE {column} = ? AND d.def_type = ? AND d.element_index >= 0
                           ORDER BY d.wins DESC, d.mod_position DESC LIMIT 1""", (name, def_type)).fetchone()
    if row is None:
        return None
    text = element_xml(*row[:4])
    if text is None:
        return None
    return tidy(ET.fromstring(text)), row[4]


def out_of_date(install, meta, defs_conn):
    """Why the file may no longer match the game as it stands: plain phrases, none when nothing moved since it was written."""
    reasons = []
    active = defs_conn.execute("SELECT COUNT(*) FROM mod WHERE installed").fetchone()[0]
    listed = str(meta.get("dump_activeMods", ""))
    if listed.isdigit() and int(listed) != active:
        reasons.append(f"it was written with {listed} active mods and {active} are active now")
    version = meta.get("dump_gameVersion")
    if version and install.version_file.is_file():
        now = install.version_file.read_text(encoding="utf-8", errors="replace").strip()
        if now and now != version:
            reasons.append(f"the game is now {now}")
    written = int(meta.get("dump_mtime_ns") or 0)
    for path, what in ((install.mods_config, "the mod list has been saved since"),
                       (install.manifest, "Steam's Workshop manifest is newer, so a Workshop mod may have updated")):
        if path.is_file() and path.stat().st_mtime_ns > written:
            reasons.append(what)
    changed = local_mods_changed_since(install.game, written)
    if changed:
        more = f" and {len(changed) - FOLDERS_NAMED} more" if len(changed) > FOLDERS_NAMED else ""
        reasons.append(f"XML changed since in the game's Mods folder ({', '.join(changed[:FOLDERS_NAMED])}{more})")
    return reasons


def show(defs_conn, patched_index, name, def_type=None, max_lines=80, install=None):
    """A Def as every patch left it, and the difference from the definition as written."""
    meta = derived.read_meta(patched_index)
    with closing(derived.open_read_only(patched_index)) as conn:
        sql = "SELECT def_type, def_name, name, abstract, xml FROM pdef WHERE (def_name = ? COLLATE NOCASE OR name = ? COLLATE NOCASE)"
        params = [name, name]
        if def_type:
            sql += " AND def_type = ?"
            params.append(def_type)
        rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    report = Report(f"Def {name}, with every patch applied")
    report.lines.append(f"From the patched-Defs file written {meta.get('dump_written', '(unknown time)')} by game "
                        f"{meta.get('dump_gameVersion', '(unknown)')} with {meta.get('dump_activeMods', '?')} active mods. "
                        "Patches are applied; inheritance is not (ParentName is shown, its values are not merged in).")
    reasons = out_of_date(install, meta, defs_conn) if install is not None else []
    if reasons:
        report.lines.append("This file may be out of date: " + "; ".join(reasons) + ". These compare file times and counts, "
                            "and the change may not touch this Def; have the game write the file again to be sure.")
    if not rows:
        report.lines.append("No Def in the file has that name. A Def the game makes in code is not in the file; check the "
                            "spelling with the who report.")
        return report
    types = sorted({r[0] for r in rows})
    if len(types) > 1 and not def_type:
        report.lines.append(f"Several types use this name ({', '.join(types)}); showing the last, choose with --type.")
    def_type_found, def_name, abstract_name, abstract, xml = rows[-1]
    if len(rows) > 1:
        report.lines.append(f"{len(rows)} definitions in the file; showing the last, which the game keeps.")
    lines = xml.splitlines()
    shown = lines if not max_lines or len(lines) <= max_lines else lines[:max_lines] + [
        f"... {len(lines) - max_lines} more lines (raise --lines, or 0 for all)"]
    report.section("As patched", Code(shown, "xml"))
    written = _written(defs_conn, def_type_found, abstract_name if abstract else def_name, abstract)
    if written is None:
        report.section("What the patches changed",
                       "No definition as written was found to compare with: a patch may have added this Def "
                       "(PatchOperationAdd), or the Def index is older than the file (rebuild it with --rebuild).")
        return report
    written_xml, mod = written
    diff = list(difflib.unified_diff(written_xml.splitlines(), lines, fromfile=f"as written ({mod})",
                                     tofile="after every patch", lineterm="", n=2))
    if not diff:
        report.section("What the patches changed", "Nothing: the Def is as its mod wrote it.")
    else:
        report.section("What the patches changed", Code(diff, "diff"))
    return report
