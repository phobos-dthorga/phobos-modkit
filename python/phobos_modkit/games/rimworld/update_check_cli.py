"""rimworld-update-check: the game or mods updated; what does it mean for ours?

    rimworld-update-check --root REPO                     all four answers, for updates the archive kept in the last 7 days
    rimworld-update-check --root REPO --since 2026-11-19T10:00:00Z   for updates kept since a moment (a last session)
    rimworld-update-check --root REPO --only names,xml    some of them

Four answers from one run, for an agent session and for D'thorga Companion's "Since you last played":

  names      does every member our C# names by string still exist in the game and the active mods (rimworld-targets' check)
  temporary  for each patch of ours for another author's fault, did an update change the members that fault lives in? A change
             is a reason to read whether the fault is fixed and the patch can come out; no change means it stays
  updates    how big each update the archive kept in the window was, and the new types it brought: a mod we tie into that
             gains a feature may now do something ours also does
  xml        whether each of our XML patches still finds the Def it names, and, where its xpath is simple, the node inside it,
             in the Defs as the active mods write them

The repository says what is ours in config/update-check.json: {"ourPackageIds": ["Author.*"], "targets": {"sources": [...],
"assemblies": [...], "typeLookups": [...]}, "temporaryPatches": "config/temporary-patches.json"}. The temporary patches file
lists {"row", "patch", "mod", "file", "members": ["Type.Member"]} under "patches". Reads only.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from ... import cache as derived
from ...assembly_archive import Archive, ArchiveError, archive_root
from ...code import compare as code_compare, index as code_index
from ...manifest import RUNS
from ...progress import Progress
from ...report import Report, Table, envelope_text, home_redactor, keep, render_markdown
from . import defs, patched_defs, paths
from .patches import PatchesError
from .targets_cli import check as check_targets

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
PARTS = ("names", "temporary", "updates", "xml")
CONFIG = "config/update-check.json"
DEFAULT_DAYS = 7
NEW_TYPES_SHOWN = 12
# An xpath this check can follow: Defs/Type[defName="Name"], then plain steps, each with at most one [child="text"] test.
SIMPLE_XPATH = re.compile(r"""^/?Defs/(?P<type>[\w.*]+)\[defName\s*=\s*(?P<q>["'])(?P<name>[^"']+)(?P=q)\]"""
                          r"""(?P<rest>(?:/[\w.]+(?:\[[\w.]+\s*=\s*(["'])[^"']*\5\])?)*)/?$""")
# Operations whose xpath is a question, not a target: finding nothing is an answer, not a fault.
QUESTIONS = ("PatchOperationConditional", "PatchOperationTest", "PatchOperationFindMod")


class UpdateCheckError(RuntimeError):
    pass


# ---- the repository's configuration ----

def read_config(root, name=CONFIG):
    """The repository's update-check settings, or defaults when it has none."""
    path = Path(root) / name
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise UpdateCheckError(f"{path} is not valid JSON: {error}") from error


def read_temporary(root, config):
    """The temporary patches the repository lists, or [] with none."""
    name = config.get("temporaryPatches")
    if not name:
        return []
    path = Path(root) / name
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("patches", [])
    except (OSError, ValueError) as error:
        raise UpdateCheckError(f"Cannot read the temporary patches list {path}: {error}") from error
    for entry in entries:
        if not entry.get("file") or not entry.get("members"):
            raise UpdateCheckError(f"{path}: row {entry.get('row', '?')} needs a file and its members.")
    return entries


def window_start(since, days, now):
    """The archive's "YYYY-MM-DD HH:MM" (UTC) from which an update counts."""
    if since:
        try:
            moment = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as error:
            raise UpdateCheckError(f"--since {since!r} is not an ISO date and time.") from error
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = now - timedelta(days=days)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


# ---- the archive: what an update changed ----

def chains(archive):
    """{(owner, file): [versions, oldest first]}."""
    found = defaultdict(list)
    for version in archive.versions():
        found[(version.owner, version.file)].append(version)
    return found


def _when(version):
    return version.version or version.seen_at


def temporary_rows(entries, versions_by_file, since, compare):
    """[{row, patch, mod, file, status, members, detail}] for each listed patch. `compare(older, newer, patterns)` gives
    (changes, removed, added) for the members named: an added member counts as a change (a fix can be a new constructor)."""
    rows = []
    for entry in entries:
        file = entry["file"]
        chain = [v for (owner, name), chain in versions_by_file.items() if name.lower() == file.lower()
                 and (not entry.get("mod") or (chain[-1].owner_name or owner).lower() == entry["mod"].lower()) for v in chain]
        chain.sort(key=lambda v: (v.seen_at or "", v.id))
        row = {"row": entry.get("row"), "patch": entry.get("patch", ""), "mod": entry.get("mod", ""), "file": file,
               "members": list(entry["members"])}
        if len(chain) < 2:
            rows.append({**row, "status": "one-build", "detail": "only one build kept, so nothing to compare yet"})
            continue
        older, newer = chain[-2], chain[-1]
        if (newer.seen_at or "") < since:
            rows.append({**row, "status": "no-update", "detail": f"no update in the window; last kept {newer.seen_at} UTC"})
            continue
        patterns = [p for m in entry["members"] for p in (f"*.{m.lower()}", f"*.{m.lower()}(*")]
        changes, removed, added = compare(older, newer, patterns)
        names = sorted({_member(c.right.full) for c in changes} | {_member(i.full) for i in added})
        gone = sorted({_member(i.full) for i in removed})
        when = f"{_when(older)} to {_when(newer)}"
        if gone:
            rows.append({**row, "status": "removed", "changed": names, "removed": gone,
                         "detail": f"{', '.join(gone)} removed in {when}: the patch cannot reach it"})
        elif names:
            rows.append({**row, "status": "changed", "changed": names,
                         "detail": f"{', '.join(names)} changed in {when}: read whether the fault is fixed"})
        else:
            rows.append({**row, "status": "unchanged", "detail": f"untouched by the update of {when}: the patch stays"})
    return rows


def _member(full):
    parts = full.split("(")[0].split(".")
    return ".".join(parts[-2:])


def update_rows(versions_by_file, since, compare_all, shown=NEW_TYPES_SHOWN):
    """[{mod, file, versions, added, removed, signatures, bodies, newTypes}] for each file updated in the window, largest first.
    `compare_all(older, newer)` gives (changes, removed, added)."""
    rows = []
    for (owner, file), chain in sorted(versions_by_file.items()):
        if len(chain) < 2 or (chain[-1].seen_at or "") < since:
            continue
        older, newer = chain[-2], chain[-1]
        changes, removed, added = compare_all(older, newer)
        types = [i for i in code_compare._not_inside(added) if i.kind in code_compare.CONTAINER_KINDS]
        rows.append({"mod": newer.owner_name or owner, "file": file, "versions": f"{_when(older)} to {_when(newer)}",
                     "keptAt": newer.seen_at, "added": len(added), "removed": len(removed),
                     "signatures": sum(1 for c in changes if c.signature),
                     "bodies": sum(1 for c in changes if not c.signature),
                     "newTypes": [i.full.split(".")[-1] for i in types[:shown]], "newTypeCount": len(types)})
    rows.sort(key=lambda r: (-(r["added"] + r["removed"] + r["signatures"] + r["bodies"]), r["mod"].lower(), r["file"]))
    return rows


def _archive_comparer(decompiled, code_cache, find_tool):
    """compare(older, newer, patterns) over the archive's builds, decompiled once each and cached."""
    built = {}

    def side(archive, version):
        if version.sha256 not in built:
            folder, _ = code_compare.decompile(archive.extract(version), decompiled, find_tool)
            corpus = code_index.Corpus(f"{version.file}@{version.sha256[:8]}", folder)
            index, _ = code_index.ensure(corpus, code_cache, False)
            built[version.sha256] = code_compare.Source(corpus, index)
        return built[version.sha256]

    def compare(archive, older, newer, patterns=()):
        return code_compare.compare(side(archive, older), side(archive, newer), patterns)

    return compare


# ---- our XML patches against the Defs as written ----

def _parse_file(path, cache):
    if path not in cache:
        try:
            cache[path] = [e for e in ET.parse(path).getroot() if isinstance(e.tag, str)]
        except (OSError, ET.ParseError):
            cache[path] = None
    return cache[path]


def _rest_found(rest, elements):
    """Whether the steps after the Def find a node in any of its definitions, as an ElementTree path."""
    path = "." + rest.rstrip("/")
    return any(element is not None and element.find(path) is not None for element in elements)


def patch_added_defs(conn, parsed):
    """{defName: mod name} for every Def a patch adds whole (an Add whose xpath is Defs itself), which the Def index, reading
    Defs folders only, cannot see."""
    found = {}
    rows = conn.execute("SELECT DISTINCT m.folder, p.load_folder, p.file, m.name FROM patch p JOIN mod m ON m.position = "
                        "p.mod_position WHERE trim(p.xpath, '/ ') = 'Defs'").fetchall()
    for folder, load_folder, file, mod_name in rows:
        path = Path(folder) / load_folder / file if load_folder else Path(folder) / file
        if path not in parsed:
            try:
                parsed[path] = ET.parse(path).getroot()
            except (OSError, ET.ParseError):
                parsed[path] = None
        root = parsed[path]
        if root is None:
            continue
        for element in root.iter():
            xpath = element.find("xpath")
            if xpath is None or (xpath.text or "").strip().strip("/ ") != "Defs":
                continue
            for value in element.findall("value"):
                for added in value:
                    name = added.findtext("defName")
                    if name:
                        found.setdefault(name.strip(), mod_name)
    return found


def _patched_has(patched, name, def_type, rest):
    """Whether the patched-Defs file (every patch applied) holds the node: True, False, or None when it lacks the Def."""
    found = patched.execute("SELECT def_type, xml FROM pdef WHERE def_name = ? COLLATE NOCASE", (name,)).fetchall()
    if def_type and "*" not in def_type:
        found = [f for f in found if f[0] == def_type or f[0].split(".")[-1] == def_type.split(".")[-1]]
    if not found:
        return None
    return _rest_found(rest, [ET.fromstring(xml) for _, xml in found])


def xml_rows(conn, ours, patched=None):
    """{checked, skipped: {why: count}, rows: [{mod, file, operation, xpath, def, status, detail, definedBy}]} for our patches.
    Status: missing (no active mod defines the Def), node-missing (the Def, but not the node), patched (not in the Def as
    written, but there once every patch has run, by the patched-Defs file `patched`), found, made (the game makes the Def in
    code, so only its name is checked)."""
    active_names = {r[0] for r in conn.execute("SELECT name FROM mod WHERE installed = 1") if r[0]}
    active_ids = {r[0].lower() for r in conn.execute("SELECT package_id FROM mod WHERE installed = 1") if r[0]}
    patches = conn.execute("SELECT p.id, p.mod_position, p.operation, p.xpath, p.def_type, p.find_mods, p.may_require, "
                           "p.load_folder, p.file, m.name, m.package_id FROM patch p JOIN mod m ON m.position = p.mod_position "
                           "ORDER BY p.mod_position, p.id").fetchall()
    targets = defaultdict(list)
    for patch_id, name in conn.execute("SELECT patch_id, def_name FROM patch_target"):
        targets[patch_id].append(name)
    patterns = [p.lower() for p in ours]
    skipped, rows, checked, parsed = defaultdict(int), [], 0, {}
    added_by_patch = patch_added_defs(conn, {})
    for pid, position, operation, xpath, def_type, find_mods, may_require, load_folder, file, mod_name, package_id in patches:
        if not package_id or not any(fnmatch.fnmatchcase(package_id.lower(), p) for p in patterns):
            continue
        where = f"{load_folder}/{file}".lstrip("/")
        if (operation or "").endswith(QUESTIONS):
            skipped["a question (Conditional, Test, FindMod): finding nothing is an answer"] += 1
            continue
        if find_mods and any(name.strip() not in active_names for name in find_mods.split(", ")):
            skipped["for a mod that is not active"] += 1
            continue
        if may_require and any(i.strip().lower() not in active_ids for i in may_require.split(",")):
            skipped["for a mod that is not active"] += 1
            continue
        names = targets.get(pid, [])
        if not names:
            skipped["names no Def by defName"] += 1
            continue
        simple = SIMPLE_XPATH.match(xpath)
        for name in names:
            checked += 1
            query = ("SELECT d.def_type, d.implied, d.load_folder, d.file, d.element_index, m.folder, m.name FROM def d "
                     "JOIN mod m ON m.position = d.mod_position WHERE d.def_name = ? AND d.loads = 1")
            found = conn.execute(query, (name,)).fetchall()
            if def_type and "*" not in def_type:
                found = [f for f in found if f[0] == def_type or f[0].split(".")[-1] == def_type.split(".")[-1]]
            row = {"mod": mod_name, "file": where, "operation": (operation or "").split(".")[-1], "xpath": xpath, "def": name,
                   "definedBy": sorted({f[6] for f in found if f[6]})}
            if not found and name in added_by_patch:
                rows.append({**row, "status": "found", "definedBy": [added_by_patch[name]],
                             "detail": f"a patch of {added_by_patch[name]} adds this Def; only its name is checked"})
                continue
            if not found:
                rows.append({**row, "status": "missing", "detail": "no active mod defines this Def, in its Defs or by a patch"})
                continue
            if any(f[1] for f in found):
                rows.append({**row, "status": "made", "detail": "the game makes this Def in code; only its name is checked"})
                continue
            if not simple or not simple.group("rest").strip("/"):
                rows.append({**row, "status": "found", "detail": "the Def exists" + ("" if simple else
                                                                                       "; the xpath is past this check")})
                continue
            elements = []
            for _, _, folder, def_file, index, mod_folder, _ in found:
                path = Path(mod_folder) / folder / def_file if folder else Path(mod_folder) / def_file
                all_elements = _parse_file(path, parsed)
                elements.append(all_elements[index] if all_elements and index < len(all_elements) else None)
            if _rest_found(simple.group("rest"), elements):
                rows.append({**row, "status": "found", "detail": "the Def and the node exist"})
                continue
            once_patched = _patched_has(patched, name, def_type, simple.group("rest")) if patched is not None else None
            if once_patched:
                rows.append({**row, "status": "patched", "detail": "not in the Def as written, but there once every patch has "
                                                                   "run (the patched-Defs file)"})
                continue
            earlier = conn.execute("SELECT COUNT(*) FROM patch p JOIN patch_target t ON t.patch_id = p.id WHERE t.def_name = ? "
                                   "AND (p.mod_position < ? OR (p.mod_position = ? AND p.id < ?))",
                                   (name, position, position, pid)).fetchone()[0]
            rows.append({**row, "status": "node-missing", "earlierPatches": earlier,
                         "detail": f"the Def exists but not {simple.group('rest').strip('/')} in it as written"
                                   + (f"; {earlier} earlier {'patch names' if earlier == 1 else 'patches name'} this Def and may add it"
                                      if earlier else "; no earlier patch names this Def")
                                   + ("; not in the patched-Defs file either" if once_patched is False else "")})
    order = {"missing": 0, "node-missing": 1, "patched": 2, "made": 3, "found": 4}
    rows.sort(key=lambda r: (order[r["status"]], r["mod"].lower(), r["file"], r["def"]))
    return {"checked": checked, "skipped": dict(sorted(skipped.items())), "rows": rows}


# ---- the command ----

def _parser():
    p = argparse.ArgumentParser(prog="rimworld-update-check", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--root", default=".", help="the repository holding our C#, our mods and config/update-check.json")
    p.add_argument("--only", help="some of " + ", ".join(PARTS) + ", by commas (default: all four)")
    p.add_argument("--since", help="count updates the archive kept since this moment (ISO, UTC unless it says otherwise)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"without --since: the last N days (default {DEFAULT_DAYS})")
    p.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    p.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    p.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    p.add_argument("--archive", help="the assembly archive (else PHOBOS_ASSEMBLY_ARCHIVE, the settings file, the default)")
    p.add_argument("--decompiler", help="ilspycmd (else PHOBOS_MODKIT_ILSPYCMD, ilspycmdPath in the settings file, the PATH)")
    p.add_argument("--cache", help="the kit's cache folder")
    p.add_argument("--settings", help="a JSON settings file")
    p.add_argument("--top", type=int, default=25, help="rows per table (default 25)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _parts(text):
    if not text:
        return PARTS
    chosen = tuple(p.strip() for p in text.split(",") if p.strip())
    unknown = [p for p in chosen if p not in PARTS]
    if unknown:
        raise UpdateCheckError(f"--only: {', '.join(unknown)} is not one of {', '.join(PARTS)}.")
    return chosen


def names_section(report, data, scan, findings, files):
    failing = [f for f in findings if f.fails]
    found = [f for f in findings if f.status in ("ok", "inherited")]
    unread = [f for f in findings if f.status == "type-missing"]
    data["names"] = {"found": len(found), "failing": [{"where": f"{f.file}:{f.line}", "target": f.label, "status": f.status,
                                                       "detail": f.detail or ""} for f in failing],
                     "notChecked": len(unread), "atRunTime": len(scan.unresolved), "assemblies": len(files)}
    summary = (f"{len(found)} of {len(found) + len(failing)} still found; {len(unread)} not checked (an optional mod not "
               f"active); {len(scan.unresolved)} worked out at run time.")
    if failing:
        report.section("Our patches' targets: some no longer match", summary,
                       Table(["Where", "Target", "Problem"], [[f"{f.file}:{f.line}", f.label, f.status + (": " + f.detail
                                                                                                         if f.detail else "")]
                                                               for f in failing]))
    else:
        report.section("Our patches' targets: every one found", summary)


def temporary_section(report, data, rows, top):
    data["temporary"] = rows
    if not rows:
        report.section("Temporary patches", "None listed (config/update-check.json names no temporaryPatches file).")
        return
    act = [r for r in rows if r["status"] in ("changed", "removed")]
    lead = (f"{len(act)} of {len(rows)} touched by an update: **read whether the fault is fixed** before taking a patch out."
            if act else f"None of {len(rows)} touched by an update in the window: every one stays.")
    report.section("Temporary patches", lead, Table(["Row", "Patch", "Mod", "Status", "What"],
                                                    [[str(r["row"]), r["patch"], r["mod"], r["status"], r["detail"]]
                                                     for r in rows][:top], len(rows)))


def updates_section(report, data, rows, top):
    data["updates"] = rows
    if not rows:
        report.section("Updates kept in the window", "None: the archive kept no update in the window "
                       "(rimworld-archive snapshot keeps them).")
        return
    report.section("Updates kept in the window", "Largest first. A mod we tie into that gains a feature may now do something "
                   "ours does too: read its new types before relying on our own.",
                   Table(["Mod", "File", "Versions", "Added", "Removed", "New signatures", "New bodies", "New types"],
                         [[r["mod"], r["file"], r["versions"], r["added"], r["removed"], r["signatures"], r["bodies"],
                           ", ".join(r["newTypes"]) + (f" and {r['newTypeCount'] - len(r['newTypes'])} more"
                                                       if r["newTypeCount"] > len(r["newTypes"]) else "")]
                          for r in rows][:top], len(rows)))


def xml_section(report, data, result, top):
    data["xml"] = result
    rows = result["rows"]
    problems = [r for r in rows if r["status"] in ("missing", "node-missing")]
    lead = (f"{result['checked']} Def names checked in our patches; {len(problems)} find nothing as the mods write them."
            if problems else f"{result['checked']} Def names checked in our patches; every one found.")
    patched = sum(1 for r in rows if r["status"] == "patched")
    if result.get("patchedDefs"):
        lead += (f" The patched-Defs file (written {result['patchedDefs']} UTC) confirms {patched} more once every patch has run"
                 " (the game writes the file again only when asked, so it may be older than the updates).")
    else:
        lead += " No patched-Defs file was found to confirm rows against (D'thorga Framework writes one on request)."
    skipped = "; ".join(f"{count} {why}" for why, count in result["skipped"].items())
    blocks = [lead] + ([f"Not checked: {skipped}."] if skipped else [])
    if problems:
        blocks.append(Table(["Mod", "File", "Def", "Status", "What"],
                            [[r["mod"], r["file"], r["def"], r["status"], r["detail"]] for r in problems][:top], len(problems)))
    report.section("Our XML patches", *blocks)


def build_report(args, parts, config, environ, settings_file, now, progress, run=None):
    report, data = Report("rimworld-update-check"), {"since": None, "parts": list(parts)}
    since = window_start(args.since, args.days, now)
    data["since"] = since
    report.lines.append(f"Updates counted from {since} UTC. Reads only: assemblies as metadata or decompiled, never run.")
    game = paths.game_path(args.game, environ, settings_file)
    workshop = paths.workshop_path(game, args.workshop, environ, settings_file)
    mods_config = paths.config_path(args.config, environ, settings_file)
    step, total = 0, len(parts)
    if "names" in parts:
        step += 1
        progress("Checking our patches' targets", step, total)
        targets = config.get("targets", {})
        scan, findings, files, _ = check_targets(args.root, targets.get("sources"), targets.get("assemblies"),
                                                 targets.get("typeLookups"), game, workshop, mods_config, environ, run)
        names_section(report, data, scan, findings, files)
    if "temporary" in parts or "updates" in parts:
        archive = Archive(archive_root(args.archive, environ, settings_file))
        decompiled = derived.folder(code_compare.CACHE_FOLDER, args.cache, environ, settings_file)
        code_cache = derived.folder(code_index.CACHE_FOLDER, args.cache, environ, settings_file)
        comparer = _archive_comparer(decompiled, code_cache,
                                     lambda: code_compare._find_decompiler(args.decompiler, environ, settings_file))
        versions = chains(archive)
        if "temporary" in parts:
            step += 1
            progress("Reading the temporary patches' faults", step, total)

            def members(older, newer, patterns):
                changes, removed, added, *_ = comparer(archive, older, newer, patterns)
                return changes, removed, added
            temporary_section(report, data, temporary_rows(read_temporary(args.root, config), versions, since, members), args.top)
        if "updates" in parts:
            step += 1
            progress("Measuring each update", step, total)

            def whole(older, newer):
                changes, removed, added, *_ = comparer(archive, older, newer)
                return changes, removed, added
            updates_section(report, data, update_rows(versions, since, whole), args.top)
    if "xml" in parts:
        step += 1
        progress("Checking our XML patches", step, total)
        install = defs.Install(game, workshop, mods_config)
        index, _ = defs.ensure(install, derived.folder(defs.CACHE_FOLDER, args.cache, environ, settings_file))
        dump = paths.patched_defs_path(None, environ, settings_file)
        patched_index = None
        if dump and Path(dump).is_file():
            patched_index, _ = patched_defs.ensure(dump, derived.folder(defs.CACHE_FOLDER, args.cache, environ, settings_file))
        with closing(derived.open_read_only(index)) as conn:
            if patched_index:
                with closing(derived.open_read_only(patched_index)) as patched:
                    result = xml_rows(conn, config.get("ourPackageIds") or [], patched)
            else:
                result = xml_rows(conn, config.get("ourPackageIds") or [])
        if dump and Path(dump).is_file():
            written = datetime.fromtimestamp(Path(dump).stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M")
            result["patchedDefs"] = written
        xml_section(report, data, result, args.top)
        report.lines.append("XML patches are checked against the Defs as written, before any patch: a node an earlier patch "
                            "adds reads as missing, so read the row before acting on it.")
    report.lines.append("A pass says names and nodes still exist, not that anything works in play; it is not a test in game.")
    return report, data


def main(argv=None, settings_file=None, environ=None, out=None, run=None, now=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    code, data = EXIT_OK, None
    try:
        parts = _parts(args.only)
        config = read_config(args.root)
        report, data = build_report(args, parts, config, environ, settings_file, now or datetime.now(timezone.utc),
                                    Progress(environ), run)
    except (UpdateCheckError, PatchesError, ArchiveError, code_index.CodeError, defs.DefsError, patched_defs.PatchedError) as error:
        report, code = Report("rimworld-update-check: error", [str(error)]), EXIT_FAILED
    print(envelope_text("rimworld-update-check", report, redact, data) if args.json else render_markdown(report, redact),
          file=out)
    return code


# It runs ilspycmd on archived builds it has not decompiled yet, so a program runs it on a person's press, as the archive's
# compare; it needs a repository (--root), so it has no question of its own for a page of reports to offer.
MANIFEST = {"game": "rimworld", "parser": _parser, "effect": RUNS, "surface": "update-check",
            "note": "Runs ilspycmd on archived assemblies and the kit's assembly reader, reading them, never loading them."}
