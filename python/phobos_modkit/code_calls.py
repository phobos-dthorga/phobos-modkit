"""What a commit did to its C# methods' calls, and the rings of calls it made or cut (1.116.0; D'thorga Companion's
docs/code-reading.md, step 6). Game-free; a game's adapter may offer its own assemblies for the bodies of its methods.

The names reader (Roslyn) reads every method in the files the commit changed twice, as they stood before the commit and after
it, each a build of its own with those files swapped in; every other file is read as it stands now. For each method: the calls
the commit took away, the calls it added, those it kept, and calls that moved whole from one of its methods to another.

A ring is a loop of calls. It is followed through our own code, through a method of ours the changed methods call through
`base` or override (read one level deep), through a virtual call on the same object landing in an override of ours, and, when
the game is named and its adapter finds its own assemblies, through a game method a changed method hands on to (its body read
by the kit's assembly reader, `calls-of`) calling back into an override of ours: the ring behind phobos-rimworld's crashes of
23 November 2026. Only rings holding a method the commit changed are given, and only those it made or cut are news. A ring is
not always a fault: it is shown for a person to judge.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from . import assemblies, changes, games
from .code_names import NamesError, TOOL, describe_all, project_for
from .dotnet_tools import ToolBuildError

MAX_FILES = 12
MAX_RING = 8
MAX_RINGS = 40
READ_TIMEOUT = 600


def _changed_files(root, commit):
    """(before, after) paths of each C# file the commit changed; None where the file did not exist on that side."""
    found = []
    text = changes.git(root, "show", "--format=", "--name-status", "-M", "--no-color", commit, check=False)
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        before, after = (parts[1], parts[2]) if status in "RC" and len(parts) > 2 else (parts[1], parts[1])
        if status == "A":
            before = None
        if status == "D":
            after = None
        if any(p and p.lower().endswith(".cs") for p in (before, after)):
            found.append((before, after))
    return found


def _key(item):
    return item.get("id") or f"{item['type']}.{item['name']}"


def node_of(item):
    """The connections id of a method (`cs:Phobos.Boat.Float`), from its documentation id; None for one with none."""
    doc = item.get("id") or ""
    if not doc[:2] in ("M:", "P:", "T:", "F:", "E:"):
        return None
    full = doc[2:].split("(")[0]
    full = full.split("``")[0]
    if full.endswith((".#ctor", ".#cctor")):
        kind = full.rsplit(".", 1)[0]
        full = f"{kind}.{kind.rsplit('.', 1)[-1]}"
    return f"cs:{full}"


def _call(call):
    """A call as the answer gives it: what it is, where, and how it is made."""
    found = {"key": _key(call), "display": call["display"], "viaBase": bool(call.get("viaBase"))}
    if call.get("file"):
        found.update(file=call["file"], line=call.get("line"), node=node_of(call))
    else:
        found["assembly"] = call.get("assembly")
    return found


def compare(before, after):
    """Each method whose calls the commit changed, and calls that moved whole between them."""
    old = {_key(m): m for m in before if not m.get("base")}
    new = {_key(m): m for m in after if not m.get("base")}
    methods = []
    for key in sorted(set(old) | set(new)):
        b, a = old.get(key), new.get(key)
        b_calls = {_key(c): c for c in (b or {}).get("calls", [])}
        a_calls = {_key(c): c for c in (a or {}).get("calls", [])}
        status = "added" if b is None else "removed" if a is None else "changed" if set(b_calls) != set(a_calls) else None
        if status is None:
            continue
        shown = a or b
        methods.append({
            "key": key, "id": shown.get("id"), "node": node_of(shown), "display": shown["display"], "file": shown["file"],
            "line": shown["line"], "end": shown["end"], "status": status,
            "gone": [_call(b_calls[k]) for k in sorted(set(b_calls) - set(a_calls))],
            "new": [_call(a_calls[k]) for k in sorted(set(a_calls) - set(b_calls))],
            "kept": [_call(a_calls[k]) for k in sorted(set(a_calls) & set(b_calls))],
        })
    for source in methods:
        gone = {c["key"] for c in source["gone"]}
        for target in methods:
            if target is source:
                continue
            moved = sorted(gone & {c["key"] for c in target["new"]})
            if moved:
                source.setdefault("movedTo", []).append({"key": target["key"], "display": target["display"], "calls": moved})
                target.setdefault("movedFrom", []).append({"key": source["key"], "display": source["display"], "calls": moved})
    return methods


def handed_on(methods):
    """The outside methods a change hands on to and whose bodies may call back into ours: called through `base`, or virtually
    on the same object. (type, name, assembly) each."""
    wanted = set()
    for method in methods:
        for call in method["calls"]:
            if call.get("assembly") and not call.get("file") and (call.get("viaBase") or (call.get("virtual") and call.get("onThis"))):
                wanted.add((call["type"], call["name"], call["assembly"]))
    return wanted


def graph(methods, bodies):
    """The calls among one version's methods, with the steps a virtual call or a game method's call back may take into an
    override of ours: {key: set of keys}, and each node's words."""
    by_key = {_key(m): m for m in methods}
    dispatch = {}
    for method in methods:
        if method.get("overrides"):
            dispatch.setdefault((method["overrides"]["type"], method["overrides"]["name"]), []).append(_key(method))
    edges, words, outside = {}, {k: m["display"] for k, m in by_key.items()}, set()
    for key, method in by_key.items():
        steps = edges.setdefault(key, set())
        for call in method["calls"]:
            target = _key(call)
            words.setdefault(target, call["display"])
            if target in by_key or call.get("file"):
                steps.add(target)
            # A virtual call on the same object may land in an override of ours; a call through `base` never does.
            if call.get("virtual") and call.get("onThis") and not call.get("viaBase"):
                steps.update(dispatch.get((call["type"], call["name"]), []))
            body = bodies.get((call["type"], call["name"])) if call.get("assembly") and not call.get("file") else None
            if body is not None:
                steps.add(target)
                outside.add(target)
                back = edges.setdefault(target, set())
                for called_type, called_name in body:
                    back.update(dispatch.get((called_type or call["type"], called_name), []))
    return edges, words, outside


def rings(edges, holding):
    """Every loop of calls through at most `MAX_RING` steps holding one of `holding`, each once, written from the first of its
    steps in `holding` (by key), so a ring reads from where the change is and is written the same way in either version."""
    found = []

    def walk(start, node, path):
        if len(found) >= MAX_RINGS:
            return
        for step in sorted(edges.get(node, ())):
            if step == start:
                changed = sorted(set(path) & holding)
                if changed:
                    at = path.index(changed[0])
                    found.append(tuple(path[at:] + path[:at]))
            elif step > start and step not in path and len(path) < MAX_RING:
                walk(start, step, path + [step])

    for start in sorted(edges):
        walk(start, start, [start])
    return found


def _read_bodies(wanted, game, environ, run, reader):
    """The calls inside the outside methods wanted, from the game's own assemblies: {(type, name): [(type, name)]}, and the
    assemblies read. Empty when no game is named, its adapter finds no assemblies, or none of them holds the methods."""
    if not wanted:
        return {}, []
    files = [p for p in games.real_assemblies(game, environ) if Path(p).stem in {a for _, _, a in wanted}]
    if not files:
        return {}, []
    with tempfile.TemporaryDirectory(prefix="phobos-calls-of-") as scratch:
        listing = Path(scratch) / "methods.txt"
        listing.write_text("\n".join(f"{t}\t{n}" for t, n, _ in sorted(wanted)), encoding="utf-8")
        tool = reader or assemblies.ensure_reader(environ)
        result = run([str(tool), "calls-of", f"@{listing}", *[str(f) for f in files]], capture_output=True, check=False)
    if result.returncode != 0:
        return {}, []
    bodies = {}
    for line in (result.stdout or b"").decode("utf-8", "replace").splitlines():
        record = json.loads(line) if line.strip() else {}
        for method in record.get("methods", []):
            bodies[(method["type"], method["name"])] = [(c.get("type", ""), c.get("name", "")) for c in method.get("calls", [])]
    return bodies, [Path(f).stem for f in files]


def read(root, commit, game=None, environ=None, run=subprocess.run, progress=None, tool=None, reader=None):
    """What a commit did to its C# methods' calls, and the rings it made or cut. `tool` is the names reader, `reader` the
    assembly reader; by default the kit's, built on first use."""
    root = Path(root).resolve()
    pairs = _changed_files(root, commit)
    limits = []
    if len(pairs) > MAX_FILES:
        limits.append(f"The commit changed {len(pairs)} C# files; the first {MAX_FILES} were read.")
        pairs = pairs[:MAX_FILES]
    present = [p for pair in pairs for p in pair if p and (root / p).is_file()]
    projects = {}
    for file in present:
        project = project_for(root, file)
        if project is not None and str(project.resolve()).lower() not in {k.lower() for k in projects}:
            for described in describe_all(project, run, progress):
                projects.setdefault(described["path"], described)
    if not projects:
        raise NamesError("No C# project in this repository holds the files this commit changed.")
    with tempfile.TemporaryDirectory(prefix="phobos-calls-") as scratch:
        versions = []
        for name, revision in (("before", f"{commit}^"), ("after", commit)):
            texts = {}
            for index, pair in enumerate(pairs):
                path = pair[0] if name == "before" else pair[1]
                for other in pair:
                    if other and other != path:
                        texts[str(root / other)] = None
                if path is None:
                    continue
                text = changes.git(root, "show", f"{revision}:{path}", check=False)
                if text:
                    copy = Path(scratch) / f"{name}-{index}.cs"
                    copy.write_text(text, encoding="utf-8")
                    texts[str(root / path)] = str(copy)
                else:
                    texts[str(root / path)] = None
            versions.append({"name": name, "texts": texts})
        files = sorted({str(root / p) for pair in pairs for p in pair if p})
        request = {"projects": [{k: v for k, v in p.items() if k != "projectReferences"} for p in projects.values()],
                   "root": str(root), "context": 0, "versions": versions, "files": files}
        request_path = Path(scratch) / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        if tool is None:
            try:
                tool = TOOL.ensure(environ)
            except ToolBuildError as error:
                raise NamesError(str(error)) from None
        if progress:
            progress("Reading the commit's methods before and after it, with Roslyn")
        result = run([str(tool), str(request_path)], capture_output=True, text=True, encoding="utf-8", check=False,
                     timeout=READ_TIMEOUT)
    if result.returncode != 0:
        raise NamesError(f"The names reader could not read the commit's methods: {(result.stderr or '').strip()[-600:]}")
    answer = json.loads(result.stdout)
    by_version = {v["name"]: v["methods"] for v in answer["versions"]}
    before, after = by_version.get("before", []), by_version.get("after", [])
    methods = compare(before, after)
    wanted = handed_on(before) | handed_on(after)
    if progress and wanted:
        progress("Reading the game's methods the change hands on to")
    bodies, read_from = _read_bodies(wanted, game, environ, run, reader)
    if wanted and not bodies:
        limits.append("The game's own code was not read" + (f" ({game} has no reader of its assemblies here)" if game else
                      " (no game was named)") + ", so a ring through it is not seen.")
    holding = {m["key"] for m in methods}
    found = {}
    for name, version in (("before", before), ("after", after)):
        edges, words, outside = graph(version, bodies)
        found[name] = {ring: [{"key": k, "display": words.get(k, k), "outside": k in outside} for k in ring]
                       for ring in rings(edges, holding)}
    made = [found["after"][r] for r in found["after"] if r not in found["before"]]
    cut = [found["before"][r] for r in found["before"] if r not in found["after"]]
    standing = [found["after"][r] for r in found["after"] if r in found["before"]]
    limits.append("Every file the commit did not change is read as it stands now.")
    described = changes.describe(root, commit)
    return {"commit": {"hash": described.hash if described else commit, "subject": described.subject if described else ""},
            "files": [{"before": b, "after": a} for b, a in pairs], "methods": methods,
            "rings": {"made": made, "cut": cut, "standing": standing},
            "game": game, "gameRead": read_from, "seconds": answer.get("seconds", 0), "limits": limits}
