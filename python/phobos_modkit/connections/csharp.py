"""C# connections: exact from the assemblies the repository builds, placed in its source; by name from the source where none is built.

The assemblies are found by the projects in the repository: each .csproj's AssemblyName (or its file name), and the newest .dll of
that name anywhere in the repository outside obj folders. The kit's assembly reader (`calls`, `patches`) reads them without
loading or running them. A method's place in the source comes from the kit's C# scanner, matched by full name.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .. import assemblies
from ..code import scan
from . import Node, source_files

LANGUAGE = "csharp"
SKIPPED_BASES = {"System.Object", "System.ValueType", "System.Enum", "System.MulticastDelegate", ""}
_ASSEMBLY_NAME = re.compile(r"<AssemblyName>\s*([^<$]+?)\s*</AssemblyName>")
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*(?:<[^<>()]*>)?\s*\(")
_ACCESSORS = {"get_": "property", "set_": "property", "add_": "event", "remove_": "event"}
# .NET's own library: strings, lists, maths. Calls into it are most of any program's calls and say nothing about how its parts fit
# together, so they are left out (the game's engine and other mods stay).
_PLATFORM_ASSEMBLIES = ("System", "mscorlib", "netstandard", "Microsoft.")


def platform(type_name, assembly):
    return (type_name or "").startswith("System.") or (assembly or "").startswith(_PLATFORM_ASSEMBLIES)


def _projects(root):
    return [path for _, path in source_files(root, (".csproj",))]


def assembly_names(root):
    found = []
    for project in _projects(root):
        text = project.read_text(encoding="utf-8", errors="replace")
        named = _ASSEMBLY_NAME.search(text)
        found.append(named.group(1) if named else project.stem)
    return sorted(set(found))


def built_assemblies(root):
    """The newest built .dll of each of the repository's projects, outside obj folders."""
    wanted = {name.lower(): name for name in assembly_names(root)}
    newest = {}
    for folder, folders, files in os.walk(root):
        folders[:] = [f for f in folders if f not in {".git", "obj", "node_modules", ".local", "external"} and not f.startswith(".")]
        for name in files:
            stem = name[:-4].lower() if name.lower().endswith(".dll") else None
            if stem in wanted:
                path = Path(folder) / name
                if stem not in newest or path.stat().st_mtime > newest[stem].stat().st_mtime:
                    newest[stem] = path
    return sorted(newest.values())


def inputs(root):
    return [p for _, p in source_files(root, (".cs",))] + built_assemblies(root)


def node_id(type_name, member=None):
    return f"cs:{type_name}" + (f".{member}" if member else "")


def member_of(type_name, il_name):
    """The source's name for a compiled member, and its kind: get_Label is the property Label, .ctor the constructor."""
    if il_name == ".ctor":
        return type_name.rsplit(".", 1)[-1], "constructor"
    if il_name == ".cctor":
        return "static constructor", "constructor"
    for prefix, kind in _ACCESSORS.items():
        if il_name.startswith(prefix) and len(il_name) > len(prefix):
            return il_name[len(prefix):], kind
    return il_name, "method"


def _run(tool, command, paths):
    handle, listing = tempfile.mkstemp(prefix="phobos-connections-", suffix=".txt")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write("\n".join(str(p) for p in paths))
        result = subprocess.run([str(tool), command, "@" + listing], capture_output=True, check=False)
    finally:
        os.remove(listing)
    if result.returncode != 0:
        raise RuntimeError(f"The assembly reader failed: {(result.stderr or b'').decode('utf-8', 'replace')[-500:]}")
    return [json.loads(line) for line in result.stdout.decode("utf-8").splitlines() if line.strip()]


def _source_map(root):
    """Every declaration in the repository's C# source by full name: (file, first line, last line, kind)."""
    places = {}
    for relative, path in source_files(root, (".cs",)):
        try:
            found = scan.declarations(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 (a file the scanner cannot read still leaves the rest)
            continue
        for d in found:
            if d.kind != "namespace":
                places.setdefault(d.full, (relative, d.start, d.end, d.kind))
    return places


def _place(node, places):
    found = places.get(node.id[3:])
    if found:
        node.file, node.line, node.end = found[0], found[1], found[2]
    return node


def read(root, graph, environ=None):
    root = Path(root)
    if not source_files(root, (".cs",)) and not _projects(root):
        return None
    places = _source_map(root)
    dlls = built_assemblies(root)
    if dlls:
        try:
            tool = assemblies.ensure_reader(environ)
            read_built(graph, _run(tool, "calls", dlls), _run(tool, "patches", dlls), places)
            return f"exact, from {len(dlls)} built assembl{'y' if len(dlls) == 1 else 'ies'}"
        except (assemblies.ReaderError, RuntimeError, OSError, ValueError):
            pass   # the source still gives the shape, by name
    read_source(root, graph, places)
    return "by name, from the source (nothing built was found)"


def read_built(graph, call_records, patch_records, places):
    ours = {t["name"] for record in call_records for t in record.get("types", [])}
    # Read once for every virtual method (1.147.1): made afresh for each, they took ten seconds on a large repository.
    bases = {t["name"]: t["base"] for record in call_records for t in record.get("types", [])}
    declared = {(m["type"], m["name"]) for record in call_records for m in record.get("methods", [])}

    def member_node(type_name, il_name, assembly=None):
        name, kind = member_of(type_name, il_name)
        member_id = node_id(type_name, name)
        if type_name in ours:
            node = graph.nodes.get(member_id) or graph.add(_place(Node(member_id, f"{_short(type_name)}.{name}", kind, LANGUAGE,
                                                                       owner=node_id(type_name)), places))
            graph.link(node_id(type_name), member_id, "holds")
            return node
        graph.ensure(node_id(type_name), _short(type_name), "type", LANGUAGE, assembly=assembly or None)
        node = graph.ensure(member_id, f"{_short(type_name)}.{name}", kind, LANGUAGE, owner=node_id(type_name), assembly=assembly or None)
        graph.link(node_id(type_name), member_id, "holds")
        return node

    for record in call_records:
        assembly = record.get("assembly")
        for t in record.get("types", []):
            type_node = graph.add(_place(Node(node_id(t["name"]), _short(t["name"]), t["kind"], LANGUAGE, assembly=assembly,
                                              owner=_outer(t["name"], ours)), places))
            if type_node.owner:
                graph.link(type_node.owner, type_node.id, "holds")
            for base in [t["base"], *t["interfaces"]]:
                if base not in SKIPPED_BASES and not platform(base, None):
                    if base not in ours:
                        graph.ensure(node_id(base), _short(base), "type", LANGUAGE)
                    graph.link(type_node.id, node_id(base), "builds-on")
        for m in record.get("methods", []):
            if m["type"] not in ours:
                continue
            caller = member_node(m["type"], m["name"])
            for call in m.get("calls", []):
                if platform(call["type"], call.get("assembly")) and call["type"] not in ours:
                    continue
                if call["type"] in ours:
                    graph.link(caller.id, member_node(call["type"], call["name"]).id, "calls")
                elif call["type"]:
                    graph.link(caller.id, member_node(call["type"], call["name"], call.get("assembly")).id, "calls")
            for used in m.get("fields", []):
                if platform(used["type"], used.get("assembly")) and used["type"] not in ours:
                    continue
                field_id = node_id(used["type"], used["name"])
                if used["type"] in ours:
                    graph.add(_place(Node(field_id, f"{_short(used['type'])}.{used['name']}", "field", LANGUAGE,
                                          owner=node_id(used["type"])), places))
                    graph.link(node_id(used["type"]), field_id, "holds")
                else:
                    graph.ensure(field_id, f"{_short(used['type'])}.{used['name']}", "field", LANGUAGE, assembly=used.get("assembly"))
                graph.link(caller.id, field_id, "uses")
            if m.get("virtual"):
                _link_override(graph, bases, declared, m, caller, ours, member_node)
    for record in patch_records:
        for patch in record.get("patches", []):
            if not patch.get("targetType") or not patch.get("targetMember") or not patch.get("patchClass"):
                continue
            target_name = patch["targetMember"]
            if patch.get("methodType") == "Getter":
                target_name = f"get_{target_name}"
            elif patch.get("methodType") == "Setter":
                target_name = f"set_{target_name}"
            patch_node = member_node(patch["patchClass"], patch["patchMethod"])
            target = member_node(patch["targetType"], target_name)
            graph.link(patch_node.id, target.id, "patches")


def _link_override(graph, bases, declared, method, caller, ours, member_node):
    """A virtual method overrides its base type's method of the same name: exact within the repository, by name outside it.
    `bases` maps each of our types to its base; `declared` holds every (type, method) our code declares."""
    base = bases.get(method["type"])
    while base and base not in SKIPPED_BASES:
        if base in ours:
            if (base, method["name"]) in declared:
                graph.link(caller.id, member_node(base, method["name"]).id, "overrides")
                return
            base = bases.get(base)
        else:
            graph.link(caller.id, member_node(base, method["name"]).id, "overrides", exact=False)
            return


def read_source(root, graph, places):
    """By name: types and members from the source, and a call wherever a member's body names a method only one or two types declare."""
    by_name = {}
    for full, (file, start, end, kind) in places.items():
        owner, _, name = full.rpartition(".")
        node = graph.add(Node(node_id(full), f"{_short(owner)}.{name}" if owner else name, kind, LANGUAGE, file, start, end,
                              owner=node_id(owner) if owner in places else None))
        if node.owner:
            graph.link(node.owner, node.id, "holds", exact=True)
        if kind in ("method", "constructor"):
            by_name.setdefault(name, []).append(node.id)
    texts = {}
    for full, (file, start, end, kind) in places.items():
        if kind not in ("method", "constructor", "property"):
            continue
        if file not in texts:
            texts[file] = scan.blank((Path(root) / file).read_text(encoding="utf-8", errors="replace")).splitlines()
        body = "\n".join(texts[file][start - 1:end])
        for called in set(_CALL.findall(body)):
            targets = by_name.get(called, [])
            if 0 < len(targets) <= 2:
                for target in targets:
                    graph.link(node_id(full), target, "calls", exact=False)


def _short(type_name):
    return type_name.rsplit(".", 1)[-1]


def _outer(type_name, ours):
    outer = type_name.rsplit(".", 1)[0] if "." in type_name else None
    return node_id(outer) if outer in ours else None


def declared_in(text, relative):
    """Every declaration in a C# file's text, as (id, first line, last line): for what a commit's changed lines changed."""
    return [(node_id(d.full), d.start, d.end) for d in scan.declarations(text) if d.kind != "namespace"]
