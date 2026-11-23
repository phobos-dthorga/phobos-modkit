"""doc-tables: tables in a repository's own docs, filled from its own files, so they cannot drift from them (1.107.0; 1.108.0).

    doc-tables --root REPO            check: name each table that is missing or out of date (fails when one is)
    doc-tables --root REPO --write    write every table that is missing or out of date

The repository's config/doc-tables.json lists each table: the doc it sits in, its kind and its options. A table sits between
`<!-- generated: table NAME -->` and `<!-- end generated -->` (NAME is the entry's "name", else its kind); everything else in
the doc is its own and never touched, as with command-docs. Kinds:

  dotnet-projects    every .csproj under the folders named: what it builds into, its references, Harmony, its test projects
  harmony-patches    per project, the methods its C# source patches with Harmony attributes, read from the text
  mod-requirements   per mod folder, through the game's adapter: needs, load order, game versions, optional tie-ins
  mod-settings       one mod's settings, through the game's adapter: label, what it does, default, page and section

It reads only the repository's files; it writes only the docs' generated blocks, and only with --write.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from importlib import import_module
import json
from pathlib import Path, PurePosixPath
import sys

from . import dotnet_projects as projects_module
from . import generated_blocks as blocks
from .code import harmony
from .manifest import READS, WRITES
from .markdown import table
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
CONFIG = "config/doc-tables.json"
CONFIG_FORMAT = 1
CELL = 10_000  # a doc's cells are never cut
DEFAULT_RUN = "python -m phobos_modkit doc-tables --write"
KINDS = ("dotnet-projects", "harmony-patches", "mod-requirements", "mod-settings")
HEADINGS = {"dotnet-projects": "## Projects", "harmony-patches": "## Harmony patches",
            "mod-requirements": "## What each mod needs", "mod-settings": "## Settings"}
RULES = {"any": " or ", "all": " and "}


def key_of(entry):
    return f"table {entry.get('name') or entry['kind']}"


def _note(config, source):
    return (f"Generated from {source} by `{config.get('run') or DEFAULT_RUN}`: change those files, not this table.")


def _code(text):
    return f"`{text}`"


def _listed(items, empty="none"):
    return ", ".join(items) if items else empty


# ---- dotnet-projects ----

def projects_table(root, options, config):
    """(lines, data) of the projects table."""
    folders = options.get("folders") or ["."]
    test_folders = options.get("testFolders") or []
    tests = projects_module.read_projects(root, test_folders) if test_folders else []
    test_paths = {t.path for t in tests}
    found = [p for p in projects_module.read_projects(root, folders) if p.path not in test_paths]
    names = {p.path: p.name for p in found + tests}
    output = options.get("output")
    headers = ["Project", options.get("outputLabel") or "Builds into", "Projects it references", "Other assemblies", "Harmony",
               "Test projects"]
    if not output:
        headers.pop(1)
    rows, data = [], []
    for project in found:
        refs = [names.get(r, PurePosixPath(r).stem) for r in project.project_refs]
        testers = projects_module.tests_of(project, tests)
        into = projects_module.fill(output, project.properties) if output else None
        row = [_code(project.name), _code(into) if into else "not set",
               _listed([_code(r) for r in refs], "none"), _listed([_code(r) for r in project.references], "none"),
               "yes" if project.harmony else "no", _listed([_code(t) for t in testers], "none")]
        if not output:
            row.pop(1)
        rows.append(row)
        data.append({"project": project.name, "path": project.path, "buildsInto": into, "projectReferences": refs,
                     "references": project.references, "harmony": project.harmony, "tests": testers,
                     "error": project.error or None})
    lines = [_note(config, "the project files"), ""]
    lines += table(headers, rows, CELL) if rows else ["No project files were found in " + ", ".join(folders) + "."]
    harmony_count = sum(1 for d in data if d["harmony"])
    lines += ["", f"{len(rows)} project{'' if len(rows) == 1 else 's'} ({harmony_count} using Harmony) and {len(tests)} test "
              f"project{'' if len(tests) == 1 else 's'}. Read from each project file as written: MSBuild is not run, so a value "
              "set only in `Directory.Build.props` or `Directory.Build.targets` is not shown. Harmony: its own C# files have "
              "`using HarmonyLib` or a `[HarmonyPatch]`. Test projects: those that reference the project or compile its files."]
    errors = [f"`{d['path']}`: {d['error']}" for d in data if d["error"]]
    if errors:
        lines += ["", "Could not read: " + "; ".join(errors) + "."]
    return lines, {"projects": data, "tests": [t.name for t in tests]}


# ---- harmony-patches ----

def _patch_rows(found):
    """Rows of (target, kinds, files) for one project: a named target once, with every file that patches it."""
    grouped = {}
    for patch in found.patches:
        by_name = patch.target.startswith("by name in ")
        key = (patch.target, patch.file) if by_name else (patch.target, None)
        entry = grouped.setdefault(key, {"kinds": set(), "files": set(), "classes": set()})
        entry["kinds"].update(patch.kinds)
        entry["files"].add(patch.file)
        entry["classes"].add((patch.file, patch.line))
    rows = []
    for (target, _), entry in sorted(grouped.items(), key=lambda kv: (kv[0][0].startswith("by name in "), kv[0][0].lower(),
                                                                       kv[0][1] or "")):
        shown = target if not target.startswith("by name in ") or len(entry["classes"]) == 1 \
            else f"{target} ({len(entry['classes'])} classes)"
        kinds = [k for k in harmony.KINDS if k in entry["kinds"]]
        rows.append((shown, kinds, sorted(entry["files"])))
    return rows


def patches_table(root, options, config):
    root = Path(root)
    folders = options.get("folders") or ["."]
    found_projects = projects_module.read_projects(root, folders)
    summary, sections, unread, data = [], [], [], []
    for project in found_projects:
        folder = root / project.folder
        found = harmony.read_folder(folder)
        rows = _patch_rows(found)
        named = sum(1 for r in rows if not r[0].startswith("by name in "))
        by_name = sum(1 for p in found.patches if p.target.startswith("by name in "))
        unread += [(f"{project.folder}/{u.file}", u.line, u.text) for u in found.unread]
        data.append({"project": project.name, "patched": named, "byName": by_name, "manual": len(found.manual),
                     "unread": len(found.unread),
                     "patches": [{"target": t, "kinds": k, "files": f} for t, k, f in rows]})
        if not rows and not found.manual and not found.unread:
            continue
        summary.append([_code(project.name), named, by_name, len(found.manual), len(found.unread)])
        if rows:
            sections += ["", f"<details><summary><code>{project.name}</code>: {named} patched method"
                         f"{'' if named == 1 else 's'}{f', {by_name} by name' if by_name else ''}</summary>", ""]
            sections += table(["Patched method", "Kinds", f"Where (in `{project.folder}/`)"],
                              [[_code(t) if not t.startswith("by name in ") else t, ", ".join(k) or "none found",
                                ", ".join(_code(f) for f in fs)] for t, k, fs in rows], CELL)
            sections += ["", "</details>"]
    lines = [_note(config, "the projects' C# source"), ""]
    if summary:
        lines += table(["Project", "Patched methods", "Found by name at run time", "Manual `.Patch(` calls", "Not read"],
                       summary, CELL)
    else:
        lines += ["No project patches anything with Harmony."]
    total = sum(d["patched"] for d in data)
    lines += ["", f"{total} patched method{'' if total == 1 else 's'} named in attributes, "
              f"{sum(d['byName'] for d in data)} patch classes that find their target by name (`TargetMethod`), and "
              f"{sum(d['manual'] for d in data)} manual `.Patch(` calls, whose targets are found at run time and are not "
              "listed. Read from the source text, never from a build: a method a patch names but the game or the mod no longer "
              "has still shows here."]
    if unread:
        lines += ["", "Not read (an attribute form the reader does not know; check these by hand):", ""]
        lines += [f"- `{file}:{line}`: `{text}`" for file, line, text in sorted(unread)]
    else:
        lines += ["", "Every HarmonyPatch attribute was read."]
    lines += sections
    return lines, {"projects": data, "unread": [{"file": f, "line": n, "text": t} for f, n, t in sorted(unread)]}


# ---- mod-requirements ----

def requirement_reader(game):
    """The game adapter's mod_requirements(folder), or None when no adapter reads them."""
    from .games import mod_list_game
    row = mod_list_game(game) if game else None
    if row is None:
        return None
    return getattr(import_module(row[3], "phobos_modkit.games"), "mod_requirements", None)


def _name(package_id, names):
    return names.get(package_id.lower()) or _code(package_id)


def _condition(conditions, names):
    parts = []
    for rule, ids in conditions:
        shown = [_name(i, names) for i in ids]
        parts.append(("not " + " or ".join(shown)) if rule == "none" else RULES.get(rule, ", ").join(shown))
    return "; ".join(parts)


def requirements_table(root, options, config):
    root = Path(root)
    game = options.get("game")
    folders = options.get("folders") or ["mods"]
    lines = [_note(config, "each mod's own files"), ""]
    reader = requirement_reader(game)
    if reader is None:
        lines += [f"No game adapter reads {game or 'this game'}'s mod requirements yet, so this table cannot be made. A next game "
                  "needs a `mod_requirements(folder)` in its adapter (phobos-modkit's `games/<game>/mod_list.py`) that returns "
                  "the mod and its optional tie-ins from the mod's own files (`docs/doc-tables.md`)."]
        return lines, {"game": game, "adapter": False, "mods": []}
    read = []
    for folder in folders:
        base = root / folder
        for sub in sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name.lower()) if base.is_dir() else []:
            found = reader(sub)
            if found is not None:
                read.append((sub, *found))
    names = {k.lower(): v for k, v in (options.get("names") or {}).items()}
    for _, mod, _ in read:
        names.setdefault(mod.id.lower(), mod.name)
        for need in mod.needs:
            if need.name:
                for i in need.ids:
                    names.setdefault(i.lower(), need.name)
    rows, data = [], []
    for folder, mod, tie_ins in read:
        needs = [need.name or _code(need.ids[0]) for need in mod.needs]
        after = [_name(i, names) for i in mod.load_after]
        before = [_name(i, names) for i in mod.load_before]
        optional = sorted({_condition(t.conditions, names) for t in tie_ins}, key=lambda s: s.replace("`", "").lower())
        rows.append([mod.name, _code(mod.id), _listed(needs), _listed(after), _listed(before), _listed(mod.versions, "not said"),
                     _listed(optional)])
        data.append({"folder": folder.relative_to(root).as_posix(), "name": mod.name, "packageId": mod.id,
                     "needs": [{"ids": list(n.ids), "name": n.name} for n in mod.needs], "loadAfter": mod.load_after,
                     "loadBefore": mod.load_before, "versions": mod.versions,
                     "tieIns": [{"folders": list(t.folders), "conditions": [[r, list(i)] for r, i in t.conditions]}
                                for t in tie_ins]})
    headers = ["Mod", "Package ID", "Needs", "Loads after", "Loads before", "Game versions", "Works with (optional)"]
    lines += table(headers, rows, CELL) if rows else [f"No mod folders were found in {', '.join(folders)}."]
    lines += ["", "**Needs** must be switched on too. **Loads after** and **Loads before** only set the order when those mods are "
              "on; they are not needed. **Works with** lists the mods that switch on extra content of this mod when they are on "
              "(\"or\": any one of them; \"and\": all of them)."]
    return lines, {"game": game, "adapter": True, "mods": data}


# ---- mod-settings ----

def settings_reader(game):
    """The game adapter's mod_settings(root, options) (games/<game>/mod_settings.py), or None when no adapter reads them."""
    from .games import mod_list_game
    row = mod_list_game(game) if game else None
    if row is None:
        return None
    name = f".{row[3].split('.')[1]}.mod_settings"
    try:
        module = import_module(name, "phobos_modkit.games")
    except ModuleNotFoundError as missing:
        if missing.name != f"phobos_modkit.games{name}":
            raise
        return None
    return getattr(module, "mod_settings", None)


def settings_table(root, options, config):
    """One mod's settings, as its game's adapter reads them from the mod's own files."""
    game = options.get("game")
    lines = [_note(config, "the mod's source code and language files"), ""]
    reader = settings_reader(game)
    if reader is None:
        lines += [f"No game adapter reads {game or 'this game'}'s mod settings yet, so this table cannot be made. A next game needs "
                  "a `mod_settings(root, options)` in its adapter (phobos-modkit's `games/<game>/mod_settings.py`) that returns "
                  "each setting's label, description, default, page and section from the mod's own files (`docs/doc-tables.md`)."]
        return lines, {"game": game, "adapter": False, "settings": [], "unresolved": []}
    read = reader(Path(root), options)
    shown = [s for s in read.settings if s.shown]
    hidden = [s for s in read.settings if not s.shown]
    pages = {s.page for s in shown}
    with_page = len(pages) > 1
    with_section = any(s.section for s in shown)
    headers = ["Setting", "What it does", "Default"] + (["Page"] if with_page else []) + (["Section"] if with_section else [])
    rows = []
    for s in shown:
        default = f"{s.default} ({s.note})" if s.note else s.default
        row = [s.label or _code(s.label_key or s.key), s.description or "", default]
        row += [s.page] if with_page else []
        row += [s.section] if with_section else []
        rows.append(row)
    if rows:
        lines += table(headers, rows, CELL)
    else:
        lines += ["No setting was found drawn in the mod's settings window."]
    count = len(rows)
    lines += ["", f"{count} setting{'' if count == 1 else 's'}, in the order the settings window draws them. **Default** is what the "
              "game uses until the setting is changed. A setting the window shows only in some games (another mod active, another "
              "setting on) is listed all the same."]
    if hidden:
        lines += ["", "Saved, but not found drawn in the window by the reader (kept by the window itself, or drawn by code it cannot "
                  "follow): " + ", ".join(_code(s.key) for s in hidden) + "."]
    return lines, {"game": game, "adapter": True, "settings": [asdict(s) for s in read.settings], "unresolved": read.unresolved}


BUILDERS = {"dotnet-projects": projects_table, "harmony-patches": patches_table, "mod-requirements": requirements_table,
            "mod-settings": settings_table}


# ---- Planning and writing ----

@dataclass
class DocFile:
    path: str
    tables: list = field(default_factory=list)    # config entries
    before: str = None
    after: str = None
    crlf: bool = False
    missing: list = field(default_factory=list)   # table keys whose block was not there
    stale: list = field(default_factory=list)     # whose block was there but out of date

    @property
    def state(self):
        if self.before is None:
            return "no such file"
        if self.missing:
            return "block missing"
        return "out of date" if self.stale else "current"


def load_config(root):
    config = json.loads((Path(root) / CONFIG).read_text(encoding="utf-8"))
    if config.get("schemaVersion") != CONFIG_FORMAT:
        raise ValueError(f"{CONFIG}: schemaVersion {config.get('schemaVersion')} is not {CONFIG_FORMAT}")
    return config


def plan(root, config=None):
    """(docs, problems, data): each doc with its text now and as it should be; what cannot be made; what each table found."""
    root = Path(root)
    config = load_config(root) if config is None else config
    problems, docs, data = [], {}, []
    seen = set()
    for entry in config.get("tables", []):
        kind, doc = entry.get("kind"), entry.get("doc")
        if kind not in BUILDERS:
            problems.append(f"{CONFIG}: unknown kind `{kind}` (known: {', '.join(KINDS)})")
            continue
        if not doc:
            problems.append(f"{CONFIG}: a `{kind}` table names no doc")
            continue
        if (doc, key_of(entry)) in seen:
            problems.append(f"{CONFIG}: {doc} has two tables called `{key_of(entry)}`; give one a \"name\"")
            continue
        seen.add((doc, key_of(entry)))
        docs.setdefault(doc, DocFile(doc)).tables.append(entry)
    for doc in docs.values():
        path = root / doc.path
        if not path.is_file():
            problems.append(f"{doc.path} does not exist")
            continue
        doc.before, doc.crlf = blocks.read(path)
        text, added = doc.before, []
        for entry in doc.tables:
            body, found = BUILDERS[entry["kind"]](root, entry.get("options") or {}, config)
            data.append({"doc": doc.path, "table": key_of(entry)[len("table "):], "kind": entry["kind"], "found": found})
            text, there = blocks.replace_block(text, key_of(entry), body)
            if not there:
                doc.missing.append(key_of(entry))
                added.append((key_of(entry), body, entry["kind"]))
        for key, body, kind in added:
            text = blocks.append_section(text, HEADINGS[kind], [(key, None, body)])
        doc.after = text
        doc.stale = [key_of(e) for e in doc.tables if key_of(e) not in doc.missing] if text != doc.before else []
    return list(docs.values()), problems, data


# ---- The command ----

def _parser():
    p = argparse.ArgumentParser(prog="doc-tables", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--root", help="the repository (default: the current folder)")
    p.add_argument("--write", action="store_true", help="write the tables that are missing or out of date; without it, only check")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def report_of(docs, problems, data, written, wrote):
    out_of_date = [d for d in docs if d.before is not None and d.after != d.before]
    count = sum(len(d.tables) for d in docs)
    if wrote:
        title = f"Doc tables: wrote {len(written)} file{'' if len(written) == 1 else 's'}" if written else "Doc tables: all current"
    else:
        title = ("Doc tables: all current" if not out_of_date
                 else f"Doc tables: {len(out_of_date)} file{'' if len(out_of_date) == 1 else 's'} out of date")
    report = Report(title)
    report.lines.append(f"{count} table{'' if count == 1 else 's'} in {len(docs)} doc{'' if len(docs) == 1 else 's'}.")
    if out_of_date and not wrote:
        report.lines.append("Run doc-tables with `--write` to bring them up to date.")
    rows = [[d.path, ", ".join(key_of(e)[len("table "):] for e in d.tables),
             ("written" if d.path in written else d.state) if wrote else d.state] for d in docs]
    if rows:
        report.section("Docs", Table(["Doc", "Tables", "State"], rows))
    unread = [f"{u['file']}:{u['line']}: {u['text']}" for t in data if t["kind"] == "harmony-patches" for u in t["found"]["unread"]]
    if unread:
        report.section("Harmony attributes not read", Bullets(unread))
    no_adapter = [f"{t['doc']}: no adapter reads {t['found']['game']}'s mod "
                  f"{'requirements' if t['kind'] == 'mod-requirements' else 'settings'} yet" for t in data
                  if t["kind"] in ("mod-requirements", "mod-settings") and not t["found"]["adapter"]]
    if no_adapter:
        report.section("Tables that say they cannot be made", Bullets(no_adapter))
    partly = [f"{t['doc']}: {u}" for t in data if t["kind"] == "mod-settings" for u in t["found"]["unresolved"]]
    if partly:
        report.section("Settings not read in full", Bullets(partly))
    if problems:
        report.section("Cannot generate", Bullets(problems))
    failed = bool(problems) or (bool(out_of_date) and not wrote)
    return report, {"written": written, "problems": problems, "tables": data,
                    "docs": [{"path": d.path, "state": d.state, "missing": d.missing, "stale": d.stale} for d in docs]}, failed


def main(argv=None, out=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    root = Path(args.root).resolve() if args.root else Path.cwd()
    try:
        docs, problems, data = plan(root)
    except (OSError, ValueError) as failed:
        out.write((envelope_text("doc-tables", Report("Doc tables: cannot read the config"), redact,
                                 {"problems": [str(failed)]}) if args.json else f"Doc tables: cannot read the config: {failed}")
                  + "\n")
        return EXIT_FAILED
    written = blocks.write_changed(root, docs) if args.write else []
    report, extra, failed = report_of(docs, problems, data, written, args.write)
    out.write((envelope_text("doc-tables", report, redact, extra) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_FAILED if failed else EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {None: {"effect": WRITES, "when": "--write"}},
            "question": "Do the tables in my docs still match the repository's projects, patches, mods and settings?",
            "note": "fails when a table is missing or out of date; with --write, writes only the generated tables in the docs "
                    "config/doc-tables.json names"}


if __name__ == "__main__":
    sys.exit(main())
