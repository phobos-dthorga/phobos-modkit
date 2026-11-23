"""A repository's .NET projects as their project files describe them (1.107.0, for doc-tables). Game-free.

Reads each `*.csproj` as XML: its properties, `ProjectReference`, `Reference` and `Compile Include` items. MSBuild is never
run, so a property set in `Directory.Build.props` or by a condition is not seen; a value is only what the file itself says.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import os
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

from .code.harmony import uses_harmony

SKIP_FOLDERS = frozenset({"bin", "obj", ".git", "node_modules"})
_PROPERTY = re.compile(r"\{(\w+)\}")


@dataclass
class Project:
    name: str                    # the file's name without .csproj
    path: str                    # relative to the repository, forward slashes
    properties: dict = field(default_factory=dict)        # the first value the file gives each property
    project_refs: list = field(default_factory=list)      # paths of referenced project files, relative to the repository
    references: list = field(default_factory=list)        # Reference Include names, without version or culture
    compiles: list = field(default_factory=list)          # Compile Include patterns, relative to the repository
    harmony: bool = False        # its own .cs files use Harmony
    error: str = ""              # why the file could not be read

    @property
    def folder(self):
        return str(PurePosixPath(self.path).parent)


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _normal(path):
    """A path with ".." resolved, forward slashes, without touching the disk."""
    return os.path.normpath(path).replace("\\", "/")


def read_project(file, root):
    """The Project in one .csproj file; root is the repository, which every path is made relative to."""
    file, root = Path(file), Path(root)
    relative = file.relative_to(root).as_posix()
    project = Project(file.stem, relative)
    here = PurePosixPath(relative).parent
    try:
        tree = ET.parse(file).getroot()
    except (OSError, ET.ParseError) as failed:
        project.error = str(failed)
        return project
    for element in tree.iter():
        tag, include = _local(element.tag), element.get("Include")
        if not include:
            continue
        if tag == "ProjectReference":
            project.project_refs.append(_normal(str(here / include.replace("\\", "/"))))
        elif tag == "Reference":
            project.references.append(include.split(",")[0].strip())
        elif tag == "Compile":
            project.compiles.append(_normal(str(here / include.replace("\\", "/"))))
    for group in tree:
        if _local(group.tag) != "PropertyGroup":
            continue
        for prop in group:
            name = _local(prop.tag)
            if name and name not in project.properties:
                project.properties[name] = (prop.text or "").strip()
    project.harmony = _folder_uses_harmony(file.parent)
    return project


def _folder_uses_harmony(folder):
    for current, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_FOLDERS)
        for name in sorted(files):
            if name.endswith(".cs"):
                try:
                    if uses_harmony(Path(current, name).read_text(encoding="utf-8-sig", errors="replace")):
                        return True
                except OSError:
                    continue
    return False


def find_projects(root, folders):
    """Every .csproj under the folders named (relative to root), sorted by path."""
    root = Path(root)
    found = []
    for folder in folders:
        base = root / folder
        if not base.is_dir():
            continue
        for current, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_FOLDERS)
            found += [Path(current, n) for n in files if n.endswith(".csproj")]
    return sorted({p.resolve() for p in found}, key=lambda p: p.relative_to(root.resolve()).as_posix().lower())


def read_projects(root, folders):
    """Every Project under the folders named, by name (then path)."""
    root = Path(root).resolve()
    return sorted((read_project(p, root) for p in find_projects(root, folders)), key=lambda p: (p.name.lower(), p.path))


def fill(template, properties):
    """template with each {Property} replaced by the project's value ("" when it has none); None when the first is missing."""
    names = _PROPERTY.findall(template)
    if names and not properties.get(names[0]):
        return None
    return _PROPERTY.sub(lambda m: properties.get(m.group(1), ""), template)


def tests_of(project, tests):
    """The test projects that reference project, or compile any of its files."""
    found = []
    folder = project.folder.rstrip("/") + "/"
    for test in tests:
        if project.path in test.project_refs:
            found.append(test.name)
        elif any(c.startswith(folder) or fnmatchcase(project.path, c) for c in test.compiles):
            found.append(test.name)
    return found
