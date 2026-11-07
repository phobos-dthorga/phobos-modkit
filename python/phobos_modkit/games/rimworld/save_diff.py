"""The diff report: what changed between two saves, matched by things' IDs and hediffs' load IDs.

Both indexes are opened read-only; the earlier save's is attached as "before". A thing keeps its ID for its whole
life, so one in both saves is the same thing; a hediff keeps its load ID. Times come from each save's game ticks.
"""
from __future__ import annotations

from ...report import Report, Table
from .save_reports import PLAYER_FACTION_PREFIX, TICKS_PER_DAY


def _faction_clause(alias, faction):
    if not faction or faction.lower() == "any":
        return "1", ()
    if faction.lower() == "player":
        return f"{alias}.faction_def LIKE ?", (PLAYER_FACTION_PREFIX + "%",)
    return f"({alias}.faction_name LIKE ? OR {alias}.faction_def LIKE ?)", (faction, faction)


def diff(conn, before_uri, before_name, after_name, faction="player", top=30):
    conn.execute("ATTACH DATABASE ? AS before", (before_uri,))
    try:
        return _diff(conn, before_name, after_name, faction, top)
    finally:
        conn.execute("DETACH DATABASE before")


def _diff(conn, before_name, after_name, faction, top):
    one = lambda sql, params=(): conn.execute(sql, params).fetchone()[0]
    rows = lambda sql, params=(): [tuple(r) for r in conn.execute(sql, params).fetchall()]
    report = Report(f"{after_name} against {before_name}")
    ticks_after, ticks_before = one("SELECT ticks_game FROM main.game"), one("SELECT ticks_game FROM before.game")
    if ticks_after is not None and ticks_before is not None:
        days = (ticks_after - ticks_before) / TICKS_PER_DAY
        report.lines.append(f"{after_name} is {abs(days):,.1f} in-game days {'after' if days >= 0 else 'before'} "
                            f"{before_name}. Things are matched by ID and hediffs by load ID.")
    clause_after, params_after = _faction_clause("p", faction)
    clause_before, params_before = _faction_clause("p", faction)
    who = "the player's pawns" if (faction or "").lower() == "player" else \
        "all pawns" if not faction or faction.lower() == "any" else f"pawns of {faction}"

    counts = []
    for label, sql in (("things", "SELECT COUNT(*) FROM {db}.thing"), ("pawns", "SELECT COUNT(*) FROM {db}.pawn"),
                       ("hediffs", "SELECT COUNT(*) FROM {db}.hediff")):
        b, a = one(sql.format(db="before")), one(sql.format(db="main"))
        counts.append((label, b, a, f"{a - b:+,}"))
    report.section("Counts", Table(["What", before_name, after_name, "Change"], counts))

    appeared = """SELECT t.def, COUNT(*) FROM main.thing t
                  WHERE NOT EXISTS (SELECT 1 FROM before.thing x WHERE x.thing_id = t.thing_id)
                  GROUP BY t.def ORDER BY COUNT(*) DESC, t.def"""
    went = """SELECT t.def, COUNT(*) FROM before.thing t
              WHERE NOT EXISTS (SELECT 1 FROM main.thing x WHERE x.thing_id = t.thing_id)
              GROUP BY t.def ORDER BY COUNT(*) DESC, t.def"""
    new_rows, gone_rows = rows(appeared), rows(went)
    report.section("Things that appeared, by def", Table(["Def", "Things"], new_rows[:top], len(new_rows)))
    report.section("Things that went, by def", Table(["Def", "Things"], gone_rows[:top], len(gone_rows)))
    stacks = rows("""SELECT a.def, SUM(COALESCE(a.stack, 1) - COALESCE(b.stack, 1)) AS change, COUNT(*)
                     FROM main.thing a JOIN before.thing b ON b.thing_id = a.thing_id
                     WHERE COALESCE(a.stack, 1) <> COALESCE(b.stack, 1)
                     GROUP BY a.def ORDER BY ABS(change) DESC, a.def""")
    report.section("Stacks that grew or shrank, by def", Table(
        ["Def", "Change", "Stacks"], [(d, f"{c:+,}", n) for d, c, n in stacks[:top]], len(stacks)))

    # Two one-sided joins rather than FULL OUTER JOIN, which SQLite only has from 3.39.
    moved = rows(f"""
        WITH a AS (SELECT p.name, p.thing_id, p.place || CASE WHEN p.place = 'map' THEN ' ' || p.map ELSE '' END AS at
                   FROM main.pawn_view p WHERE {clause_after}),
             b AS (SELECT p.name, p.thing_id, p.place || CASE WHEN p.place = 'map' THEN ' ' || p.map ELSE '' END AS at
                   FROM before.pawn_view p WHERE {clause_before})
        SELECT a.name, a.thing_id, COALESCE(b.at, '(not in the save)'), a.at
            FROM a LEFT JOIN b ON b.thing_id = a.thing_id WHERE b.thing_id IS NULL OR b.at IS NOT a.at
        UNION ALL
        SELECT b.name, b.thing_id, b.at, '(not in the save)'
            FROM b WHERE NOT EXISTS (SELECT 1 FROM a WHERE a.thing_id = b.thing_id)
        ORDER BY 1""", params_after + params_before)
    report.section(f"Where {who} moved, arrived or left", Table(["Pawn", "ID", before_name, after_name],
                                                                moved[:top], len(moved)))

    hediffs = f"""
        WITH a AS (SELECT p.thing_id, p.name, h.def, h.part_index, h.severity, h.load_id
                   FROM main.hediff h JOIN main.pawn_view p ON p.id = h.pawn WHERE {clause_after}),
             b AS (SELECT p.thing_id, p.name, h.def, h.part_index, h.severity, h.load_id
                   FROM before.hediff h JOIN before.pawn_view p ON p.id = h.pawn WHERE {clause_before})
        SELECT a.name, 'gained', a.def, a.part_index, NULL, a.severity FROM a
            WHERE NOT EXISTS (SELECT 1 FROM b WHERE b.thing_id = a.thing_id AND b.load_id IS a.load_id
                                                AND b.def = a.def)
        UNION ALL
        SELECT b.name, 'lost', b.def, b.part_index, b.severity, NULL FROM b
            WHERE EXISTS (SELECT 1 FROM a WHERE a.thing_id = b.thing_id)
              AND NOT EXISTS (SELECT 1 FROM a WHERE a.thing_id = b.thing_id AND a.load_id IS b.load_id
                                                AND a.def = b.def)
        UNION ALL
        SELECT a.name, CASE WHEN a.severity > b.severity THEN 'worse' ELSE 'better' END, a.def, a.part_index,
               b.severity, a.severity
            FROM a JOIN b ON b.thing_id = a.thing_id AND b.load_id IS a.load_id AND b.def = a.def
            WHERE ABS(COALESCE(a.severity, 0) - COALESCE(b.severity, 0)) >= 0.01
        ORDER BY 1, 2, 3"""
    changes = rows(hediffs, params_after + params_before)
    report.section(f"Hediffs of {who} gained, lost or changed", Table(
        ["Pawn", "Change", "Hediff", "Part index", f"Severity in {before_name}", f"Severity in {after_name}"],
        changes[:top], len(changes)))
    report.lines.append("Hediffs of pawns missing from either save are not compared; see the pawn table for them.")
    return report
