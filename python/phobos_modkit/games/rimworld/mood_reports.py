"""Where a colony's mood is suffering, from a save index and the Defs (phobos_modkit.games.rimworld.mood has the rules).

The report answers first: where to start, who is closest to breaking, which thoughts cost the colony most and which help,
which needs run low and which addictions are empty. A save holds only remembered thoughts; when the colony mood file a running
game wrote at the same save is there (phobos_modkit.games.rimworld.mood_file), every thought comes from it exactly, situational
ones included. Otherwise the report counts remembered events by the game's rules and gives the rest as one figure.
"""
from __future__ import annotations

from collections import defaultdict

from ...report import Bullets, Chart, ChartLine, ChartSeries, Report, Section, Table
from . import mood as rules

GROUPS = {"colonists": "colonist", "slaves": "slave", "prisoners": "prisoner"}
WHO = ("all", *GROUPS)
PAWN_LIMIT = 100           # pawns charted and listed; a colony larger than this is cut and says so
CHART_THOUGHTS = 12        # bars in the charts of thoughts
START_HERE = 5             # causes in "Where to start"
LOW_NEED = 0.3             # authored: a need below this is called low
EMPTY_NEED = 0.01          # an addiction need this low is empty: withdrawal follows
PLAYER_FACTION_PREFIX = "Player"
MEMORY, SITUATIONAL = "memory", "situational"
KIND_WORDS = {MEMORY: "remembered", SITUATIONAL: "situational"}
RISK_WORDS = {"extreme": "Extreme break risk", "major": "Major break risk", "minor": "Minor break risk", None: "Fine"}
RISK_ROLES = {"extreme": "risk", "major": "accent", "minor": "comparison", None: "success"}
ADVICE_NOTE = ("Advice is ours, written from how the game behaves, not the game's own; check it fits your colony and its "
               "beliefs. Each figure is what the cause costs now, so roughly what removing it would give back.")


def _percent(level):
    return f"{level * 100:.0f}%"


def _points(value):
    return f"{value:+.1f}"


def _population(conn, who):
    """(id, thing ID, name, group, mood level) for pawns on maps with a mood: the colony's own, its slaves and prisoners."""
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
            found.append((pid, thing_id, name or thing_id, group, level))
    return found


def _by_pawn(conn, sql, ids):
    rows = defaultdict(list)
    for row in conn.execute(sql):
        if row[0] in ids:
            rows[row[0]].append(row[1:])
    return rows


class _Colony:
    """Every number the report shows, worked out once."""

    def __init__(self, conn, lookup, who, mood_file=None, advice=None):
        self.lookup, self.advice, self.file = lookup, advice, mood_file
        game = conn.execute("SELECT ticks_game, world_seed FROM game").fetchone() or (None, None)
        self.exact = mood_file is not None and mood_file.matches(game[0], game[1])
        self.pawns = _population(conn, who)
        ids = {p[0] for p in self.pawns}
        self.traits = {pid: {d: (g or 0) for d, g in rows}
                       for pid, rows in _by_pawn(conn, "SELECT pawn, def, degree FROM trait", ids).items()}
        self.memories = _by_pawn(conn, """SELECT pawn, def, COALESCE(stage_index, 0), mood_power_factor, mood_offset,
                                                 age_ticks, duration_override, other_pawn
                                          FROM memory ORDER BY id""", ids)
        # The game leaves a need's level out of the save when it is 0, so a missing level is an empty need.
        self.needs = _by_pawn(conn, "SELECT pawn, def, COALESCE(level, 0) FROM need", ids)
        self.unknown, self.cancelled, self.missing_from_file = set(), 0, 0
        base_stat = lookup.get("StatDef", rules.BREAK_THRESHOLD_STAT)
        self.base_threshold = rules.number(base_stat, "defaultBaseValue", None) if base_stat is not None else None
        self.rows = [self._pawn(*p) for p in self.pawns]

    def rule(self, def_name):
        return rules.thought_rule(self.lookup.get("ThoughtDef", def_name), def_name)

    def _from_save(self, pid):
        """(def, label, mood, kind) for each group of remembered thoughts, by the game's rules."""
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
        return [(labels[k][0], labels[k][1], rules.stacked(v, labels[k][2]), MEMORY) for k, v in groups.items()]

    def _pawn(self, pid, thing_id, name, group, level):
        filed = self.file.pawns.get(thing_id) if self.exact else None
        if self.exact and filed is None:
            self.missing_from_file += 1
        if filed is not None:
            thoughts = [(t.def_name, t.label, t.mood, MEMORY if t.kind == MEMORY else SITUATIONAL) for t in filed.thoughts]
            limits = filed.limits
        else:
            thoughts = self._from_save(pid)
            limits = None
        if limits is None:
            base = self.base_threshold if self.base_threshold is not None else rules.BREAK_THRESHOLD_FALLBACK
            limits = rules.thresholds(base, [rules.trait_break_change(self.lookup.get("TraitDef", t), d)
                                             for t, d in self.traits.get(pid, {}).items()])
        memories = sum(v for _, _, v, kind in thoughts if kind == MEMORY)
        situational = sum(v for _, _, v, kind in thoughts if kind == SITUATIONAL)
        rest = (level - rules.MOOD_BASE_LEVEL) * 100 - memories - situational
        return {"id": pid, "name": name, "group": group, "level": level, "limits": limits, "exact": filed is not None,
                "risk": rules.risk(level, limits), "thoughts": thoughts, "memories": memories,
                "situational": situational, "rest": rest, "needs": self.needs.get(pid, [])}

    def need_label(self, def_name):
        label = rules.text(self.lookup.get("NeedDef", def_name), "label", def_name) or def_name
        return label[:1].upper() + label[1:]

    def is_chemical(self, def_name):
        element = self.lookup.get("NeedDef", def_name)
        return rules.is_chemical_need(element) if element is not None else def_name.startswith("Chemical_")

    def thought_advice(self, def_name):
        return self.advice.thought(def_name) if self.advice else None

    def fixable(self, def_name):
        return bool(self.advice and self.advice.fixable(def_name))

    def need_advice(self, def_name):
        if not self.advice:
            return None
        return self.advice.drug if self.is_chemical(def_name) else self.advice.need(def_name)


def _thought_totals(colony):
    """Per thought label and kind: (label, pawns, total mood, def, kind)."""
    totals, pawns, defs = defaultdict(float), defaultdict(set), {}
    for row in colony.rows:
        for def_name, label, value, kind in row["thoughts"]:
            totals[(label, kind)] += value
            pawns[(label, kind)].add(row["id"])
            defs[(label, kind)] = def_name
    return [(key[0], len(pawns[key]), totals[key], defs[key], key[1]) for key in totals]


def _start_section(colony, totals):
    """The few costliest causes the player can do something about, with the advice for each."""
    rows = [(t[0], t[1], _points(t[2]), colony.thought_advice(t[3]))
            for t in sorted(totals, key=lambda t: t[2]) if t[2] < 0 and colony.fixable(t[3])][:START_HERE]
    if not rows:
        return None
    return Section("Where to start", [ADVICE_NOTE, Table(["Cause", "Pawns", "Mood it costs", "Advice"], rows)])


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
        last = (_points(r["situational"]),) if colony.exact else (_points(r["rest"]),)
        rows.append((r["name"], r["group"], _percent(r["level"]), _percent(r["limits"][0]), RISK_WORDS[r["risk"]],
                     _points(r["memories"]), *last,
                     f"{colony.need_label(lowest[1])} {_percent(lowest[0])}" if lowest else ""))
    table = Table(["Pawn", "Group", "Mood", "Minor break below", "Risk", "Remembered events",
                   "Situational" if colony.exact else "Everything else", "Lowest need"], rows, len(colony.rows))
    return Section("Who is closest to breaking", [chart, table])


def _thought_sections(colony, totals, top):
    hurting = sorted((t for t in totals if t[2] < 0), key=lambda t: t[2])
    helping = sorted((t for t in totals if t[2] > 0), key=lambda t: -t[2])
    what = "thoughts" if colony.exact else "remembered events"
    sections = []
    for heading, title, items, role, describe in (
            ("What hurts the most", f"Costliest {what}", hurting, "risk",
             f"{what.capitalize()} by the mood they cost everyone together, worst first."),
            ("What helps the most", f"Most cheering {what}", helping, "success",
             f"{what.capitalize()} by the mood they add for everyone together, best first.")):
        charted = items[:CHART_THOUGHTS]
        blocks = []
        if charted:
            blocks.append(Chart(title, describe, [t[0] for t in charted],
                                [ChartSeries("Mood, everyone together", [round(t[2], 1) for t in charted], role)],
                                value_label="Mood points"))
        headers = ["Thought" if colony.exact else "Remembered event", "Pawns", "Mood, everyone together",
                   "Each, on average", *(["Kind"] if colony.exact else []), "Def"]
        blocks.append(Table(headers, [(t[0], t[1], _points(t[2]), _points(t[2] / t[1]),
                                       *([KIND_WORDS[t[4]]] if colony.exact else []), t[3]) for t in items[:top]],
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
    blocks.append(Table(["Need", "Pawns with it", "Average", f"Below {_percent(LOW_NEED)}", "Advice", "Def"],
                        [(colony.need_label(d), len(v), _percent(sum(v) / len(v)), sum(x < LOW_NEED for x in v),
                          colony.need_advice(d) if any(x < LOW_NEED for x in v) else "", d)
                         for d, v in needs[:top]], len(needs)))
    drugs = sorted(chemical.items(), key=lambda dv: -len(dv[1]))
    addictions = Table(["Drug need", "Pawns with it", "Average", f"Below {_percent(LOW_NEED)}", "Empty", "Def"],
                       [(colony.need_label(d), len(v), _percent(sum(v) / len(v)), sum(x < LOW_NEED for x in v),
                         sum(x < EMPTY_NEED for x in v), d) for d, v in drugs[:top]], len(drugs))
    drug_blocks = ["Each addiction is a need of its own: when it empties, withdrawal follows. A general need for drugs, "
                   "from a trait or a belief, lowers mood as it runs low instead.", addictions]
    if colony.advice and any(x < EMPTY_NEED for _, v in drugs for x in v):
        drug_blocks.append(f"Advice: {colony.advice.drug}")
    return [Section("Needs running low", blocks), Section("Addictions and drug needs", drug_blocks)]


def _file_lines(colony):
    """What the colony mood file gave, for the limits section."""
    if colony.exact:
        lines = [f"Every thought is as the game counted it at this save, read from the colony mood file written "
                 f"{colony.file.written or 'at this save'}: situational thoughts (rooms, pain, cold, beliefs) included, "
                 "and break thresholds with everything that moves them. Mood moves towards its target gradually, so a "
                 "pawn's mood can differ a little from the sum of its thoughts."]
        if colony.missing_from_file:
            lines.append(f"{colony.missing_from_file} pawns are not in the file and are counted from the save alone.")
        return lines
    if colony.file is not None:
        return [f"A colony mood file exists, but it was written at another save (tick {colony.file.ticks:,}), so this "
                "report works from the save alone. Report on the newest save, or save again in game, to use it."]
    return ["Situational thoughts are not in the save: rooms (bedroom, dining room, rec room), pain, hunger, exhaustion, "
            "cold, darkness, traits, ideology precepts and drugs' highs are worked out while the game runs. \"Everything "
            "else\" is mood minus the remembered events: their sum, plus the lag of mood catching up. With D'thorga "
            "Framework's setting \"Write a colony mood file at each save\", the next save names every one."]


def _limits(colony, source):
    items = _file_lines(colony)
    if not colony.exact:
        items += ["Mood values come from " + source + ". Thoughts multiplied by a stat or by their own rules, and "
                  "thoughts cancelled by hediffs, genes or precepts, are counted at face value; trait cancelling is "
                  "applied.",
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


def mood(conn, lookup, who="all", top=30, mood_file=None, advice=None):
    if who not in WHO:
        raise ValueError(f"who must be one of {', '.join(WHO)}")
    colony = _Colony(conn, lookup, who, mood_file, advice)
    report = Report("Colony mood")
    if not colony.rows:
        report.lines.append("No pawn of the colony, its slaves or its prisoners is on a map with a mood.")
        return report
    counts, groups = defaultdict(int), defaultdict(int)
    for r in colony.rows:
        counts[r["risk"]] += 1
        groups[r["group"]] += 1
    whom = ", ".join(f"{n} {g}{'s' if n != 1 else ''}" for g, n in sorted(groups.items()))
    report.lines.append(f"{len(colony.rows)} pawns ({whom}): {counts['extreme']} below the extreme break threshold, "
                        f"{counts['major']} below major and {counts['minor']} below minor.")
    totals = _thought_totals(colony)
    ordered = sorted(totals, key=lambda t: t[2])
    memories = sum(r["memories"] for r in colony.rows)
    worst = f"; the costliest is \"{ordered[0][0]}\" ({_points(ordered[0][2])} across {ordered[0][1]} pawns)" \
        if ordered and ordered[0][2] < 0 else ""
    if colony.exact:
        situational = sum(r["situational"] for r in colony.rows)
        report.lines.append(f"Every thought as the game counted it at this save: remembered events add "
                            f"{_points(memories)} mood in all and situational thoughts {_points(situational)}{worst}.")
    else:
        report.lines.append(f"Remembered events add {_points(memories)} mood in all{worst}.")
        report.lines.append(f"Everything the save does not list, mostly situational thoughts such as rooms, pain and "
                            f"precepts, comes to about {_points(sum(r['rest'] for r in colony.rows))}.")
    start = _start_section(colony, totals)
    if start:
        report.sections.append(start)
    report.sections.append(_who_section(colony, colony.rows[:PAWN_LIMIT]))
    report.sections += _thought_sections(colony, totals, top)
    report.sections += _need_sections(colony, top)
    report.sections.append(_limits(colony, _source(colony.lookup)))
    return report


def pawn_mood(conn, lookup, name, top=60, mood_file=None, advice=None):
    """One pawn's thoughts and needs, in full."""
    colony = _Colony(conn, lookup, "all", mood_file, advice)
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
    if r["exact"]:
        report.lines.append(f"Remembered events {_points(r['memories'])}; situational thoughts "
                            f"{_points(r['situational'])}.")
    else:
        report.lines.append(f"Remembered events {_points(r['memories'])}; everything else about {_points(r['rest'])}.")
    thoughts = sorted(r["thoughts"], key=lambda t: t[2])
    heading = "Thoughts" if r["exact"] else "Remembered events"
    if thoughts:
        shown = thoughts[:CHART_THOUGHTS * 2]
        report.sections.append(Section(heading, [
            Chart(heading, f"What each {'thought' if r['exact'] else 'remembered event'} does to {r['name']}'s mood.",
                  [t[1] for t in shown],
                  [ChartSeries("Lowers mood", [round(t[2], 1) if t[2] < 0 else None for t in shown], "risk"),
                   ChartSeries("Raises mood", [round(t[2], 1) if t[2] >= 0 else None for t in shown], "success")],
                  value_label="Mood points", stacked=True),
            Table(["Thought" if r["exact"] else "Remembered event", "Mood", "Kind", "Advice", "Def"],
                  [(t[1], _points(t[2]), KIND_WORDS[t[3]], (colony.thought_advice(t[0]) or "") if t[2] < 0 else "", t[0])
                   for t in thoughts[:top]], len(thoughts))]))
    needs = sorted(((colony.need_label(d), lv, d) for d, lv in r["needs"] if lv is not None and d != rules.MOOD_NEED),
                   key=lambda n: n[1])
    report.sections.append(Section("Needs", [Table(["Need", "Level", "Def"],
                                                   [(n[0], _percent(n[1]) if n[1] <= 1 else f"{n[1]:.1f}", n[2])
                                                    for n in needs[:top]], len(needs))]))
    if len(matches) > 1:
        report.lines.append(f"{len(matches) - 1} more pawns match that name; give the full name to choose.")
    report.sections.append(_limits(colony, _source(colony.lookup)))
    return report
