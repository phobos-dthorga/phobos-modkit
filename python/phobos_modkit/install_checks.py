"""What else differs between an installed mod and the repository's copy, beyond the changelogs (installs status, 1.21.0).

- Files: which of the mod's files would be added, changed or removed by installing, by kind (code, Defs, textures...). Files only an
  install has (the install record, generated files, encoded textures) are left out by the config's installOnly patterns.
- Builds: whether a C# project's sources are newer than the assembly it last built, so the repository's copy is behind its code.
  A project counts its own folder, the files it compiles from elsewhere (Compile Include) and the root build files the config
  names; never the projects it references, whose changes need not rebuild it.
- The installed commit: the install record's, or, for a copy installed before records began, the commit that first gave the mod
  its installed version (approximate: later commits may share the version).
- Settings changes since that commit, from the repository's own command (config settingsChanges), which prints JSON.
- Test rows an install would bring: rows still waiting whose named version of the mod is newer than the installed one and no newer
  than the repository's (phobos_modkit.testpass).
"""
from __future__ import annotations

from fnmatch import fnmatch
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from . import testpass

SKIP_DIRS = {"__pycache__", "obj", "bin", ".git"}
SKIP_SUFFIXES = (".pyc", ".pdb")
SYNC_CONFLICT = re.compile(r"_(Download|Upload|Case)Conflict", re.IGNORECASE)
CATEGORIES = ("code", "defs", "patches", "textures", "text", "sounds", "about", "other")
MAX_PATHS = 60
CHUNK = 1024 * 1024
BUILD_SLACK_SECONDS = 1.0       # file systems round times; a source this much newer than its build counts
WAITING = ("open", "partial", "seen")


# ---------------------------------------------------------------- files

def files_of(folder, install_only=()):
    """{relative path: (size, mtime)} of a mod folder, leaving out build clutter, sync conflict copies and install-only files."""
    folder = Path(folder)
    found = {}
    for current, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(SKIP_SUFFIXES) or SYNC_CONFLICT.search(name) or any(fnmatch(name.lower(), p.lower()) for p in install_only):
                continue
            path = Path(current) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            found[path.relative_to(folder).as_posix()] = (stat.st_size, stat.st_mtime)
    return found


def category(relative):
    parts = [p.lower() for p in relative.split("/")]
    if parts[-1].endswith(".dll"):
        return "code"
    for segment, kind in (("defs", "defs"), ("patches", "patches"), ("textures", "textures"), ("languages", "text"),
                          ("sounds", "sounds"), ("about", "about")):
        if segment in parts[:-1]:
            return kind
    return "other"


def same_bytes(a, b):
    try:
        with open(a, "rb") as one, open(b, "rb") as two:
            while True:
                x, y = one.read(CHUNK), two.read(CHUNK)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def compare_files(installed, repository, install_only=()):
    """What installing the repository's copy over the installed one would add, change and remove, by kind."""
    have, would = files_of(installed, install_only), files_of(repository, install_only)
    changes = []
    for rel in sorted(set(have) | set(would)):
        if rel not in have:
            changes.append((rel, "added"))
        elif rel not in would:
            changes.append((rel, "removed"))
        elif have[rel] != would[rel] and (have[rel][0] != would[rel][0]
                                           or not same_bytes(Path(installed) / rel, Path(repository) / rel)):
            changes.append((rel, "changed"))
    counts = {}
    for rel, _ in changes:
        kind = category(rel)
        counts[kind] = counts.get(kind, 0) + 1
    return {"total": len(changes), "counts": {k: counts[k] for k in CATEGORIES if k in counts},
            "paths": [{"path": rel, "change": change, "category": category(rel)} for rel, change in changes[:MAX_PATHS]]}


# ---------------------------------------------------------------- builds

def _property(text, name):
    found = re.search(rf"<{re.escape(name)}>\s*([^<]+?)\s*</{re.escape(name)}>", text)
    return found.group(1) if found else None


def _newest(paths):
    newest, which = 0.0, None
    for path in paths:
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            continue
        if mtime > newest:
            newest, which = mtime, path
    return newest, which


def project_inputs(csproj, text):
    """The files a project compiles from: its own folder (without obj and bin) and its Compile Include paths outside it."""
    folder = Path(csproj).parent
    found = []
    for current, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        found += [Path(current) / n for n in filenames]
    for include in re.findall(r'<Compile\s+Include="([^"]+)"', text):
        if ".." in include:
            pattern = str(folder / include.replace("\\", "/"))
            found += [Path(p) for p in glob.glob(pattern, recursive=True)]
    return found


def build_states(root, config):
    """{mod: [{project, needsBuild, built, newest, newestFile}]} for every project the config's build section names."""
    build = config.get("build") or {}
    pattern, prop = build.get("projects"), build.get("modProperty")
    if not pattern or not prop:
        return {}
    root = Path(root)
    shared = [root / p for p in build.get("shared", [])]
    states = {}
    for csproj in sorted(root.glob(pattern)):
        try:
            text = csproj.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        mod = _property(text, prop)
        if not mod:
            continue
        assembly = _property(text, "AssemblyName") or csproj.stem
        dlls = [p for p in (root / config["mods"] / mod).rglob(f"{assembly}.dll") if p.parent.name.lower() == "assemblies"]
        built, _ = _newest(dlls)
        newest, which = _newest(project_inputs(csproj, text) + shared)
        states.setdefault(mod, []).append({
            "project": csproj.stem, "assembly": assembly, "inputs": input_paths(root, csproj, text, shared),
            "needsBuild": not dlls or newest > built + BUILD_SLACK_SECONDS,
            "built": built or None, "newest": newest or None,
            "newestFile": Path(which).relative_to(root).as_posix() if which and Path(which).is_relative_to(root) else None})
    return states


def input_paths(root, csproj, text, shared):
    """The folders and files a project builds from, as paths relative to the repository, for asking git what changed in them."""
    root = Path(root)
    folder = Path(csproj).parent
    found = [folder]
    for include in re.findall(r'<Compile\s+Include="([^"]+)"', text):
        if ".." in include:
            found.append(Path(os.path.normpath(folder / Path(include.replace("\\", "/")).parent)))
    found += [Path(p) for p in shared]
    relative = []
    for path in found:
        try:
            relative.append(path.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            continue
    return sorted(set(relative))


MAX_CHANGED_SOURCES = 5


def changed_sources(root, commit, paths):
    """The files among paths that changed since commit, committed or not, and new ones git has not been told of, sorted; [] when
    none did. None when git cannot say (no commit, an unknown one), so a doubt never hides a change."""
    if not commit or not paths:
        return None
    diff = _git(root, "diff", "--name-only", commit, "--", *paths)
    if diff is None:
        return None
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", *paths) or ""
    return sorted({line.strip() for line in (diff + "\n" + untracked).splitlines() if line.strip()})


def sources_changed(root, commit, paths):
    """Whether any of the paths changed since commit (see changed_sources); True when git cannot say."""
    found = changed_sources(root, commit, paths)
    return found is None or bool(found)


def mark_rebuilt(files, builds, root, commit):
    """Marks each changed assembly whose project's own sources are unchanged since commit as only rebuilt: it differs because it was
    built against newer code it uses (another mod's assembly, a new version of it), not because its own code changed. Returns how
    many it marked. Such a file still counts as a change: an assembly built against older code it uses can fail against the new."""
    by_assembly = {f"{b['assembly']}.dll".lower(): b for b in builds}
    marked = 0
    for change in files["paths"]:
        build = by_assembly.get(change["path"].rsplit("/", 1)[-1].lower())
        if change["change"] != "changed" or not build:
            continue
        found = changed_sources(root, commit, build["inputs"])
        if found == []:
            change["rebuilt"] = True
            marked += 1
        elif found:
            # Which of its sources changed, so a reader sees why an assembly differs when no changelog entry says.
            change["sources"] = found[:MAX_CHANGED_SOURCES]
            change["sourcesInAll"] = len(found)
    files["rebuilt"] = marked
    return marked


# ---------------------------------------------------------------- the installed commit

def _git(root, *arguments):
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *arguments]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def version_commit(root, version_file, marker):
    """The commit that first wrote marker (a version, as the mod's version file holds it) into version_file; None if none did."""
    out = _git(root, "log", "-S", marker, "--format=%H", "--", version_file)
    lines = [line for line in (out or "").splitlines() if line.strip()]
    return lines[-1] if lines else None


# ---------------------------------------------------------------- settings changes

def settings_changes(root, config, commit, run=subprocess.run):
    """[{mod, key, label, what, before, after}] the repository's command reports since commit; (None, why) when it cannot."""
    template = config.get("settingsChanges")
    if not template or not commit:
        return None, None
    command = [sys.executable if part == "{python}" else part.replace("{commit}", commit) for part in template]
    try:
        result = run(command, cwd=str(root), capture_output=True, text=True, check=False, timeout=300,
                     env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        found = json.loads(result.stdout or "null")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return None, f"the settings changes could not be read ({error})"
    if result.returncode != 0 or not isinstance(found, list):
        return None, (result.stderr or "the settings command failed").strip()[:300]
    return found, None


# ---------------------------------------------------------------- test rows

def look_out(root, name, installed, repository):
    """Rows of the repository's test list still waiting whose newest named version of this mod lies after the installed version and
    no later than the repository's: [{id, title, version}]. Empty without a test list or a way to name the mod in rows."""
    have, would = testpass.version_tuple(installed or ""), testpass.version_tuple(repository or "")
    if not have or not would or have >= would:
        return []
    try:
        config = testpass.load_config(root)
        rows = testpass.parse_rows((Path(root) / config["doc"]).read_text(encoding="utf-8"))
    except (testpass.TestPassError, OSError, KeyError):
        return []
    names = {k: v for k, v in (config.get("versionNames") or {}).items() if k == name}
    if not names:
        return []
    found = []
    for row in rows:
        if row.status not in WAITING:
            continue
        version = testpass.row_versions(row, names).get(name)
        if version and have < version <= would:
            found.append({"id": row.id, "title": row.title, "version": ".".join(str(n) for n in version)})
    return found
