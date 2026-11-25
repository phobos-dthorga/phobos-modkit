"""What every name in one C# file is, and where it is declared: the names reader (dotnet/PhobosModKit.Names), run on the project
that holds the file. Game-free.

The project's source files and the assemblies it refers to are asked of MSBuild (`dotnet msbuild -getItem`), without building it,
and so are those of every project it refers to, so a name declared in another of the repository's projects is placed in its file.
The reader builds each project from source with Microsoft's Roslyn and reads the one file: for each name, what it is (a class, a
method, a parameter...), its full signature, and its declaration, as a file and lines of this repository or as another assembly.
For declarations in this repository it gives their lines, so a viewer can show them without reading the file itself.

At a commit, the file is read as it stood then; every other file is read as it stands now, and the answer says so. It only reads:
MSBuild is asked to list, never to build, and the reader parses source and reads assemblies' metadata without loading them.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import tempfile

from . import changes
from .connections import lua, rustcode, source_files, webcode
from .dotnet_tools import DotnetTool, ToolBuildError


class NamesError(RuntimeError):
    """The names could not be read; the words say why."""


TOOL = DotnetTool("PhobosModKit.Names", "names", "read the names in C# code", NamesError)
# A declaration's lines given with the answer, at most: enough for a method, the head of a class.
CONTEXT = 60
MAX_PROJECTS = 12
MSBUILD_TIMEOUT = 180
READ_TIMEOUT = 300
ITEMS = ("ReferencePath", "Compile", "ProjectReference")
PROPERTIES = ("AssemblyName", "LangVersion", "Nullable", "DefineConstants", "AllowUnsafeBlocks")


def project_for(root, file):
    """The project that holds a file: the one whose folder holds it most closely. None when no project does."""
    target = (Path(root) / file).resolve()
    best = None
    for _, project in source_files(root, (".csproj",)):
        folder = project.resolve().parent
        if folder in target.parents and (best is None or len(folder.parts) > len(best.resolve().parent.parts)):
            best = project
    return best


def _msbuild(project, run, restore):
    command = ["dotnet", "msbuild", str(project), "-nologo", "-t:ResolveAssemblyReferences", "-p:BuildProjectReferences=false"]
    command += [f"-getItem:{item}" for item in ITEMS] + [f"-getProperty:{name}" for name in PROPERTIES]
    if restore:
        command.insert(3, "-restore")
    return run(command, capture_output=True, text=True, check=False, timeout=MSBUILD_TIMEOUT)


def describe(project, run=subprocess.run):
    """A project as MSBuild lists it: its name, its source files, what it refers to, and how its code is read. A project never
    restored is restored first, which lists its packages but builds nothing."""
    result = _msbuild(project, run, restore=False)
    if result.returncode != 0 and "NETSDK1004" in (result.stdout or "") + (result.stderr or ""):
        result = _msbuild(project, run, restore=True)
    if result.returncode != 0:
        raise NamesError(f"MSBuild could not list {Path(project).name}'s files: {((result.stdout or '') + (result.stderr or ''))[-600:]}")
    text = result.stdout or ""
    try:
        found = json.loads(text[text.index("{"):])
    except ValueError as error:
        raise NamesError(f"MSBuild's list of {Path(project).name}'s files could not be read ({error}).") from None
    items, props = found.get("Items", {}), found.get("Properties", {})
    references = []
    for item in items.get("ReferencePath", []):
        source = item.get("MSBuildSourceProjectFile") if item.get("ReferenceSourceTarget") == "ProjectReference" else None
        references.append({"path": item.get("FullPath", ""), "project": source or None})
    return {
        "path": str(Path(project).resolve()),
        "name": props.get("AssemblyName") or Path(project).stem,
        "sources": [item["FullPath"] for item in items.get("Compile", []) if item.get("FullPath", "").lower().endswith(".cs")],
        "references": references,
        "langVersion": props.get("LangVersion") or None,
        "nullable": props.get("Nullable") or None,
        "defines": props.get("DefineConstants") or None,
        "allowUnsafe": str(props.get("AllowUnsafeBlocks", "")).lower() == "true",
        "projectReferences": [item["FullPath"] for item in items.get("ProjectReference", []) if item.get("FullPath")],
    }


def describe_all(project, run=subprocess.run, progress=None):
    """A project and every project it refers to, each listed once."""
    found, waiting = {}, [str(Path(project).resolve())]
    while waiting:
        path = waiting.pop()
        if path.lower() in found:
            continue
        if len(found) == MAX_PROJECTS:
            raise NamesError(f"{Path(project).name} refers to more than {MAX_PROJECTS} projects; the names were not read.")
        if progress:
            progress(f"Listing {Path(path).name}'s files", len(found) + 1, len(found) + 1 + len(waiting))
        described = describe(path, run)
        found[path.lower()] = described
        waiting.extend(str(Path(p).resolve()) for p in described["projectReferences"])
    return list(found.values())


def read(root, file, commit=None, environ=None, run=subprocess.run, progress=None, tool=None):
    """Every name in `file` (relative to `root`), as the names reader gives them, with the project and what limits the answer.
    `tool` is the reader's program; by default the kit's, built on first use."""
    root = Path(root).resolve()
    if Path(file).suffix.lower() != ".cs":
        raise NamesError(f"{file} is not C#; names are read exactly only in C#.")
    target = (root / file).resolve()
    if root not in target.parents:
        raise NamesError(f"{file} is not inside the repository.")
    project = project_for(root, file)
    if project is None:
        raise NamesError(f"No C# project in this repository holds {file}.")
    projects = describe_all(project, run, progress)
    if not any(Path(s).resolve() == target for s in projects[0]["sources"]):
        raise NamesError(f"{file} is not one of {projects[0]['name']}'s source files.")
    with tempfile.TemporaryDirectory(prefix="phobos-names-") as scratch:
        text_path = None
        if commit:
            text = changes.git(root, "show", f"{commit}:{Path(file).as_posix()}", check=False)
            if not text:
                raise NamesError(f"{file} did not exist at {commit[:8]}.")
            text_path = Path(scratch) / "text.cs"
            text_path.write_text(text, encoding="utf-8")
        request = {"projects": [{k: v for k, v in p.items() if k != "projectReferences"} for p in projects],
                   "project": projects[0]["path"], "file": str(target), "text": str(text_path) if text_path else None,
                   "root": str(root), "context": CONTEXT}
        request_path = Path(scratch) / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        if tool is None:
            try:
                tool = TOOL.ensure(environ)
            except ToolBuildError as error:
                raise NamesError(str(error)) from None
        if progress:
            progress(f"Reading {len(projects)} project{'s' if len(projects) != 1 else ''} with Roslyn")
        result = run([str(tool), str(request_path)], capture_output=True, text=True, encoding="utf-8", check=False,
                     timeout=READ_TIMEOUT)
    if result.returncode != 0:
        raise NamesError(f"The names reader could not read {file}: {(result.stderr or '').strip()[-600:]}")
    answer = json.loads(result.stdout)
    answer["projects"] = [p["name"] for p in projects]
    answer["commit"] = commit
    answer["limits"] = (["Every other file is read as it stands now, not as it stood at that commit."] if commit else [])
    if answer.get("missingReferences"):
        answer["limits"].append(f"{answer['missingReferences']} of the assemblies the project refers to were not found, so "
                                "names from them are not placed.")
    return answer


# ---------------------------------------------------------------- by name, for the languages Roslyn does not read (1.115.0)

#: The languages read by name, by file suffix, and the graph's languages a name in each may stand for.
BY_NAME = {".lua": ("lua", ("lua",)), ".py": ("python", ("python",)), ".xml": ("xml", ("xml", "csharp")),
           ".ts": ("typescript", ("typescript", "svelte")), ".svelte": ("svelte", ("typescript", "svelte")),
           ".rs": ("rust", ("rust",))}
MAX_CANDIDATES = 8
_WORD = re.compile(r"[A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*")
_PART = re.compile(r"[A-Za-z_]\w*")
_PY_SKIP = re.compile(r"(?s)(\"\"\"|''').*?\1|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|#[^\n]*")
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_XML_VALUE = re.compile(r">([^<]+)<|=\s*\"([^\"]*)\"")


def _blank(match):
    return re.sub(r"[^\n]", " ", match.group(0))


def _code_lines(text, language):
    """The text as the words in it can be read: comments and strings blanked in Lua and Python; in XML only element text and
    attribute values kept, the rest blanked. Line breaks and columns stay where they were."""
    if language == "lua":
        return lua._code(text).split("\n")
    if language == "python":
        return _PY_SKIP.sub(_blank, text).split("\n")
    if language in ("typescript", "svelte"):       # 1.128.0
        return webcode.code_of(text, language == "svelte").split("\n")
    if language == "rust":
        return rustcode.code_of(text).split("\n")
    text = _XML_COMMENT.sub(_blank, text)
    kept = [" "] * len(text)
    for match in _XML_VALUE.finditer(text):
        group = 1 if match.group(1) is not None else 2
        for at in range(match.start(group), match.end(group)):
            kept[at] = text[at]
    for at, char in enumerate(text):
        if char == "\n":
            kept[at] = "\n"
    return "".join(kept).split("\n")


def _index(conn, languages):
    """This repository's things in these languages, by their whole name and by the last part of it."""
    whole, last = {}, {}
    marks = ",".join("?" * len(languages))
    rows = conn.execute(f'SELECT id, name, kind, file, line, "end" FROM nodes WHERE external = 0 AND file IS NOT NULL '
                        f"AND language IN ({marks}) ORDER BY id", languages).fetchall()
    for node_id, name, kind, file, line, end in rows:
        thing = {"id": node_id, "name": name, "kind": kind, "file": file, "line": line, "end": end or line}
        full = node_id.split(":", 1)[1] if node_id.startswith(("cs:", "py:", "lua:")) else name
        for key in {full, name}:
            whole.setdefault(key, []).append(thing)
        last.setdefault(re.split(r"[.:/]", name)[-1], []).append(thing)
    return whole, last


def read_by_name(conn, root, file, text, commit=None):
    """Every name in a Lua, Python or XML file that names one of this repository's things, matched by name in the connections
    graph: a dotted name whole when the graph has it (a C# class named in a Def), else each part. Each says which things it may
    stand for, at most `MAX_CANDIDATES`, and is marked by name; a declaration's lines come with it, read as the file now stands."""
    language, languages = BY_NAME[Path(file).suffix.lower()]
    whole, last = _index(conn, languages)
    names, snippets, files = [], {}, {}
    for number, line in enumerate(_code_lines(text, language), 1):
        for match in _WORD.finditer(line):
            word = match.group(0)
            pieces = [(match.start(), word, whole.get(word))] if word in whole else \
                [(match.start() + p.start(), p.group(0), last.get(p.group(0))) for p in _PART.finditer(word)]
            for column, piece, things in pieces:
                if not things:
                    continue
                # A name at its own declaration means that thing, whatever else shares the name (1.117.0).
                things = [t for t in things if t["file"] == file and t["line"] == number] or things
                first = things[0]
                names.append({
                    "line": number, "column": column, "length": len(piece), "text": piece, "kind": first["kind"],
                    "display": first["name"], "id": None, "node": first["id"], "exact": False,
                    "here": len(things) == 1 and first["file"] == file and first["line"] == number,
                    "declared": {"file": first["file"], "line": first["line"], "end": first["end"]},
                    "candidates": things[:MAX_CANDIDATES], "more": max(0, len(things) - MAX_CANDIDATES)})
                for thing in things[:MAX_CANDIDATES]:
                    key = f"{thing['file']}:{thing['line']}"
                    if key not in snippets:
                        snippets[key] = snippet(root, thing, files)
    return {"file": file, "project": None, "projects": [], "names": names,
            "snippets": {k: v for k, v in snippets.items() if v}, "errors": 0, "missingReferences": 0, "seconds": 0,
            "commit": commit, "exact": False,
            "limits": ["Read by name, from this repository's connections as it now stands: a name may stand for any of the "
                       "things listed with it."] + (["The file is read as it stood at that commit."] if commit else [])}


def snippet(root, thing, files):
    """A thing's lines as its file now stands, at most `CONTEXT`; None when the file cannot be read."""
    path = Path(root) / thing["file"]
    if thing["file"] not in files:
        try:
            files[thing["file"]] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            files[thing["file"]] = None
    lines = files[thing["file"]]
    if not lines or not thing["line"]:
        return None
    start, end = thing["line"], max(thing["line"], thing["end"] or thing["line"])
    last = min(end, start + CONTEXT - 1, len(lines))
    return {"file": thing["file"], "start": start, "end": end, "lines": lines[start - 1:last], "cut": last < end}


def counts(answer):
    """How many names of each kind, and how many are declared in this repository."""
    kinds = {}
    for name in answer["names"]:
        kinds[name["kind"]] = kinds.get(name["kind"], 0) + 1
    ours = sum(1 for name in answer["names"] if name["declared"].get("file"))
    return dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))), ours
