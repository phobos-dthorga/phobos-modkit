"""Reports over a RimWorld save index: each returns a phobos_modkit.report.Report (Markdown or JSON).

All filters take plain text, matched without regard to case; * and ? are wildcards. Tables are cut at `top` rows
and say how many there were in all.
"""
from __future__ import annotations

from ...query import Filters, count as _count, like, rows as _rows
from ...report import Report, Section, Table

TICKS_PER_DAY = 60000          # RimWorld: one in-game day
TICKS_PER_YEAR = 60 * TICKS_PER_DAY
PLAYER_FACTION_PREFIX = "Player"  # the player's faction defs are PlayerColony, PlayerTribe and modded Player* ones


def _section(heading, headers, rows, total=None):
    """A report section holding one table."""
    return Section(heading, [Table(headers, rows, total)])


def summary(conn, top=10):
    game = conn.execute("SELECT game_version, scenario, ticks_game, play_seconds FROM game").fetchone() or (None,) * 4
    version, scenario, ticks, play_seconds = game
    report = Report("Save summary")
    if ticks is not None:
        report.lines.append(f"RimWorld {version}, scenario \"{scenario}\". {ticks // TICKS_PER_DAY:,} in-game days "
                            f"({ticks / TICKS_PER_YEAR:.1f} years) since the colony began"
                            + (f"; {play_seconds / 3600:,.0f} hours of play." if play_seconds else "."))
    mods = conn.execute("SELECT COUNT(*) FROM mod_id").fetchone()[0]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("thing", "pawn", "hediff")}
    report.lines.append(f"{mods:,} mods; {counts['thing']:,} things, {counts['pawn']:,} of them pawns; "
                        f"{counts['hediff']:,} hediffs.")
    report.sections.append(_section("Maps", ["Map", "Generator", "Size", "Things on it", "Pawns on it"], _rows(conn, """
        SELECT m.position, m.generator, m.size_x || ' x ' || m.size_z,
               (SELECT COUNT(*) FROM thing_place pl WHERE pl.place = 'map' AND pl.map = m.position AND NOT pl.held),
               (SELECT COUNT(*) FROM pawn_view pv WHERE pv.place = 'map' AND pv.map = m.position AND NOT pv.held)
        FROM map m ORDER BY m.position""", (), top)))
    report.sections.append(_section("Where things are", ["Place", "Held by another thing", "Things"], _rows(conn, """
        SELECT place, CASE WHEN held THEN 'yes' ELSE 'no' END, COUNT(*) FROM thing_place
        GROUP BY place, held ORDER BY COUNT(*) DESC""", (), top)))
    report.sections.append(_section("The player's pawns on maps, by race", ["Race", "Pawns"], _rows(conn, """
        SELECT race, COUNT(*) FROM pawn_view WHERE faction_def LIKE ? AND place = 'map'
        GROUP BY race ORDER BY COUNT(*) DESC, race""", (PLAYER_FACTION_PREFIX + "%",), top)))
    report.sections.append(_section(f"Commonest things (top {top})", ["Def", "Things", "Total stack"], _rows(conn, """
        SELECT def, COUNT(*), SUM(COALESCE(stack, 1)) FROM thing GROUP BY def ORDER BY COUNT(*) DESC, def""",
        (), top)))
    return report


def schema(conn, under="", depth=None, top=60):
    """The element paths in the save, with how often each occurs: where to look without reading the file."""
    under = under.strip("/")
    base = under.count("/") + 1 if under else 0
    depth = depth if depth is not None else (2 if under else 3)
    f = Filters()
    if under:
        f.raw("(path = ? OR path LIKE ? ESCAPE '\\')")
        f.params += [under, like(under) + "/%"]
    f.raw("depth <= ?")
    f.params.append(base + depth)
    sql = f"SELECT count, path FROM element_path{f.where} ORDER BY path"
    report = Report(f"Element paths{' under ' + under if under else ''}")
    report.lines.append(f"Paths up to {depth} levels {'below ' + under if under else 'from the root'}. "
                        f"Narrow with --under and --depth.")
    report.sections.append(_section("Paths", ["Count", "Path"], _rows(conn, sql, f.params, top),
                                   _count(conn, sql, f.params)))
    return report


def _thing_filters(def_=None, cls=None, map_=None, place=None, held=None):
    f = Filters()
    f.text("t.def", def_)
    f.text("t.class", cls)
    f.equal("pl.map", map_)
    f.text("pl.place", place)
    if held is not None:
        f.raw("pl.held" if held else "NOT pl.held")
    return f


def things(conn, def_=None, cls=None, map_=None, place=None, held=None, listing=False, top=30):
    f = _thing_filters(def_, cls, map_, place, held)
    base = f"FROM thing t JOIN thing_place pl ON pl.id = t.id{f.where}"
    report = Report("Things")
    if listing:
        sql = f"""SELECT t.thing_id, t.def, t.stuff, t.stack, t.quality, t.hit_points, pl.place,
                         h.thing_id, pl.map, t.pos_x, t.pos_z
                  FROM thing t JOIN thing_place pl ON pl.id = t.id LEFT JOIN thing h ON h.id = t.holder{f.where}
                  ORDER BY t.def, t.id"""
        headers = ["ID", "Def", "Stuff", "Stack", "Quality", "Hit points", "Place", "Held by", "Map", "x", "z"]
    else:
        sql = f"""SELECT t.def, COUNT(*), SUM(COALESCE(t.stack, 1)), GROUP_CONCAT(DISTINCT pl.place)
                  {base} GROUP BY t.def ORDER BY COUNT(*) DESC, t.def"""
        headers = ["Def", "Things", "Total stack", "Places"]
    total_things = conn.execute(f"SELECT COUNT(*) {base}", f.params).fetchone()[0]
    report.lines.append(f"{total_things:,} things match.")
    report.sections.append(_section("Things" if listing else "By def", headers, _rows(conn, sql, f.params, top),
                                   _count(conn, sql, f.params)))
    return report


def _pawn_filters(faction=None, name=None, kind=None, place=None):
    f = Filters()
    if faction and faction.lower() == "player":
        f.raw("pv.faction_def LIKE ?")
        f.params.append(PLAYER_FACTION_PREFIX + "%")
    else:
        f.text("pv.faction_name", faction, "pv.faction_def", "pv.faction")
    f.text("pv.name", name, "pv.thing_id")
    f.text("pv.kind_def", kind, "pv.race")
    f.text("pv.place", place)
    return f


def pawns(conn, faction=None, name=None, kind=None, place=None, top=50):
    f = _pawn_filters(faction, name, kind, place)
    sql = f"""SELECT pv.name, pv.thing_id, pv.race, pv.kind_def, pv.faction_name, pv.place,
                     CASE WHEN pv.held THEN 'yes' ELSE 'no' END, pv.map, pv.pos_x, pv.pos_z, pv.age_years,
                     pv.health_state, (SELECT COUNT(*) FROM hediff h WHERE h.pawn = pv.id)
              FROM pawn_view pv{f.where} ORDER BY pv.name IS NULL, pv.name, pv.id"""
    report = Report("Pawns")
    report.sections.append(_section("Pawns", ["Name", "ID", "Race", "Kind", "Faction", "Place", "Held", "Map", "x",
                                             "z", "Age", "Health state", "Hediffs"],
                                   _rows(conn, sql, f.params, top), _count(conn, sql, f.params)))
    return report


def hediffs(conn, pawn=None, def_=None, top=50):
    f = Filters()
    f.text("pv.name", pawn, "pv.thing_id")
    f.text("h.def", def_)
    base = f"FROM hediff h JOIN pawn_view pv ON pv.id = h.pawn{f.where}"
    report = Report("Hediffs")
    if pawn:
        sql = f"""SELECT pv.name, pv.thing_id, h.def, h.severity, h.part_body, h.part_index,
                         h.age_ticks / {TICKS_PER_DAY}, h.source
                  {base} ORDER BY pv.name, pv.id, h.id"""
        headers = ["Pawn", "ID", "Hediff", "Severity", "Body", "Part index", "Age (days)", "Source"]
        report.lines.append("A part index counts the body's parts in the order the body def lists them.")
    else:
        sql = f"""SELECT h.def, COUNT(*), COUNT(DISTINCT h.pawn), AVG(h.severity), MAX(h.severity)
                  {base} GROUP BY h.def ORDER BY COUNT(*) DESC, h.def"""
        headers = ["Hediff", "Hediffs", "Pawns", "Mean severity", "Highest severity"]
    report.sections.append(_section("Hediffs", headers, _rows(conn, sql, f.params, top), _count(conn, sql, f.params)))
    return report


def find(conn, thing_id, top=20):
    """Things by their ID (Steel12345, ChunkA8061017), each with the chain of things holding it."""
    f = Filters()
    f.text("t.thing_id", thing_id)
    found = conn.execute(f"SELECT t.id FROM thing t{f.where} ORDER BY t.id LIMIT ?", (*f.params, top)).fetchall()
    report = Report(f"Things with ID {thing_id}")
    if not found:
        report.lines.append("No thing has that ID. IDs join the def and a number, as in Steel12345.")
    for (row_id,) in found:
        chain, current = [], row_id
        while current is not None and len(chain) < 50:
            row = conn.execute("""SELECT t.thing_id, t.def, t.class, t.stack, t.quality, t.hit_points, t.faction,
                                         t.map, t.pos_x, t.pos_z, e.path, t.holder
                                  FROM thing t JOIN element_path e ON e.id = t.path_id WHERE t.id = ?""",
                               (current,)).fetchone()
            if row is None:
                break
            chain.append(row[:-1])
            current = row[-1]
        report.sections.append(_section(f"{chain[0][0]} and what holds it",
                                       ["ID", "Def", "Class", "Stack", "Quality", "Hit points", "Faction", "Map",
                                        "x", "z", "Element path"], chain))
    return report


def world(conn, def_=None, faction=None, name=None, top=50):
    """World objects (settlements, sites, caravans): counted by def and faction, or listed when filtered."""
    f = Filters()
    f.text("w.def", def_, "w.class")
    f.text("w.faction_name", faction, "w.faction_def", "w.faction")
    f.text("w.name", name)
    report = Report("World objects")
    if def_ or faction or name:
        sql = f"""SELECT w.object_id, w.def, w.name, w.faction_name, w.tile FROM world_object_view w{f.where}
                  ORDER BY w.faction_name IS NULL, w.faction_name, w.name, w.object_id"""
        headers = ["ID", "Def", "Name", "Faction", "Tile"]
    else:
        sql = """SELECT w.def, w.faction_name, COUNT(*) FROM world_object_view w
                 GROUP BY w.def, w.faction_name ORDER BY COUNT(*) DESC, w.def, w.faction_name"""
        headers = ["Def", "Faction", "World objects"]
        report.lines.append("Filter with --def, --faction or --name to list them.")
    report.sections.append(_section("World objects", headers, _rows(conn, sql, f.params, top),
                                   _count(conn, sql, f.params)))
    return report


def components(conn, cls=None, path=None, value=None, map_=None, top=50):
    """The game's, the world's and maps' components (often mods' saved state), or the values inside them.

    Without --class, --path or --value it lists the components with how many values each holds; with one it lists
    the values, each with its path inside its component.
    """
    report = Report("Components")
    if cls or path or value:
        f = Filters()
        f.text("v.component", cls)
        f.text("v.path", path)
        f.text("v.value", value)
        f.equal("v.map", map_)
        sql = f"""SELECT v.component, v.map, v.path, v.value FROM component_view v{f.where}
                  ORDER BY v.component, v.map IS NOT NULL, v.map, v.id"""
        report.lines.append("Values in save order. A list's items share a path; containers without text of their own "
                            "are left out.")
        report.sections.append(_section("Values", ["Component", "Map", "Path", "Value"],
                                       _rows(conn, sql, f.params, top), _count(conn, sql, f.params)))
        return report
    f = Filters()
    f.equal("m.position", map_)
    sql = f"""SELECT c.class, CASE WHEN e.path LIKE 'savegame/game/maps/%' THEN 'map'
                                   WHEN e.path LIKE 'savegame/game/world/%' THEN 'world' ELSE 'game' END,
                     m.position, (SELECT COUNT(*) FROM component_value v WHERE v.component = c.id) AS n
              FROM component c JOIN element_path e ON e.id = c.path_id LEFT JOIN map m ON m.id = c.map{f.where}
              ORDER BY n DESC, c.class, m.position"""
    report.lines.append("Pass --class (with * wildcards), --path or --value to see the values.")
    report.sections.append(_section("Components", ["Class", "Scope", "Map", "Values"],
                                   _rows(conn, sql, f.params, top), _count(conn, sql, f.params)))
    return report


def sql(conn, query, top=100):
    """Any read-only query; the index cannot be changed through this connection."""
    cursor = conn.execute(query)
    headers = [d[0] for d in cursor.description or []]
    rows = [tuple(r) for r in cursor.fetchmany(top + 1)]
    report = Report("Query")
    report.lines.append("Tables: game, mod_id, mod_name, mod_steam_id, faction, map, map_grid, thing, pawn, hediff, "
                        "trait, skill, world_object, component, component_value, element_path, meta. Views: mods, "
                        "thing_place, pawn_view, world_object_view, component_view.")
    if len(rows) > top:
        report.lines.append(f"Only the first {top:,} rows are shown; raise --top to see more.")
    report.sections.append(_section("Result", headers, rows[:top]))
    return report
