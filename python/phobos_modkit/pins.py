"""pins: which version of this tool kit each repository pins, and what moving its pin to this kit would bring (1.38.0).

    pins status --root REPO [--root REPO ...]     each repository's pin of this kit, and the versions it lacks

A repository pins the kit as a git submodule (phobos-rimworld's external/phobos-modkit). The pin is the commit the repository's
HEAD records, not whatever its checkout holds; its version is read from that commit of this kit (python/phobos_modkit/__init__.py).
What a move would bring is this kit's own changelog, as it stands here, between the two versions: the same reading the Mods page
gives a mod (D'thorga Companion's cross-links S2). A submodule that is not this kit is left out.

Reads only: git is asked, never told.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from . import __version__
from .installs import UNRELEASED, parse_changelog, version_tuple
from .manifest import READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE = 0, 2
KIT_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = "python/phobos_modkit/__init__.py"
VERSION = re.compile(r'__version__\s*=\s*"([^"]+)"')
ENTRIES_SHOWN = 8


def _git(folder, *args):
    result = subprocess.run(["git", "-C", str(folder), "-c", "core.fsmonitor=false", *args], capture_output=True, check=False)
    return result.stdout.decode("utf-8", "replace").strip() if result.returncode == 0 else None


def submodules(root):
    """[(path, url)] of the repository's submodules, from its .gitmodules."""
    listed = _git(root, "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$") or ""
    found = {}
    for line in listed.splitlines():
        key, _, value = line.partition(" ")
        name, _, field = key[len("submodule."):].rpartition(".")
        found.setdefault(name, {})[field] = value
    return [(f["path"], f.get("url", "")) for f in found.values() if "path" in f]


def pinned_version(kit_root, commit):
    """This kit's version at a commit, or None when the commit is not one of this kit's."""
    text = _git(kit_root, "show", f"{commit}:{VERSION_FILE}")
    found = VERSION.search(text or "")
    return found.group(1) if found else None


def repository_kit(root, kit_root=KIT_ROOT):
    """The version of this kit a repository pins, or None when it pins none (1.137.0): read from its checkout of the kit first,
    since a kit older than the pin may not know the pinned commit, then from the commit its HEAD records."""
    root = Path(root).resolve()
    for path, _ in submodules(root):
        found = VERSION.search(_read(root / path / VERSION_FILE))
        if found and (root / path / "python" / "phobos_modkit" / "pins.py").is_file():
            return found.group(1)
        commit = _git(root, "rev-parse", f"HEAD:{path}")
        version = pinned_version(kit_root, commit) if commit else None
        if version:
            return version
    return None


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def versions_between(changelog, older, newer):
    """[{version, heading, entries: [lead]}] of the changelog's versions above older, up to and including newer, newest first."""
    low, high = version_tuple(older), version_tuple(newer)
    found = {}
    for entry in changelog.entries:
        if entry.version == UNRELEASED:
            continue
        number = version_tuple(entry.version)
        if number and low < number <= high:
            found.setdefault(entry.version, []).append(entry.lead)
    return [{"version": v, "heading": changelog.headings.get(v, ""), "entries": leads}
            for v, leads in sorted(found.items(), key=lambda item: version_tuple(item[0]), reverse=True)]


def status(roots, kit_root=KIT_ROOT, kit_version=__version__):
    """Each repository's pins of this kit: {repository, path, commit, version, behind, ahead, versions}."""
    changelog = parse_changelog((Path(kit_root) / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace"))
    found = []
    for root in roots:
        root = Path(root).resolve()
        for path, url in submodules(root):
            commit = _git(root, "rev-parse", f"HEAD:{path}")
            if not commit:
                continue
            version = pinned_version(kit_root, commit)
            if version is None:
                continue
            newer = versions_between(changelog, version, kit_version)
            found.append({"repository": root.name, "path": path, "url": url, "commit": commit[:12], "version": version,
                          "kit": kit_version, "behind": len(newer),
                          "ahead": version_tuple(version) > version_tuple(kit_version), "versions": newer})
    return found


def _parser():
    p = argparse.ArgumentParser(prog="pins", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("status", help="each repository's pin of this kit, and the versions it lacks")
    s.add_argument("--root", action="append", default=[], help="a repository (repeatable; default: the current folder)")
    s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    pins = status(args.root or ["."])
    report = Report(f"Tool kit pins: this kit is {__version__}")
    report.section("Pins", Table(["Repository", "Pinned", "Behind", "Commit"],
                                 [[p["repository"], p["version"], "ahead of this kit" if p["ahead"] else f"{p['behind']} versions",
                                   p["commit"]] for p in pins]))
    for pin in pins:
        if pin["versions"]:
            report.section(f"What {pin['repository']} would gain", Bullets(
                [f"{v['version']}: " + "; ".join(v["entries"][:ENTRIES_SHOWN]) for v in pin["versions"]]))
    out.write((envelope_text("pins", report, redact, {"kit": __version__, "pins": pins}) if args.json
               else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"status": {"note": "each repository's pin of this kit; needs the repositories"}}}
