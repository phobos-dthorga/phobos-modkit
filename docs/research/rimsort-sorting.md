# RimSort's sorting, studied (23 Nov 2026)

**Why:** the owner asked (23 Nov 2026) whether RimSort's code was worth studying "before any further changes", after two of our
full re-sort designs failed on their list: 1.79.0 put Vanilla Expanded Framework 176 places down, and a narrower "libraries first"
tried after 1.85.0 put it back down to 181. This record says how RimSort sorts, compares it with the kit's sorter
(`python/phobos_modkit/mod_sort.py`), and proposes changes for the owner to choose.

**Source:** RimSort's public repository (github.com/RimSort/RimSort), commit d446d3b, cloned to `K:\phobos-modkit\sources\RimSort`.
**Licence: GPL-3.0.** The kit is MIT, so nothing here is copied: this is a summary in our own words. Package ids named below are
facts about mods, not RimSort's expression. Files read: `app/controllers/sort_controller.py`, `app/sort/topo_sort.py`,
`app/sort/dependencies.py`, `app/sort/alphabetical_sort.py`, `app/models/metadata/metadata_structure.py` (the compiled graph and
the rule merge), `app/models/metadata/metadata_factory.py` (About.xml rules), `app/utils/constants.py` (the known tiers),
`app/controllers/metadata_controller.py` and `app/services/dependency_resolver.py`.

## How RimSort sorts

1. **Rules per mod.** A mod's rules are the union of three sources: its About.xml (load before and after; `forceLoad*` always;
   `...ByVersion` lists for the running version when "prefer versioned About tags" is on), the community rules, and the user's
   rules. Nothing ranks them: conflicting rules stay, and the code says they "may cause issue at sort". "Load at the top" or "at
   the bottom" holds when any source says so.
2. **Needs as load-after** (the setting "use modDependencies as loadAfter"): a mod's needs become load-after edges, with two
   exceptions. Mods in tier one or tier three get none inferred, and an inferred edge is dropped when an explicit rule says the
   opposite. Alternative package ids satisfy a need when that setting is on.
3. **Four tiers, sorted one at a time and joined in order:**
   - **Tier 0**: a fixed list: Prepatcher, Harmony, Visual Exceptions, Core and the five expansions, **plus every mod they depend
     on, recursively**.
   - **Tier 1**: a hand-kept list of known frameworks (in this commit: Adaptive Storage Framework, Aoba's framework and Exosuit
     framework, EBSG framework, XML Extensions, Ritual Attachable Outcomes, a local ASF build, Vanilla Expanded Framework, Cherry
     Picker, Better Prerequisites, Vehicle Framework, HugsLib and Vanilla Backgrounds Expanded), plus every mod any rule says to
     load at the top, **plus every mod they depend on, recursively**.
   - **Tier 3**: every mod a rule says to load at the bottom, **plus every mod that must load after them, recursively**.
   - **Tier 2**: everything else.
4. **Inside a tier**, only the edges between its own mods are kept, and one of two sorts runs:
   - **Topological** (the default): the tier's mods in dependency levels (those that depend on nothing first, then the next
     level), alphabetical by name within a level.
   - **Alphabetical** (marked deprecated, "may produce incorrect results"): by name, each mod's dependencies pulled in just
     before it.
5. **A loop of rules stops the sort:** "Unable to Sort", with each loop listed. Nothing is set aside.
6. **The Steam Workshop database is not a sort source.** It is used to find Workshop numbers for missing dependencies. **No Version
   Warning** and **Use This Instead** are read for warnings and replacements, not order.

**What keeps frameworks high is the tiers, not the sort itself.** The recursive pull is the subtle part: a tier-one framework
brings along whatever it depends on. That is why Vanilla Backgrounds Expanded sits in the hand list: it must load before Vanilla
Expanded Framework, and otherwise would hold the framework back, which is exactly what sank it in our second attempt.

## Compared with ours

| | RimSort | The kit (1.85.0) |
| --- | --- | --- |
| Keeps your order where no rule decides | No: always rebuilds | Fewest moves does; full re-sort rebuilds |
| Frameworks first | Tiers: a hand list plus "load at the top", each pulling in what it depends on | Full re-sort: any mod others load after, most used first (1.84.0) |
| Load at the bottom | Tier three, pulling in what must load after it | A priority only, nothing pulled along |
| Rule sources | About, community, user: a union | Yours, its code, its own files, needs, Workshop page, community: ranked |
| Conflicting rules | Left in; may break the sort | Ranked; the weakest of a loop set aside and named |
| Needs as load-after | Optional; skipped for tier one and three; an explicit opposite rule wins | Always; ranked under the mod's own rules |
| What a mod's code builds on | Not read | Read from its assemblies (1.84.0) |
| Workshop "required items" | Not a sort source | A rule source (1.79.0) |
| Inside a group, where nothing decides | By dependency level, then name | By name (full) or your order (fewest) |
| A rule crossing tiers | Dropped by the tier split, silently | Every rule kept |
| Explanations | None | Every move, with whose rule |

## Proposals (for the owner to choose)

1. **Full re-sort by tiers, as RimSort does, keeping every rule.** Tier 0: the game's own, Harmony and Prepatcher; tier 1: known
   frameworks (a list of package ids kept as the RimWorld adapter's data, starting from the facts above) together with mods
   others' code builds on (ours alone) and "load at the top" mods; tier 3: "load at the bottom". **Each pulls in what it depends
   on (tiers 0 and 1) or what must follow it (tier 3)**: that is what our two attempts lacked. Unlike RimSort, rules crossing
   tiers are still obeyed by one sort over all mods, with the tier as the first key, so nothing is dropped silently.
2. **Inside a tier, keep names as the order** (our full re-sort) rather than dependency levels: levels reshuffle more, for no
   gain the rules do not already give.
3. **Group the moves in the preview** (already the owner's choice of 23 Nov 2026): moves a rule asks for first, then "libraries
   first" and "names in order" folded.
4. **Keep what RimSort lacks:** fewest moves, ranked rules with loops named, code rules, and explanations.
5. **Consider making needs-as-load-after skip tier-one and tier-three mods**, as RimSort does: a framework that names a need is
   usually saying "install this", not "load this first", and the inferred edge can drag it down.
6. **Workshop requirements stay a rule source, but the weakest after community**: RimSort does not sort by them, so they are the
   least proven of ours.

## What was adopted (1.86.0)

The owner's choices of 23 Nov 2026: proposals 1, 3 and 5; proposal 6 as "weakest of all"; and "top" and "bottom" as RimSort means
them (group membership), which also ended two moves fewest moves had always flagged on the owner's list. "Libraries first, the
most used first" (1.84.0) was removed.

## For a next game

The tiers are game-free; what each game gives is data: its tier-0 ids (the game's own and its loader, such as Harmony), its known
frameworks, and what its rules call "top" and "bottom". Project Zomboid would need its own small list (none is known yet).
