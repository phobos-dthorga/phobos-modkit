"""Where a colony's mood is suffering, from a save index and the Defs (phobos_modkit.games.rimworld.mood has the rules).

The report answers first: who is closest to breaking, which remembered events cost the colony most and which help, which
needs run low and which addictions are empty. It says what the save cannot show, because half of mood is never saved.
"""
from __future__ import annotations

from collections import defaultdict

from ...report import Bullets, Chart, ChartLine, ChartSeries, Report, Section, Table
from . import mood as rules

GROUPS = {"colonists": "colonist", "slaves": "slave", "prisoners": "prisoner"}
WHO = ("all", *GROUPS)
PAWN_LIMIT = 100           # pawns charted and listed; a colony larger than this is cut and says so
CHART_THOUGHTS = 12        # bars in the charts of thoughts
LOW_NEED = 0.3             # authored: a need below this is called low
EMPTY_NEED = 0.01          # an addiction need this low is empty: withdrawal follows
PLAYER_FACTION_PREFIX = "Player"
RISK_WORDS = {"extreme": "Extreme break risk", "major": "Major break risk", "minor": "Minor break risk", None: "Fine"}
RISK_ROLES = {"extreme": "risk", "major": "accent", "minor": "comparison", None: "success"}


def _percent(level):
    return f"{level * 100:.0f}%"


def _points(value):
    return f"{value:+.1f}"


def _population(conn, who):
    """(id, name, group, mood level) for the pawns on maps who have a mood: the colony's own, its slaves and prisoners."""
    players = {f"Faction_{r[0]}" for r in conn.execute("SELECT load_id FROM faction WHERE def LIKE ?",
                                                        (PLAYER_FACTION_PREFIX + "%",))}
    found = []
    for pid, name, thing_id, status, host, faction, level in conn.execute("""
            SELECT pv.id, pv.name, pv.thing_id, p.guest_status, p.host_faction, pv.faction, COALESCE(n.level, 0)
            FROM pawn_view pv JOIN pawn p ON p.id = pv.id JOIN need n ON n.pawn = pv.id AND n.def = ?
            WHERE pv.place = 'map' ORDER BY COALESCE(n.level, 0), pv.name""", (rules.MOOD_NEED,)):
        if status == "Prisoner" and host in players:
            group = "prisoner"
        elif faction in players:
            group = "slave" if status == "Slave" else "colonist"
        else:
            continue
        if who == "all" or GROUPS.get(who) == group:
            found.append((pid, name or thing_id, group, level))
    return found


def _by_pawn(conn, sql, ids):
    rows = defaultdict(list)
    for row in conn.execute(sql):
        if row[0] in ids:
            rows[row[0]].append(row[1:])
    return rows


class _Colony:
    """Every number the report shows, worked out once."""

    def __init__(self, conn, lookup, who):
        self.lookup = lookup
        self.pawns = _population(conn, who)
        ids = {p[0] for p in self.pawns}
        self.traits = {pid: {d: (g or 0) for d, g in rows}
                       for pid, rows in _by_pawn(conn, "SELECT pawn, def, degree FROM trait", ids).items()}
        self.memories = _by_pawn(conn, """SELECT pawn, def, COALESCE(stage_index, 0), mood_power_factor, mood_offset,
                                                 age_ticks, duration_override, other_pawn
                                          FROM memory ORDER BY id""", ids)
        # The game leaves a need's level out of the save when it is 0, so a missing level is an empty need.
        self.needs = _by_pawn(conn, "SELECT pawn, def, COALESCE(level, 0) FROM need", ids)
        self.unknown, self.cancelled = set(), 0
        base_stat = lookup.get("StatDef", rules.BREAK_THRESHOLD_STAT)
        self.base_threshold = rules.number(base_stat, "defaultBaseValue", None) if base_stat is not None else None
        self.rows = [self._pawn(*p) for p in self.pawns]

    def rule(self, def_name):
        return rules.thought_rule(self.lookup.get("ThoughtDef", def_name), def_name)

    def _pawn(self, pid, name, group, level):
        traits = self.traits.get(pid, {})
        groups, labels = defaultdict(list), {}
        for def_name, stage, power, offset, age, duration, other in self.memories.get(pid, []):
            rule = self.rule(def_name)
            if rule is None:
                self.unknown.add(def_name)
                continue
            value = rules.memory_mood(rule, stage, power, offset, age, duration)
            if value is None:
                continue
            if rules.nullified(rule, traits):
                self.cancelled += 1
                continue
            key = rules.group_key(rule, stage, None if other in (None, "null") else other)
            groups[key].append(value)
            labels[key] = (def_name, rules.label_of(rule, stage), rule.stack_multiplier)
        thoughts = [(labels[k][0], labels[k][1], rules.stacked(v, labels[k][2])) for k, v in groups.items()]
        base = self.base_threshold if self.base_threshold is not None else rules.BREAK_THRESHOLD_FALLBACK
        limits = rules.thresholds(base, [rules.trait_break_change(self.lookup.get("TraitDef", t), d)
                                         for t, d in traits.items()])
        memories = sum(v for _, _, v in thoughts)
        rest = (level - rules.MOOD_BASE_LEVEL) * 100 - memories
        return {"id": pid, "name": name, "group": group, "level": level, "limits": limits,
                "risk": rules.risk(level, limits), "thoughts": thoughts, "memories": memories, "rest": rest,
                "needs": self.needs.get(pid, [])}

    def need_label(self, def_name):
        label = rules.text(self.lookup.get("NeedDef", def_name), "label", def_name) or def_name
        return label[:1].upper() + label[1:]

    def is_chemical(self, def_name):
        element = self.lookup.get("NeedDef", def_name)
        return rules.is_chemical_need(element) if element is not None else def_name.startswith("Chemical_")


def _thought_totals(colony):
    """Per thought label: (label, pawns, total mood, def)."""
    totals, pawns, defs = defaultdict(float), defaultdict(set), {}
    for row in colony.rows:
        for def_name, label, value in row["thoughts"]:
            totals[label] += value
            pawns[label].add(row["id"])
            defs[label] = def_name
    return [(label, len(pawns[label]), totals[label], defs[label]) for label in totals]


def _who_section(colony, shown):
    categories = [r["name"] for r in shown]
    series = [ChartSeries(RISK_WORDS[key], [round(r["level"] * 100, 1) if r["risk"] == key else None for r in shown],
                          RISK_ROLES[key]) for key in (*rules.RISKS, None)]
    series = [s for s in series if any(v is not None for v in s.values)]
    base = colony.base_threshold if colony.base_threshold is not None else rules.BREAK_THRESHOLD_FALLBACK
    minor, major, extreme = rules.thresholds(base)
    chart = Chart("Mood against breaking point", "Each pawn's mood, coloured by the worst break threshold it is below; "
                  "the lines are the thresholds of a pawn with no traits that move them.",
                  categories, series, unit="%", value_label="Mood", stacked=True,
                  lines=[ChartLine("Minor break", round(minor * 100, 1), "comparison"),
                         ChartLine("Major break", round(major * 100, 1), "accent"),
                         ChartLine("Extreme break", round(extreme * 100, 1), "risk")])
    rows = []
    for r in shown:
        low = [(level, d) for d, level in r["needs"] if d != rules.MOOD_NEED and level is not None and level <= 1
               and not colony.is_chemical(d)]
        lowest = min(low) if low else None
        rows.append((r["name"], r["group"], _percent(r["level"]), _percent(r["limits"][0]), RISK_WORDS[r["risk"]],
                     _points(r["memories"]), _points(r["rest"]),
                     f"{colony.need_label(lowest[1])} {_percent(lowest[0])}" if lowest else ""))
    table = Table(["Pawn", "Group", "Mood", "Minor break below", "Risk", "Remembered events", "Everything else",
                   "Lowest need"], rows, len(colony.rows))
    return Section("Who is closest to breaking", [chart, table])


def _thought_sections(colony, top):
    totals = _thought_totals(colony)
    hurting = sorted((t for t in totals if t[2] < 0), key=lambda t: t[2])
    helping = sorted((t for t in totals if t[2] > 0), key=lambda t: -t[2])
    sections = []
    for heading, items, role, describe in (
            ("What hurts the most", hurting, "risk",
             "Remembered events by the mood they cost everyone together, worst first."),
            ("What helps the most", helping, "success",
             "Remembered events by the mood they add for everyone together, best first.")):
        charted = items[:CHART_THOUGHTS]
        blocks = []
        if charted:
            blocks.append(Chart(heading, describe, [t[0] for t in charted],
                                [ChartSeries("Mood, everyone together", [round(t[2], 1) for t in charted], role)],
                                value_label="Mood points"))
        blocks.append(Table(["Remembered event", "Pawns", "Mood, everyone together", "Each, on average", "Def"],
                            [(t[0], t[1], _points(t[2]), _points(t[2] / t[1]), t[3]) for t in items[:top]],
                            len(items)))
        sections.append(Section(heading, blocks))
    return sections


def _need_sections(colony, top):
    levels, chemical = defaultdict(list), defaultdict(list)
    for row in colony.rows:
        for def_name, level in row["needs"]:
            if def_name == rules.MOOD_NEED or level is None:
                continue
            (chemical if colony.is_chemical(def_name) else levels)[def_name].append(level)
    needs = sorted(((d, v) for d, v in levels.items() if max(v) <= 1.0001), key=lambda dv: sum(dv[1]) / len(dv[1]))
    charted = needs[:CHART_THOUGHTS]
    blocks = []
    if charted:
        blocks.append(Chart("Needs across the colony", "Each need's average level among the pawns who have it, lowest "
                            "first; the line marks where this report calls a need low.",
                            [colony.need_label(d) for d, _ in charted],
                            [ChartSeries("Average level", [round(sum(v) / len(v) * 100, 1) for _, v in charted],
                                         "observed")],
                            unit="%", value_label="Average level", lines=[ChartLine("Low", LOW_NEED * 100, "accent")]))
    blocks.append(Table(["Need", "Pawns with it", "Average", f"Below {_percent(LOW_NEED)}", "Def"],
                        [(colony.need_label(d), len(v), _percent(sum(v) / len(v)), sum(x < LOW_NEED for x in v), d)
                         for d, v in needs[:top]], len(needs)))
    drugs = sorted(chemical.items(), key=lambda dv: -len(dv[1]))
    addictions = Table(["Drug need", "Pawns with it", "Average", f"Below {_percent(LOW_NEED)}", "Empty", "Def"],
                       [(colony.need_label(d), len(v), _percent(sum(v) / len(v)), sum(x < LOW_NEED for x in v),
                         sum(x < EMPTY_NEED for x in v), d) for d, v in drugs[:top]], len(drugs))
    return [Section("Needs running low", blocks),
            Section("Addictions and drug needs", [
                "Each addiction is a need of its own: when it empties, withdrawal follows. A general need for drugs, "
                "from a trait or a belief, lowers mood as it runs low instead.", addictions])]


def _limits(colony, source):
    items = ["Situational thoughts are not in the save: rooms (bedroom, dining room, rec room), pain, hunger, "
             "exhaustion, cold, darkness, traits, ideology precepts and drugs' highs are worked out while the game "
             "runs. \"Everything else\" is mood minus the remembered events: their sum, plus the lag of mood "
             "catching up.",
             "Mood values come from " + source + ". Thoughts multiplied by a stat or by their own rules, and thoughts "
             "cancelled by hediffs, genes or precepts, are counted at face value; trait cancelling is applied.",
             "Break thresholds count traits only; genes, hediffs and other mods' changes are left out."]
    if colony.cancelled:
        items.append(f"{colony.cancelled:,} remembered events are cancelled by a trait and left out.")
    if colony.unknown:
        names = ", ".join(sorted(colony.unknown)[:8]) + (" and more" if len(colony.unknown) > 8 else "")
        items.append(f"{len(colony.unknown):,} kinds of remembered event have no ThoughtDef in the Defs read, so they "
                     f"are not counted: {names}.")
    return Section("What this report cannot see", [Bullets(items)])


def _source(lookup):
    if not lookup.available:
        return "nowhere: the Defs could not be read, so remembered events are not counted"
    if "patched" in lookup.used:
        return "the Defs with every patch applied, as the game last wrote them"
    return "the Defs as their mods wrote them (patches not applied)"


def mood(conn, lookup, who="all", top=30):
    if who not in WHO:
        raise ValueError(f"who must be one of {', '.join(WHO)}")
    colony = _Colony(conn, lookup, who)
    report = Report("Colony mood")
    if not colony.rows:
        report.lines.append("No pawn of the colony, its slaves or its prisoners is on a map with a mood.")
        return report
    counts = defaultdict(int)
    for r in colony.rows:
        counts[r["risk"]] += 1
    groups = defaultdict(int)
    for r in colony.rows:
        groups[r["group"]] += 1
    whom = ", ".join(f"{n} {g}{'s' if n != 1 else ''}" for g, n in sorted(groups.items()))
    report.lines.append(f"{len(colony.rows)} pawns ({whom}): {counts['extreme']} below the extreme break threshold, "
                        f"{counts['major']} below major and {counts['minor']} below minor.")
    totals = sorted(_thought_totals(colony), key=lambda t: t[2])
    memories = sum(r["memories"] for r in colony.rows)
    rest = sum(r["rest"] for r in colony.rows)
    if totals and totals[0][2] < 0:
        worst = totals[0]
        report.lines.append(f"Remembered events add {_points(memories)} mood in all; the costliest is \"{worst[0]}\" "
                            f"({_points(worst[2])} across {worst[1]} pawns).")
    report.lines.append(f"Everything the save does not list, mostly situational thoughts such as rooms, pain and "
                        f"precepts, comes to about {_points(rest)}.")
    shown = colony.rows[:PAWN_LIMIT]
    report.sections.append(_who_section(colony, shown))
    report.sections += _thought_sections(colony, top)
    report.sections += _need_sections(colony, top)
    report.sections.append(_limits(colony, _source(colony.lookup)))
    return report


def pawn_mood(conn, lookup, name, top=60):
    """One pawn's remembered events and needs, in full."""
    colony = _Colony(conn, lookup, "all")
    wanted = name.lower()
    matches = [r for r in colony.rows if (r["name"] or "").lower() == wanted] or \
              [r for r in colony.rows if wanted in (r["name"] or "").lower()]
    report = Report(f"Mood of {name}")
    if not matches:
        report.lines.append("No pawn of the colony, its slaves or its prisoners on a map has that name.")
        return report
    r = matches[0]
    minor, major, extreme = r["limits"]
    report.lines.append(f"{r['name']} ({r['group']}): mood {_percent(r['level'])}, "
                        f"{RISK_WORDS[r['risk']].lower()}. Breaks below {_percent(minor)} (minor), {_percent(major)} "
                        f"(major) and {_percent(extreme)} (extreme).")
    report.lines.append(f"Remembered events {_points(r['memories'])}; everything else about {_points(r['rest'])}.")
    thoughts = sorted(r["thoughts"], key=lambda t: t[2])
    if thoughts:
        report.sections.append(Section("Remembered events", [
            Chart("Remembered events", f"What each remembered event does to {r['name']}'s mood.",
                  [t[1] for t in thoughts[:CHART_THOUGHTS * 2]],
                  [ChartSeries("Lowers mood", [round(t[2], 1) if t[2] < 0 else None for t in thoughts[:CHART_THOUGHTS * 2]],
                               "risk"),
                   ChartSeries("Raises mood", [round(t[2], 1) if t[2] >= 0 else None for t in thoughts[:CHART_THOUGHTS * 2]],
                               "success")],
                  value_label="Mood points", stacked=True),
            Table(["Remembered event", "Mood", "Def"], [(t[1], _points(t[2]), t[0]) for t in thoughts[:top]],
                  len(thoughts))]))
    needs = sorted(((colony.need_label(d), lv, d) for d, lv in r["needs"] if lv is not None and d != rules.MOOD_NEED),
                   key=lambda n: n[1])
    report.sections.append(Section("Needs", [Table(["Need", "Level", "Def"],
                                                   [(n[0], _percent(n[1]) if n[1] <= 1 else f"{n[1]:.1f}", n[2])
                                                    for n in needs[:top]], len(needs))]))
    if len(matches) > 1:
        report.lines.append(f"{len(matches) - 1} more pawns match that name; give the full name to choose.")
    report.sections.append(_limits(colony, _source(colony.lookup)))
    return report
