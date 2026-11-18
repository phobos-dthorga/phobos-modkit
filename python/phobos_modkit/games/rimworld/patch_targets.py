"""The methods a repository's code patches, each with every other active mod patching it, and what its last update changed (1.37.0).

The repository's side comes from its connections graph (phobos-modkit `connections`): each Harmony patch its built assemblies
declare, from the patch method to the method it patches. The other mods' side comes from rimworld-patches' index of every active
mod's assemblies, less the repository's own (by assembly name). The update side, when asked, is rimworld-upstream's comparison of
the newest two versions the assembly archive kept of each file, matched by type and member name.

For D'thorga Companion's Code map (docs/cross-links.md there, L5): a badge on a method saying how crowded and how fresh the
method it patches is, so a risk shows where it sits.
"""
from __future__ import annotations

from pathlib import Path

from ... import connections
from ...connections import csharp

PATCH_EDGES = """SELECT e.source, e.target, n.name, n.assembly FROM edges e JOIN nodes n ON n.id = e.target
                 WHERE e.kind = 'patches' ORDER BY e.target, e.source"""
OTHERS = """SELECT DISTINCT o.mod, o.package_id, o.path, p.can_skip FROM patches p JOIN owners o ON o.path = p.path
            WHERE p.target_member = ? AND p.target_type = ?"""


def split_target(node_id):
    """(type, member) of a C# member's id: cs:Verse.Pawn.Tick gives ("Verse.Pawn", "Tick")."""
    name = node_id.split(":", 1)[-1]
    owner, _, member = name.rpartition(".")
    return owner, member


def ours(root):
    """The file names (lower case, no extension) of the assemblies the repository builds."""
    return {name.lower() for name in csharp.assembly_names(root)}


def targets(graph, index, root):
    """[{node, target, name, assembly, ours, mods, skippers}] for every method the repository's code patches.

    `ours` lists the repository's patch methods on it; `mods` the other active mods patching it, by name; `skippers` how many of
    their patches are prefixes that may skip the original.
    """
    own = ours(root)
    found = {}
    for source, target, name, assembly in graph.execute(PATCH_EDGES):
        entry = found.get(target)
        if entry is None:
            owner, member = split_target(target)
            mods, skippers = set(), 0
            for mod, package_id, path, can_skip in index.execute(OTHERS, (member, owner)):
                if Path(path).stem.lower() in own:
                    continue
                mods.add(mod or package_id)
                skippers += 1 if can_skip else 0
            entry = found[target] = {"node": target, "target": f"{owner}.{member}", "name": name, "assembly": assembly,
                                     "ours": [], "mods": sorted(mods), "skippers": skippers, "changed": []}
        if source not in entry["ours"]:
            entry["ours"].append(source)
    return list(found.values())


def join_updates(found, rows):
    """Adds each update row (rimworld-upstream's: owner, file, versions, Type.Member, change, ours) to the targets it names."""
    by_member = {}
    for item in found:
        owner, member = item["target"].rsplit(".", 1)
        by_member.setdefault((owner.rsplit(".", 1)[-1], member), []).append(item)
    for mod, file, versions, member, change, _ in rows:
        bare, _, name = member.rpartition(".")
        for item in by_member.get((bare, name), []):
            item["changed"].append({"mod": mod, "file": file, "versions": versions, "change": change.replace("**", "")})
    return found


def open_graph(root, environ=None, settings=None):
    return connections.open_graph(Path(root).resolve(), environ, settings)
