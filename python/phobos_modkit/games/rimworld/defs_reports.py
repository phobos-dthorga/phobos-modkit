"""Reports over the RimWorld Def index, as phobos_modkit.report Reports.

Filters ignore case; * and ? are wildcards and _ is an ordinary character. Every report shows Defs as their mods
wrote them: other mods' patches are not applied.
"""
from __future__ import annotations

from ...query import Filters, count as _count, like, rows as _rows
from ...report import Code, Report, Table
from .defs import element_xml

AS_WRITTEN = ("Defs are shown as their mods wrote them; other mods' patches are not applied. A Def's type is its XML "
              "tag: the game also files subclass tags (such as a mod's own ThingDef class) with their base type, "
              "which this index cannot see.")
CHAIN_LIMIT = 20
XML_LINES = 80
# Patches whose xpath names a matching defName: the name match runs once, not once per patch.
PATCHES_NAMING = "p.id IN (SELECT patch_id FROM patch_target WHERE def_name LIKE ? ESCAPE '\\')"


def _meta(conn):
    return dict(conn.execute("SELECT key, value FROM meta").fetchall())


def summary(conn, top=10):
    meta = _meta(conn)
    one = lambda sql: conn.execute(sql).fetchone()[0]
    mods, missing = one("SELECT COUNT(*) FROM mod"), one("SELECT COUNT(*) FROM mod WHERE NOT installed")
    loading, abstract = one("SELECT COUNT(*) FROM def WHERE wins"), one("SELECT COUNT(*) FROM def WHERE abstract")
    unmet = one("SELECT COUNT(*) FROM def WHERE NOT abstract AND def_name IS NOT NULL AND NOT loads")
    replaced = one("SELECT COUNT(*) FROM def WHERE loads AND NOT wins")
    report = Report("Defs across the active mods")
    report.lines.append(f"RimWorld {meta.get('game_version_full') or meta.get('game_version', '?')}: {mods:,} active "
                        f"mods" + (f", {missing:,} of them not installed" if missing else "") + ".")
    report.lines.append(f"{loading:,} Defs load; {replaced:,} more are replaced by a later mod's Def of the same type "
                        f"and name, {unmet:,} wait for a MayRequire mod that is not active, and {abstract:,} are "
                        f"abstract parents. {one('SELECT COUNT(*) FROM patch'):,} patch operations. "
                        f"{one('SELECT COUNT(*) FROM def WHERE implied'):,} of the Defs are made by the game in code "
                        f"(stone floors and carpets); their File says what from.")
    report.lines.append(AS_WRITTEN)
    report.section(f"Def types (top {top})", Table(["Type", "Defs that load"], _rows(conn, """
        SELECT def_type, COUNT(*) FROM def WHERE wins GROUP BY def_type ORDER BY COUNT(*) DESC, def_type""", (), top),
        _count(conn, "SELECT DISTINCT def_type FROM def WHERE wins")))
    contested = """SELECT d.def_type, d.def_name, GROUP_CONCAT(COALESCE(m.name, m.listed_id), ' > '),
                          (SELECT COALESCE(w.name, w.listed_id) FROM def k JOIN mod w ON w.position = k.mod_position
                           WHERE k.wins AND k.def_type = d.def_type AND k.def_name = d.def_name)
                   FROM (SELECT * FROM def WHERE loads ORDER BY mod_position) d JOIN mod m ON m.position = d.mod_position
                   GROUP BY d.def_type, d.def_name HAVING COUNT(DISTINCT d.mod_position) > 1
                   ORDER BY d.def_type, d.def_name"""
    report.section("Names more than one mod defines",
                   "Each row lists the mods in load order; the game keeps the last one's Def.",
                   Table(["Type", "Name", "Mods", "Kept"], _rows(conn, contested, (), top), _count(conn, contested)))
    report.section(f"Mods with the most Defs (top {top})", Table(["Load order", "Mod", "Defs", "Patch operations"],
                   _rows(conn, "SELECT position, COALESCE(name, listed_id), defs, patches FROM mod "
                               "ORDER BY defs DESC, position", (), top)))
    report.section("Problems", Table(["Kind", "Count", "Example"], _rows(conn, """
        SELECT p.kind, COUNT(*), (SELECT COALESCE(m.name, q.mod_position) || ': ' || COALESCE(q.file || ' ', '')
                                         || q.message
                                  FROM problem q LEFT JOIN mod m ON m.position = q.mod_position
                                  WHERE q.kind = p.kind LIMIT 1)
        FROM problem p GROUP BY p.kind ORDER BY COUNT(*) DESC""", (), top)))
    return report


def mods(conn, name=None, top=50):
    f = Filters()
    f.text("COALESCE(name, '')", name, "listed_id")
    sql = f"""SELECT position, COALESCE(name, '(not installed)'), listed_id, source, workshop_id, defs, patches,
                     load_folders FROM mod{f.where} ORDER BY position"""
    report = Report("Active mods in load order")
    report.section("Mods", Table(["Load order", "Mod", "Package ID", "Source", "Workshop ID", "Defs",
                                  "Patch operations", "Load folders"], _rows(conn, sql, f.params, top),
                                 _count(conn, sql, f.params)))
    return report


def _patches_naming(conn, f, top):
    sql = f"""SELECT COALESCE(m.name, m.listed_id), p.operation, p.xpath, p.find_mods, p.load_folder, p.file
              FROM patch p JOIN mod m ON m.position = p.mod_position{f.where} ORDER BY p.mod_position, p.id"""
    return Table(["Mod", "Operation", "Xpath", "Only with mods", "Load folder", "File"],
                 _rows(conn, sql, f.params, top), _count(conn, sql, f.params), widths={2: 160})


def who(conn, name, top=30):
    """Every definition of a Def name (or abstract Name), and every patch whose xpath names it."""
    report = Report(f"Who defines and patches {name}")
    f = Filters()
    f.text("d.def_name", name, "d.name")
    sql = f"""SELECT d.def_type, COALESCE(d.def_name, d.name), COALESCE(m.name, m.listed_id), d.mod_position,
                     CASE WHEN d.wins THEN 'kept' WHEN d.loads THEN 'replaced by a later mod'
                          WHEN d.abstract THEN 'abstract parent' ELSE 'MayRequire not met' END,
                     d.parent, d.label, d.load_folder, d.file
              FROM def d JOIN mod m ON m.position = d.mod_position{f.where} ORDER BY d.def_type, d.mod_position, d.id"""
    report.section("Definitions", Table(["Type", "Name", "Mod", "Load order", "Fate", "Parent", "Label",
                                         "Load folder", "File"], _rows(conn, sql, f.params, top),
                                        _count(conn, sql, f.params)))
    p = Filters()
    p.raw(PATCHES_NAMING, like(name))
    report.section("Patches whose xpath names it", _patches_naming(conn, p, top))
    report.lines.append("Patches are found by the defName in their xpath; a patch that selects Defs another way "
                        "(by class, by parent or with *) is not listed here.")
    report.lines.append(AS_WRITTEN)
    return report


def list_defs(conn, def_type=None, mod=None, name=None, parent=None, include_all=False, top=50):
    f = Filters()
    f.text("d.def_type", def_type)
    f.text("COALESCE(m.name, '')", mod, "m.listed_id")
    f.text("d.def_name", name, "d.name")
    f.text("d.parent", parent)
    if not include_all:
        f.raw("d.wins")
    sql = f"""SELECT d.def_type, COALESCE(d.def_name, d.name), d.label, COALESCE(m.name, m.listed_id), d.parent,
                     d.load_folder, d.file
              FROM def d JOIN mod m ON m.position = d.mod_position{f.where}
              ORDER BY d.def_type, d.def_name, d.mod_position"""
    report = Report("Defs")
    report.lines.append(("Every definition, including replaced, abstract and unloaded ones." if include_all else
                         "The Defs the game keeps; add --all for replaced, abstract and unloaded ones too."))
    report.section("Defs", Table(["Type", "Name", "Label", "Mod", "Parent", "Load folder", "File"],
                                 _rows(conn, sql, f.params, top), _count(conn, sql, f.params)))
    return report


def _xml_block(conn, row_id, max_lines=XML_LINES):
    """(the Def's load position, its ParentName, report blocks showing its XML as its file holds it now, cut at
    max_lines unless that is 0)."""
    row = conn.execute("""SELECT d.def_type, COALESCE(d.def_name, d.name), d.parent, COALESCE(m.name, m.listed_id),
                                 m.folder, d.load_folder, d.file, d.element_index, d.mod_position
                          FROM def d JOIN mod m ON m.position = d.mod_position WHERE d.id = ?""", (row_id,)).fetchone()
    def_type, shown, parent, mod_name, folder, load_folder, file, element_index, position = row
    if element_index < 0:
        return position, None, [f"{def_type} {shown}, from {mod_name}: {file.strip('()')}; it has no XML of its own."]
    text = element_xml(folder, load_folder, file, element_index)
    where = f"{def_type} {shown}, from {mod_name} ({(load_folder + '/') if load_folder else ''}{file})"
    if text is None:
        return position, parent, [f"{where}: the file no longer holds this Def; rebuild the index with --rebuild."]
    lines = text.splitlines()
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... {len(lines) - max_lines:,} more lines (raise --lines, or 0 for all)"]
    return position, parent, [f"{where}:", Code(lines, "xml")]


def show(conn, name, def_type=None, max_lines=XML_LINES):
    """The kept definition of a Def as its file holds it, then each ParentName up the chain; each block is cut at
    max_lines (0 shows every line)."""
    f = Filters()
    f.text("d.def_name", name, "d.name")
    f.text("d.def_type", def_type)
    candidates = conn.execute(f"""SELECT d.id, d.def_type, COALESCE(m.name, m.listed_id) FROM def d
                                  JOIN mod m ON m.position = d.mod_position{f.where}
                                  ORDER BY d.wins DESC, d.loads DESC, d.def_type = 'ThingDef' DESC, d.mod_position DESC,
                                           d.id""", f.params).fetchall()
    report = Report(f"Def {name}")
    if not candidates:
        report.lines.append("No Def or abstract parent has that name. Try `who` with a wildcard, such as *Revolver*.")
        return report
    found = candidates[0]
    others = sorted({f"{t} ({mod})" for _, t, mod in candidates[1:] if t != found[1]})
    if others:
        report.lines.append(f"Showing the {found[1]}. Other types also use this name: {', '.join(others[:8])}; "
                            f"choose one with --type.")
    report.lines.append(AS_WRITTEN)
    report.lines.append("Each parent is the one the game picks: the same Name from the latest mod at or before the "
                        "child's own mod in load order.")
    position, parent, blocks = _xml_block(conn, found[0], max_lines)
    report.section("The Def", *blocks)
    seen = set()
    while parent and parent not in seen and len(seen) < CHAIN_LIMIT:
        seen.add(parent)
        row = conn.execute("SELECT id FROM def WHERE name = ? AND registers AND mod_position <= ? "
                           "ORDER BY mod_position DESC, id ASC LIMIT 1", (parent, position)).fetchone()
        if row is None:
            report.section(f"Parent {parent}", "No active mod at or before this one in load order gives a Def this "
                                               "Name: the game reports the parent as missing.")
            break
        position, next_parent, blocks = _xml_block(conn, row[0], max_lines)
        report.section(f"Parent {parent}", *blocks)
        parent = next_parent
    return report


def patches(conn, target=None, mod=None, def_type=None, operation=None, top=50):
    f = Filters()
    if target:
        f.raw(PATCHES_NAMING, like(target))
    f.text("COALESCE(m.name, '')", mod, "m.listed_id")
    f.text("p.def_type", def_type)
    f.text("p.operation", operation)
    report = Report("Patch operations")
    report.lines.append("Every patch element with an xpath, in load order. Only with mods: the mods a "
                        "PatchOperationFindMod around it names.")
    report.section("Patches", _patches_naming(conn, f, top))
    return report


def sql(conn, query, top=100):
    cursor = conn.execute(query)
    headers = [d[0] for d in cursor.description or []]
    rows = [tuple(r) for r in cursor.fetchmany(top + 1)]
    report = Report("Query")
    report.lines.append("Tables: mod, def, patch, patch_target, problem, meta. Views: def_view, patch_view.")
    if len(rows) > top:
        report.lines.append(f"Only the first {top:,} rows are shown; raise --top to see more.")
    report.section("Result", Table(headers, rows[:top]))
    return report

