"""Release notes: each changelog entry as a Steam change note, generated beside the Workshop page and checked.

A mod's page must name its title and current version, state its publication status and stay under the page budget;
its current version needs a dated entry. Generated files are written only with write=True, every input is compared
again before and after writing, and a file no entry explains is reported, never deleted.
"""
from __future__ import annotations

import subprocess

from ...files import atomic_write, inside, sha256
from ...release.changelog import ChangelogError, parse
from .. import bbcode
from .project import PublishError

STATUS_LINE = "[b]Publication status:[/b] "


def note_text(title, release):
    """One version's change note."""
    status = "Draft - not published" if release.status == "Draft" else "Released"
    text = f"[h1]{title} {release.version}[/h1]\n[b]{status} | {release.date}[/b]\n\n{bbcode.render(release.body)}\n"
    bbcode.validate(text)
    return text


def check_page(project, mod, title, version, text):
    rules = project.layout["pageRules"]
    bbcode.validate(text)
    if '"' in text or "\\" in text:
        raise PublishError(f"{mod}: the page must not contain ASCII double quotes or backslashes; use typographic quotes")
    size, budget = len(text.encode("utf-8")), project.layout["pageMaxBytes"]
    if size > budget:
        raise PublishError(f"{mod}: the page is {size} UTF-8 bytes; Steam takes under 8,000 and this project's budget is {budget}")
    if rules.get("version") and text.splitlines().count(f"[b]Version:[/b] {version}") != 1:
        raise PublishError(f"{mod}: the page needs one line reading [b]Version:[/b] {version}")
    if rules.get("title") and f"[h1]{title}[/h1]" not in text:
        raise PublishError(f"{mod}: the page needs the heading [h1]{title}[/h1]")
    if rules.get("status") and not any(line.startswith(STATUS_LINE) and len(line) > len(STATUS_LINE)
                                       for line in text.splitlines()):
        raise PublishError(f"{mod}: the page needs a line starting {STATUS_LINE}")


def read(path):
    return path.read_bytes()


def checked_releases(text, where):
    """The changelog's releases after checking that every entry renders; errors name the file and version."""
    try:
        releases = parse(text)
    except ChangelogError as error:
        raise PublishError(f"{where}: {error}") from None
    for release in releases.values():
        try:
            bbcode.render(release.body)
        except bbcode.BBCodeError as error:
            raise PublishError(f"{where}: {release.version}: {error}") from None
    return releases


def plan(project, mods=None, version=None):
    """(inputs, outputs): {path: bytes read} and {path: (bytes now or None, bytes generated)}."""
    names = project.select(mods, default=sorted(project.mods))
    if version and len(names) != 1:
        raise PublishError("--version needs exactly one mod")
    inputs, outputs = {}, {}
    for name in names:
        info = project.info(name)
        changelog, page = project.path("changelog", name), project.path("page", name)
        for path in (changelog, page):
            if not path.is_file():
                raise PublishError(f"{name}: missing {project.rel(path)}")
            inputs[path] = read(path)
        releases = checked_releases(inputs[changelog].decode("utf-8-sig"), f"{name}: {project.rel(changelog)}")
        if info.version not in releases:
            raise PublishError(f"{name}: current version {info.version} needs a dated Draft or Released changelog entry")
        check_page(project, name, info.title, info.version, inputs[page].decode("utf-8-sig"))
        if version and version not in releases:
            raise PublishError(f"{name}: no changelog entry for {version}")
        folder = project.path("releases", name)
        for release_version in [version] if version else list(releases):
            path = inside(project.root, folder / f"{release_version}.bbcode")
            before = path.read_bytes() if path.exists() else None
            outputs[path] = (before, note_text(info.title, releases[release_version]).encode("utf-8"))
        if not version and folder.is_dir():
            extras = sorted({p.name for p in folder.glob("*.bbcode")} - {v + ".bbcode" for v in releases})
            if extras:
                raise PublishError(f"{name}: release files with no changelog entry: {', '.join(extras)}")
    return inputs, outputs


def changed_records(project, paths):
    """Mods whose content changed without both a changelog and a page edit."""
    changed, problems = set(paths), []
    for mod in sorted(project.mods):
        changelog = project.rel(project.path("changelog", mod))
        page = project.rel(project.path("page", mod))
        scopes = [s.format(mod=mod) for s in project.layout["scope"]]
        touched = [p for p in changed if p.startswith(tuple(scopes)) and p not in (changelog, page)]
        missing = sorted({changelog, page} - changed)
        if touched and missing:
            problems.append(f"{mod}: changed content needs changelog and page edits in the same change; missing "
                            + ", ".join(missing))
    if problems:
        raise PublishError("; ".join(problems))


def check_scope(project, base):
    """Every file changed since the commit base (committed, uncommitted or new) against changed_records."""
    result = subprocess.run(["git", "rev-parse", "--verify", "--end-of-options", base + "^{commit}"],
                            cwd=project.root, capture_output=True, text=True)
    if result.returncode:
        raise PublishError("--base must name a Git commit")
    changed = project.git("diff", "--name-only", "-z", result.stdout.strip(), "--").decode().split("\0")
    untracked = project.git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    changed_records(project, [p for p in changed + untracked if p])


def run(project, mods=None, version=None, write=False, base=None):
    """(state, rows): state is valid, stale (generated files differ), written or nothing; rows describe files."""
    if base:
        check_scope(project, base)
    inputs, outputs = plan(project, mods, version)
    changes = {path: pair for path, pair in outputs.items() if pair[0] != pair[1]}
    if write and changes:
        for path, data in inputs.items():
            if read(inside(project.root, path)) != data:
                raise PublishError(f"Changed while checking: {project.rel(path)}")
        for path, (before, _) in outputs.items():
            if (path.read_bytes() if path.exists() else None) != before:
                raise PublishError(f"Changed while checking: {project.rel(path)}")
        for path, (_, data) in changes.items():
            atomic_write(inside(project.root, path), data)
        for path, data in inputs.items():
            if read(path) != data:
                raise PublishError(f"Source changed while writing: {project.rel(path)}; run again before publishing")
        if any(before != after for before, after in plan(project, mods, version)[1].values()):
            raise PublishError("Read-back failed; check again before publishing")
    state = "written" if write and changes else "stale" if changes else "valid"
    rows = [(project.rel(path), sha256(data)[:12], data.decode("utf-8")) for path, (_, data) in changes.items()]
    return state, len(outputs), rows
