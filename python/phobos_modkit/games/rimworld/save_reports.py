"""Reports over a RimWorld save index: each returns a SaveReport that renders as Markdown or JSON.

All filters take plain text, matched without regard to case; * and ? are wildcards. Tables are cut at `top` rows
and say how many there were in all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...markdown import table
from .save import like

TICKS_PER_DAY = 60000          # RimWorld: one in-game day
TICKS_PER_YEAR = 60 * TICKS_PER_DAY
PLAYER_FACTION_PREFIX = "Player"  # the player's faction defs are PlayerColony, PlayerTribe and modded Player* ones


@dataclass
class Section:
    heading: str
    headers: list
    rows: list
    total: int = None   # rows in all, when more than shown


@dataclass
class SaveReport:
    title: str
    lines: list = field(default_factory=list)
    sections: list = field(default_factory=list)

    def to_markdown(self):
        out = [f"# {self.title}", ""]
        if self.lines:
            out += [*self.lines, ""]
        for s in self.sections:
            out += [f"## {s.heading}", ""]
            if not s.rows:
                out += ["None.", ""]
                continue
            out += table(s.headers, s.rows)
            if s.total is not None and s.total > len(s.rows):
                out.append(f"\nShowing {len(s.rows):,} of {s.total:,}; raise --top to see more.")
            out.append("")
        return "\n".join(out)

    def to_json(self):
        return {"title": self.title, "lines": self.lines,
                "sections": [{"heading": s.heading, "headers": s.headers, "rows": [list(r) for r in s.rows],
                              "total": s.total if s.total is not None else len(s.rows)} for s in self.sections]}


class Filters:
    """WHERE clauses with parameters, built one filter at a time."""

    def __init__(self):
        self.clauses, self.params = [], []

    def text(self, column_sql, value, *more_columns):
        if value:
            columns = (column_sql, *more_columns)
            self.clauses.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columns) + ")")
            self.params += [like(value)] * len(columns)

    def equal(self, column_sql, value):
        if value is not None:
            self.clauses.append(f"{column_sql} = ?")
            self.params.append(value)

    def raw(self, clause):
        self.clauses.append(clause)

    @property
    def where(self):
        return (" WHERE " + " AND ".join(self.clauses)) if self.clauses else ""


def _count(conn, sql, params=()):
    return conn.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]


def _rows(conn, sql, params, top):
    return [tuple(r) for r in conn.execute(f"{sql} LIMIT ?", (*params, top)).fetchall()]


def summary(conn, top=10):
    game = conn.execute("SELECT game_version, scenario, ticks_game, play_seconds FROM game").fetchone() or (None,) * 4
    version, scenario, ticks, play_seconds = game
    report = SaveReport("Save summary")
    if ticks is not None:
        report.lines.append(f"RimWorld {version}, scenario \"{scenario}\". {ticks // TICKS_PER_DAY:,} in-game days "
                            f"({ticks / TICKS_PER_YEAR:.1f} years) since the colony began"
                            + (f"; {play_seconds / 3600:,.0f} hours of play." if play_seconds else "."))
    mods = conn.execute("SELECT COUNT(*) FROM mod_id").fetchone()[0]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("thing", "pawn", "hediff")}
    report.lines.append(f"{mods:,} mods; {counts['thing']:,} things, {counts['pawn']:,} of them pawns; "
                        f"{counts['hediff']:,} hediffs.")
    report.sections.append(Section("Maps", ["Map", "Generator", "Size", "Things on it", "Pawns on it"], _rows(conn, """
        SELECT m.position, m.generator, m.size_x || ' x ' || m.size_z,
               (SELECT COUNT(*) FROM thing_place pl WHERE pl.place = 'map' AND pl.map = m.position AND NOT pl.held),
               (SELECT COUNT(*) FROM pawn_view pv WHERE pv.place = 'map' AND pv.map = m.position AND NOT pv.held)
        FROM map m ORDER BY m.position""", (), top)))
    report.sections.append(Section("Where things are", ["Place", "Held by another thing", "Things"], _rows(conn, """
        SELECT place, CASE WHEN held THEN 'yes' ELSE 'no' END, COUNT(*) FROM thing_place
        GROUP BY place, held ORDER BY COUNT(*) DESC""", (), top)))
    report.sections.append(Section("The player's pawns on maps, by race", ["Race", "Pawns"], _rows(conn, """
        SELECT race, COUNT(*) FROM pawn_view WHERE faction_def LIKE ? AND place = 'map'
        GROUP BY race ORDER BY COUNT(*) DESC, race""", (PLAYER_FACTION_PREFIX + "%",), top)))
    report.sections.append(Section(f"Commonest things (top {top})", ["Def", "Things", "Total stack"], _rows(conn, """
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
    report = SaveReport(f"Element paths{' under ' + under if under else ''}")
    report.lines.append(f"Paths up to {depth} levels {'below ' + under if under else 'from the root'}. "
                        f"Narrow with --under and --depth.")
    report.sections.append(Section("Paths", ["Count", "Path"], _rows(conn, sql, f.params, top),
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
    report = SaveReport("Things")
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
    report.sections.append(Section("Things" if listing else "By def", headers, _rows(conn, sql, f.params, top),
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
    report = SaveReport("Pawns")
    report.sections.append(Section("Pawns", ["Name", "ID", "Race", "Kind", "Faction", "Place", "Held", "Map", "x",
                                             "z", "Age", "Health state", "Hediffs"],
                                   _rows(conn, sql, f.params, top), _count(conn, sql, f.params)))
    return report


def hediffs(conn, pawn=None, def_=None, top=50):
    f = Filters()
    f.text("pv.name", pawn, "pv.thing_id")
    f.text("h.def", def_)
    base = f"FROM hediff h JOIN pawn_view pv ON pv.id = h.pawn{f.where}"
    report = SaveReport("Hediffs")
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
    report.sections.append(Section("Hediffs", headers, _rows(conn, sql, f.params, top), _count(conn, sql, f.params)))
    return report


def find(conn, thing_id, top=20):
    """Things by their ID (Steel12345, ChunkA8061017), each with the chain of things holding it."""
    f = Filters()
    f.text("t.thing_id", thing_id)
    found = conn.execute(f"SELECT t.id FROM thing t{f.where} ORDER BY t.id LIMIT ?", (*f.params, top)).fetchall()
    report = SaveReport(f"Things with ID {thing_id}")
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
        report.sections.append(Section(f"{chain[0][0]} and what holds it",
                                       ["ID", "Def", "Class", "Stack", "Quality", "Hit points", "Faction", "Map",
                                        "x", "z", "Element path"], chain))
    return report


def sql(conn, query, top=100):
    """Any read-only query; the index cannot be changed through this connection."""
    cursor = conn.execute(query)
    headers = [d[0] for d in cursor.description or []]
    rows = [tuple(r) for r in cursor.fetchmany(top + 1)]
    report = SaveReport("Query")
    report.lines.append("Tables: game, mod_id, mod_name, mod_steam_id, faction, map, thing, pawn, hediff, trait, "
                        "skill, element_path, meta. Views: mods, thing_place, pawn_view.")
    if len(rows) > top:
        report.lines.append(f"Only the first {top:,} rows are shown; raise --top to see more.")
    report.sections.append(Section("Result", headers, rows[:top]))
    return report
