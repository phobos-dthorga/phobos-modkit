"""Sorting a game's list of active mods from the rules every mod, the community and the owner give, each move explained (1.74.0).
Game-free.

Step 3 of D'thorga Companion's own mod manager (the owner, 22 Nov 2026). The owner's choices on question cards: **both ways, chosen
at the press**: the fewest moves (the list keeps its order and only what a rule says is out of place moves) or a full re-sort (the
order rebuilt from the rules, alphabetical where no rule decides, as RimSort's sorts do); and **the owner's rules from RimSort read as
they are, plus new ones kept here** (`rules.json` in the game's mod-list folder).

Where a rule comes from, strongest first (agent's order, used only to choose which rule of a loop to set aside):

- **yours**: the owner's rules, made here or in RimSort;
- **own**: the mod's own files (load after, load before);
- **code** (1.84.0; the owner's choice, 23 Nov 2026): a mod loads after any mod whose assembly holds the parent classes or
  interfaces of its own loaded code (read from the assemblies' metadata, never loaded), which the game needs first and which
  neither mod may declare; ranked under yours only, since compiled code cannot be wrong about what it builds on;
- **needs**: a mod loads after the mods it needs (RimSort does the same with "use modDependencies as loadAfter"); not for
  frameworks or "top" and "bottom" mods (1.86.0, as RimSort: their needs usually mean "install this");
- **workshop** (1.79.0; the owner's choice, 23 Nov 2026): a mod loads after the items its Workshop page lists as required, which
  catches needs a mod never wrote into its own files (RimWorld: RimSort's Steam Workshop Database, read where RimSort keeps it);
- **community**: the community rules a game's mod managers share (RimWorld: RimSort's Community Rules database, read where RimSort
  keeps it and never copied into our repositories).

A mod may also be asked to load **at the top** or **at the bottom**. From 1.86.0 these mean what RimSort means (the owner's choice):
membership of the top group (with the frameworks) or the bottom group, not "as high as its rules allow".
Rules that form a loop cannot all be kept: the sorter sets aside the weakest link of each loop and says which, where RimSort refuses
to sort. The fewest-moves sort tries both a forward and a backward pass and keeps whichever moves fewer mods; a moved mod is one
outside the longest run of mods whose order is kept.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import bisect
import heapq
import json
import os
from pathlib import Path

from .mod_list import FixError, Installed, folder

YOURS, CODE, OWN, NEEDS, WORKSHOP, COMMUNITY, GAME = "yours", "code", "own", "needs", "workshop", "community", "game"
# Workshop requirements are the weakest (1.86.0; the owner's choice of 23 Nov 2026, after the RimSort study found RimSort does not
# sort by them at all).
STRENGTH = {YOURS: 6, CODE: 5, OWN: 4, NEEDS: 3, COMMUNITY: 2, WORKSHOP: 1, GAME: 0}
RULE_SOURCES = (YOURS, CODE, OWN, NEEDS, COMMUNITY, WORKSHOP)
SOURCE_WORDS = {YOURS: "your rule", CODE: "its code builds on it", OWN: "its own files", NEEDS: "it needs it",
                WORKSHOP: "its Workshop page requires it",
                COMMUNITY: "the community rules",
                GAME: "the game's own load first"}
FEWEST, FULL = "fewest", "full"
TOP, NORMAL, BOTTOM = 0, 1, 2
# Groups (1.86.0; the owner's choices of 23 Nov 2026 after the RimSort study, `docs/research/rimsort-sorting.md`): the game's own
# and its loaders first, then frameworks and "load at the top" mods, then the rest, then "load at the bottom" mods. Each of the
# first two takes in every mod its members must load after, and the last every mod that must load after its members. Every rule
# still counts across groups: the group is only the first thing chosen by.
GAME_GROUP, TOP_GROUP, MIDDLE_GROUP, BOTTOM_GROUP = 0, 1, 2, 3
RULE_MOVE, GROUP_MOVE, ORDER_MOVE, ROOM_MOVE = "rule", "group", "order", "room"
# Where each group goes, for a group move's reason (1.88.0: each move names its own reason, not every reason a group has).
GROUP_PLACES = {GAME_GROUP: "the game's own group, which loads first",
                TOP_GROUP: "the frameworks' group, which loads before the other mods",
                BOTTOM_GROUP: "the bottom group, which loads after the other mods"}
RULES_FORMAT = 1
RULE_KINDS = ("after", "before", "top", "bottom")


@dataclass(frozen=True)
class Rule:
    """One mod loads before another: `first` then `then`, both as the adapter keys them."""
    first: str
    then: str
    source: str
    by: str                      # who says so, in words: a mod's name, "the community rules", "your rules in RimSort"
    note: str = ""


@dataclass
class Placing:
    """A mod asked to load at the top or the bottom, and who asked."""
    key: str
    where: int                   # TOP or BOTTOM
    source: str
    by: str
    note: str = ""


@dataclass
class RuleSet:
    """Rules handed over by an adapter or kept here: {key: {"after": [(id, note)], "before": [...], "top": note|None,
    "bottom": note|None}}."""
    source: str
    label: str
    where: str
    rules: dict = field(default_factory=dict)
    editable: bool = False


# ---------------------------------------------------------------- the owner's own rules, kept here

def rules_file(game, environ=None, settings=None):
    return folder(game, environ, settings) / "rules.json"


def load_own_rules(path):
    """[{"mod", "kind", "other", "added"}] from the owner's rules file; empty when there is none."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("format") != RULES_FORMAT:
        return []
    return [r for r in data.get("rules", []) if isinstance(r, dict) and r.get("kind") in RULE_KINDS and r.get("mod")]


def _save_own_rules(path, rules):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"format": RULES_FORMAT, "rules": rules}, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def add_rule(adapter, path, mod, kind, other="", now=None):
    """Adds one of the owner's rules; refuses a rule about a mod and itself, a rule already there, or one with no other mod."""
    if kind not in RULE_KINDS:
        raise FixError(f"A rule says a mod loads {', '.join(RULE_KINDS)}; not {kind!r}.")
    if kind in ("after", "before") and not other:
        raise FixError(f"Say which mod it loads {kind}.")
    if kind in ("after", "before") and adapter.key(mod) == adapter.key(other):
        raise FixError("A mod cannot load before or after itself.")
    rules = load_own_rules(path)
    for rule in rules:
        if (adapter.key(rule["mod"]) == adapter.key(mod) and rule["kind"] == kind
                and adapter.key(rule.get("other", "")) == adapter.key(other if kind in ("after", "before") else "")):
            raise FixError("That rule is kept already.")
    stamp = (now or datetime.now(timezone.utc)).date().isoformat()
    rule = {"mod": mod, "kind": kind, "other": other if kind in ("after", "before") else "", "added": stamp}
    _save_own_rules(path, rules + [rule])
    return rule


def drop_rule(path, number):
    """Takes away the owner's rule at this place (1 is the first listed)."""
    rules = load_own_rules(path)
    if not 1 <= number <= len(rules):
        raise FixError(f"There is no rule {number}; there are {len(rules)}.")
    gone = rules.pop(number - 1)
    _save_own_rules(path, rules)
    return gone


def own_rule_set(adapter, path):
    rules = {}
    for rule in load_own_rules(path):
        entry = rules.setdefault(adapter.key(rule["mod"]), {"after": [], "before": [], "top": None, "bottom": None})
        if rule["kind"] in ("after", "before"):
            entry[rule["kind"]].append((rule["other"], ""))
        else:
            entry[rule["kind"]] = ""
    return RuleSet(YOURS, "Your rules here", str(path), rules, editable=True)


def rule_words(rule):
    if rule["kind"] in ("after", "before"):
        return f"{rule['mod']} loads {rule['kind']} {rule['other']}"
    return f"{rule['mod']} loads at the {rule['kind']}"


# ---------------------------------------------------------------- every rule that bears on one list

def _name(mods, key):
    mod = mods.get(key)
    return (mod.name or mod.id) if mod else key


def gather(adapter, keys, installed, rule_sets):
    """(rules, placings) among the mods on the list (as keys), from their own files and every rule set handed in."""
    on = set(keys)
    mods = {}
    for key in keys:
        mod = installed.first([key]) if installed is not None else None
        if mod is not None:
            mods[key] = mod
    rules, placings = [], []
    for key, mod in mods.items():
        name = mod.name or mod.id
        for other in mod.load_after:
            rules.append(Rule(adapter.key(other), key, OWN, name))
        for other in mod.load_before:
            rules.append(Rule(key, adapter.key(other), OWN, name))
        for need in mod.needs:
            found = next((adapter.key(i) for i in need.ids if adapter.key(i) in on), None)
            if found:
                rules.append(Rule(found, key, NEEDS, name))
    for rule_set in rule_sets:
        for raw_key, entry in rule_set.rules.items():
            key = adapter.key(raw_key)
            if key not in on:
                continue
            for other, note in entry.get("after", []):
                rules.append(Rule(adapter.key(other), key, rule_set.source, rule_set.label, note))
            for other, note in entry.get("before", []):
                rules.append(Rule(key, adapter.key(other), rule_set.source, rule_set.label, note))
            for where, word in ((TOP, "top"), (BOTTOM, "bottom")):
                if entry.get(word) is not None:
                    placings.append(Placing(key, where, rule_set.source, rule_set.label, entry[word]))
    rules = [r for r in rules if r.first in on and r.then in on and r.first != r.then]
    return rules, placings, mods


# ---------------------------------------------------------------- the sort itself

def _strongest(rules):
    """One rule per ordered pair: the strongest source's."""
    best = {}
    for rule in rules:
        pair = (rule.first, rule.then)
        if pair not in best or STRENGTH[rule.source] > STRENGTH[best[pair].source]:
            best[pair] = rule
    return best


def _before_the_game(edges, game_keys):
    """Every mod that some rule puts before one of the game's own (directly or through others)."""
    into = {}
    for first, then in edges:
        into.setdefault(then, set()).add(first)
    found, waiting = set(), list(game_keys)
    while waiting:
        for first in into.get(waiting.pop(), ()):
            if first not in found and first not in game_keys:
                found.add(first)
                waiting.append(first)
    return found


def _find_loop(nodes, edges):
    """A loop of keys among the nodes left (each must load after the one before it), or None."""
    out = {}
    for first, then in edges:
        if first in nodes and then in nodes:
            out.setdefault(first, []).append(then)
    state = {}
    for start in sorted(nodes):
        if state.get(start):
            continue
        path, stack = [], [(start, iter(out.get(start, ())))]
        state[start] = 1
        path.append(start)
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                state[node] = 2
                stack.pop()
                path.pop()
                continue
            if state.get(child) == 1:
                return path[path.index(child):] + [child]
            if not state.get(child):
                state[child] = 1
                path.append(child)
                stack.append((child, iter(out.get(child, ()))))
    return None


def _settle_loops(keys, best):
    """Sets aside the weakest rule of every loop until none is left; returns the rules set aside, as loops were found."""
    set_aside = []
    while True:
        indegree = {k: 0 for k in keys}
        out = {}
        for first, then in best:
            indegree[then] += 1
            out.setdefault(first, []).append(then)
        ready = [k for k in keys if indegree[k] == 0]
        done = 0
        while ready:
            node = ready.pop()
            done += 1
            for then in out.get(node, ()):
                indegree[then] -= 1
                if indegree[then] == 0:
                    ready.append(then)
        if done == len(keys):
            return set_aside
        left = {k for k in keys if indegree[k] > 0}
        loop = _find_loop(left, best)
        if loop is None:                      # cannot happen with a loop left; refuse rather than spin
            raise FixError("The rules could not be put in order.")
        links = [best[(loop[n], loop[n + 1])] for n in range(len(loop) - 1)]
        weakest = min(links, key=lambda r: STRENGTH[r.source])
        set_aside.append({"rule": weakest, "loop": [link for link in links]})
        del best[(weakest.first, weakest.then)]


def _kahn(keys, edges, priority, backwards=False):
    """The keys in an order that keeps every edge, choosing the smallest priority among those ready. Backwards builds the list from
    its end, choosing the largest."""
    indegree = {k: 0 for k in keys}
    out = {}
    for first, then in edges:
        a, b = (then, first) if backwards else (first, then)
        indegree[b] += 1
        out.setdefault(a, []).append(b)
    sign = -1 if backwards else 1
    ready = [(_signed(priority[k], sign), k) for k in keys if indegree[k] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        _, node = heapq.heappop(ready)
        order.append(node)
        for b in out.get(node, ()):
            indegree[b] -= 1
            if indegree[b] == 0:
                heapq.heappush(ready, (_signed(priority[b], sign), b))
    return order[::-1] if backwards else order


def _signed(value, sign):
    return tuple(_signed(v, sign) for v in value) if isinstance(value, tuple) else (value * sign if sign < 0 else value)


def kept_run(old_place, order):
    """The longest run of the new order whose old places rise: the mods that keep their order. The rest moved."""
    places = [old_place[k] for k in order]
    tails, tail_at, back = [], [], [-1] * len(places)
    for n, place in enumerate(places):
        at = bisect.bisect_left(tails, place)
        if at == len(tails):
            tails.append(place)
            tail_at.append(n)
        else:
            tails[at] = place
            tail_at[at] = n
        back[n] = tail_at[at - 1] if at > 0 else -1
    kept, n = set(), tail_at[-1] if tail_at else -1
    while n >= 0:
        kept.add(order[n])
        n = back[n]
    return kept


def arrange(adapter, mod_list, installed, rule_sets, how=FEWEST):
    """The list sorted, and every move explained. Changes nothing."""
    if how not in (FEWEST, FULL):
        raise FixError(f"Sort the fewest moves ({FEWEST}) or a full re-sort ({FULL}); not {how!r}.")
    ids = list(mod_list.ids)
    keys = [adapter.key(i) for i in ids]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    if twice:
        raise FixError(f"{', '.join(twice)} {'is' if len(twice) == 1 else 'are'} on the list twice: take the extra off first "
                       "(What's wrong offers it).")
    listed = dict(zip(keys, ids))
    rules, placings, mods = gather(adapter, keys, installed, rule_sets)
    game_keys = {k for k, m in mods.items() if m.source == "game"}
    tier = {k: NORMAL for k in keys}
    placed_by = {}
    for placing in sorted(placings, key=lambda p: STRENGTH[p.source]):
        tier[placing.key] = placing.where            # the strongest source's placing wins
        placed_by[placing.key] = placing
    on = set(keys)
    frameworks = {adapter.key(i) for i in getattr(adapter, "known_frameworks", ())} & on
    top_base = frameworks | {k for k in keys if tier[k] == TOP}
    bottom_base = {k for k in keys if tier[k] == BOTTOM}
    # Needs make no order rule for frameworks and "top" or "bottom" mods (as RimSort): their needs usually mean "install this".
    rules = [r for r in rules if not (r.source == NEEDS and r.then in top_base | bottom_base)]
    best = _strongest(rules)
    # A mod others' code builds on no longer joins the frameworks (1.88.0; the owner's choice of 23 Nov 2026): its code rules
    # still order each pair, but it is not pulled up with the frameworks, so the groups are RimSort's tiers and no more.
    game_base = (game_keys | {adapter.key(i) for i in getattr(adapter, "tier_zero", ())}) & on
    group, via = _groups(keys, list(best), game_base, top_base, bottom_base)
    based = {}
    for k in game_base:
        based[k] = "it is one of the game's own" if k in game_keys else "it is a loader that goes with the game's own"
    for k in top_base - game_base:
        placing = placed_by.get(k)
        based[k] = ("it is a known framework" if k in frameworks
                    else f"it loads at the top ({placing.by}" + (f": {placing.note}" if placing.note else "") + ")")
    for k in bottom_base - game_base - top_base:
        placing = placed_by[k]
        based[k] = f"it loads at the bottom ({placing.by}" + (f": {placing.note}" if placing.note else "") + ")"
    early = _before_the_game(list(best), game_keys)
    implicit = {}
    for key in keys:
        if key in game_keys or key in early or how != FULL:
            continue
        for game in game_keys:
            if (game, key) not in best:
                implicit[(game, key)] = Rule(game, key, GAME, "a full re-sort puts the game's own first")
    set_aside = _settle_loops(keys, {**implicit, **best})
    edges = dict(implicit)
    edges.update(best)
    for gone in set_aside:
        edges.pop((gone["rule"].first, gone["rule"].then), None)
    old_place = {k: n for n, k in enumerate(keys)}
    if how == FULL:
        priority = {k: (group[k], 0 if k in game_keys else 1, _name(mods, k).lower(), k) for k in keys}
        order = _kahn(keys, edges, priority)
    else:
        priority = {k: (group[k], old_place[k]) for k in keys}
        forward = _kahn(keys, edges, priority)
        backward = _kahn(keys, edges, priority, backwards=True)
        order = min((forward, backward), key=lambda o: len(keys) - len(kept_run(old_place, o)))
    kept = kept_run(old_place, order)
    new_place = {k: n for n, k in enumerate(order)}
    moves = []
    for key in order:
        # A mod whose place number does not change is not listed, though the mods around it moved (1.88.0).
        if key in kept or old_place[key] == new_place[key]:
            continue
        moves.append(_explain(key, old_place, new_place, edges, placed_by, mods, kept, how, group,
                              _group_reason(key, group, via, based, mods)))
    return {"how": how, "ids": [listed[k] for k in order], "keys": order, "moves": moves,
            "set_aside": [_aside(gone, mods) for gone in set_aside],
            "rules": {source: sum(1 for r in best.values() if r.source == source) for source in RULE_SOURCES},
            "placings": {"top": sum(1 for t in tier.values() if t == TOP), "bottom": sum(1 for t in tier.values() if t == BOTTOM)},
            "groups": {"game": sum(1 for g in group.values() if g == GAME_GROUP),
                       "top": sum(1 for g in group.values() if g == TOP_GROUP),
                       "bottom": sum(1 for g in group.values() if g == BOTTOM_GROUP)},
            "count": len(keys)}


def _said(rule, mods):
    who = rule.by if rule.source in (YOURS, CODE, WORKSHOP, COMMUNITY, GAME) else f"{rule.by}: {SOURCE_WORDS[rule.source]}"
    text = f"{_name(mods, rule.then)} loads after {_name(mods, rule.first)} ({who})"
    return text + (f". {rule.note}" if rule.note else "")


def _groups(keys, edges, game_base, top_base, bottom_base):
    """Each mod's group: the game's own and its loaders with everything they must load after; frameworks and "top" mods with
    everything they must load after; "bottom" mods with everything that must load after them; the rest in the middle."""
    before, after = {}, {}
    for first, then in edges:
        before.setdefault(then, set()).add(first)
        after.setdefault(first, set()).add(then)

    via = {}

    def reach(start, links):
        found, waiting = set(start), list(start)
        while waiting:
            member = waiting.pop()
            for other in links.get(member, ()):
                if other not in found:
                    found.add(other)
                    via.setdefault(other, member)
                    waiting.append(other)
        return found

    game = reach(game_base, before)
    top = reach(top_base, before) - game
    bottom = reach(bottom_base, after) - game - top
    group = {k: GAME_GROUP if k in game else TOP_GROUP if k in top else BOTTOM_GROUP if k in bottom else MIDDLE_GROUP
             for k in keys}
    return group, via


def _group_reason(key, group, via, based, mods):
    """Why this mod is in its group, in words: its own reason, or the member it must load before (or after, at the bottom)."""
    level = group.get(key, MIDDLE_GROUP)
    if level == MIDDLE_GROUP:
        return None
    if key in based:
        why = based[key]
    elif level == BOTTOM_GROUP:
        why = f"it loads after {_name(mods, via[key])}, which goes at the bottom"
    else:
        why = f"{_name(mods, via[key])} loads after it"
    return f"{_name(mods, key)}: {why}, so it goes in {GROUP_PLACES[level]}."


def _explain(key, old_place, new_place, edges, placed_by, mods, kept, how=FEWEST, group=None, group_reason=None):
    reasons, sources = [], []
    for (first, then), rule in edges.items():
        if key not in (first, then) or old_place[first] < old_place[then]:
            continue
        reasons.append(_said(rule, mods))
        sources.append(rule.source)
    placing = placed_by.get(key)
    if reasons and placing is not None:
        sources.append(placing.source)
    if not reasons and how == FEWEST:
        for (first, then), rule in edges.items():
            if key in (first, then) and (then if first == key else first) not in kept:
                reasons.append(f"Moved with {_name(mods, then if first == key else first)}: " + _said(rule, mods))
                sources.append(rule.source)
                break
    kind = RULE_MOVE if reasons else ROOM_MOVE
    level = (group or {}).get(key, MIDDLE_GROUP)
    if not reasons and level != MIDDLE_GROUP and group_reason:
        kind = GROUP_MOVE
        if placing is not None:
            sources.append(placing.source)
        reasons.append(group_reason)
    elif not reasons and how == FULL:
        kind = ORDER_MOVE
        reasons.append("No rule places it: a full re-sort puts such mods in order of their names.")
    if not reasons:
        reasons.append("Moved to make room for the mods around it.")
    return {"key": key, "name": _name(mods, key), "from": old_place[key] + 1, "to": new_place[key] + 1,
            "why": reasons, "sources": sorted(set(sources), key=lambda s: -STRENGTH[s]), "kind": kind}


def _aside(gone, mods):
    rule = gone["rule"]
    loop = " → ".join([_name(mods, link.first) for link in gone["loop"]] + [_name(mods, gone["loop"][-1].then)])
    return {"rule": _said(rule, mods), "source": rule.source, "loop": loop,
            "why": "These rules form a loop, so not all of them can be kept; the weakest was set aside."}


def rule_data(rule_set):
    data = asdict(rule_set)
    data["count"] = len(rule_set.rules)
    data.pop("rules")
    return data


def owner_rules(adapter, environ=None, settings=None):
    """Every rule set that is the owner's: the ones kept here, then any a mod manager keeps for them."""
    sets = [own_rule_set(adapter, rules_file(adapter.game, environ, settings))]
    sets += [s for s in (adapter.rule_sets() if hasattr(adapter, "rule_sets") else []) if s.source == YOURS]
    return sets


def every_rule_set(adapter, environ=None, settings=None):
    sets = [own_rule_set(adapter, rules_file(adapter.game, environ, settings))]
    return sets + list(adapter.rule_sets() if hasattr(adapter, "rule_sets") else [])


def sort_list(adapter, mod_list, how=FEWEST, environ=None, settings=None):
    installed = Installed(adapter, adapter.installed())
    return arrange(adapter, mod_list, installed, every_rule_set(adapter, environ, settings), how)
