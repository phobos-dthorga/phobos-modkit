"""rimworld-upstream: did another author change a method our code patches or names, in an update or in their source since?

    rimworld-upstream updates --root REPO        each archived file's last update: members our C# names that it changed or removed
    rimworld-upstream pending --root REPO --clones FOLDER [--days 30]   commits in the mods' public source since: the same members
    rimworld-upstream --root REPO --clones FOLDER   both
    rimworld-upstream pending --root REPO --clone-into FOLDER   pending, making or updating lean clones from the source register

Our side is every member our C# names by string or nameof on another assembly's type (the scan rimworld-targets checks:
Harmony patches, AccessTools, reflection). `updates` compares the newest two versions rimworld-archive kept of each file updated in
the last --days, member by member, with the code tool's compare (ilspycmd decompiles both, cached). `pending` reads the lean clones
rimworld-sources made: for each file that declares one of our target types, the commits since --days ago whose changed lines or
hunk headers name one of our members. It is a warning ahead of an update: the Workshop build may not hold those commits yet.

`--clone-into` (1.90.0) makes the lean clones itself, straight from the source register's confirmed repositories, and brings
existing ones up to date: no GitHub API call, so it suits a machine that is not the owner's, such as D'thorga Companion's nightly
watch on GitHub's own (phobos-companion docs/online.md, O3). `--json` carries every finding as data (`data.pending`,
`data.updates`), each pending one with a link to its commit.

Reads, except that --clone-into writes clones into the folder named. Matching is by type and member name: a common name (Tick) in a big file can be named by a change that is not to our
member, and a member another type inherits is matched only on the type that declares it.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from ... import cache as derived
from ...assembly_archive import Archive, ArchiveError, archive_root
from ...code import compare as code_compare, index as code_index
from ... import feeds, source_clones
from ...manifest import ONLINE, READS
from ...report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown
from ...source_clones import folder_name
from ...targets import scan_tree

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REPORTS = ("updates", "pending", "both")
DEFAULT_DAYS = 30
REGISTER = "config/source-repos.json"
DECLARES = r"\b(?:class|struct|interface|record|enum)\s+{name}\b"
LIMITS = ("Matched by type and member name. A common member name in a big file can be named by a change to something else, and "
          "an inherited member is matched only where it is declared. The compare reads C# decompiled by ilspycmd; a change a "
          "decompiler renders the same way is not seen.")


class UpstreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class Wanted:
    type: str          # the type's own name, without namespace or generic arguments
    member: str        # the member's name; the type's name again for a constructor
    where: str         # our file:line naming it first


def _bare(type_name):
    return type_name.split("<", 1)[0].strip().split(".")[-1].split("+")[-1]


def wanted_members(root, globs=("src/**/*.cs",)):
    """{(type, member): Wanted} for every member our C# names on another assembly's type."""
    scan = scan_tree(root, globs)
    found = {}
    for target in scan.targets:
        name = _bare(target.type_name)
        if not name:
            continue
        member = target.member or name
        found.setdefault((name, member), Wanted(name, member, f"{target.file}:{target.line}"))
    return found


# ---- updates: the archive's last two versions of each file ----

def _matches(full, wanted):
    """The Wanted a declaration's full name (Namespace.Type.Member) is, or None."""
    parts = full.split(".")
    if len(parts) < 2:
        return None
    member, owner = parts[-1].split("(")[0].split("<")[0], parts[-2].split("<")[0]
    return wanted.get((owner, member))


def update_rows(archive, wanted, days, now, decompiled, code_cache, find_tool, only_file=None, seen=None):
    """([(owner name, file, versions, member, what changed, ours)], [(file, why skipped)], [files compared]). When `seen` is a
    dict, it is filled with when the archive first kept each compared file's newer build, by (owner name, file) (1.51.0)."""
    groups = defaultdict(list)
    for version in archive.versions():
        groups[(version.owner, version.file)].append(version)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    rows, skipped, compared = [], [], []
    types = sorted({w.type for w in wanted.values()})
    patterns = [f"*.{t}" for t in types] + [f"*.{t}.*" for t in types]
    for (owner, file), chain in sorted(groups.items()):
        if len(chain) < 2 or (only_file and file.lower() != only_file.lower()):
            continue
        older, newer = chain[-2], chain[-1]
        if (newer.seen_at or "") < cutoff:
            continue
        try:
            sides = []
            for version in (older, newer):
                folder, _ = code_compare.decompile(archive.extract(version), decompiled, find_tool)
                corpus = code_index.Corpus(f"{file}@{version.sha256[:8]}", folder)
                built, _ = code_index.ensure(corpus, code_cache, False)
                sides.append(code_compare.Source(corpus, built))
        except (ArchiveError, code_index.CodeError) as error:
            skipped.append((file, str(error)))
            continue
        changes, removed, _, _, _, _ = code_compare.compare(sides[0], sides[1], patterns)
        compared.append(file)
        if seen is not None:
            seen[(newer.owner_name or owner, file)] = newer.seen_at
        when = f"{older.version or older.seen_at} to {newer.version or newer.seen_at}"
        for change in changes:
            hit = _matches(change.right.full, wanted)
            if hit:
                what = "new signature" if change.signature else f"new body ({change.body}, +{change.added_lines} -{change.removed_lines})"
                rows.append((newer.owner_name or owner, file, when, f"{hit.type}.{hit.member}", what, hit.where))
        for item in removed:
            hit = _matches(item.full, wanted)
            if hit:
                rows.append((newer.owner_name or owner, file, when, f"{hit.type}.{hit.member}", "**removed**", hit.where))
    return sorted(set(rows)), skipped, compared


# ---- pending: commits in the public source since ----

def _git(folder, args, run):
    result = run(["git", "-C", str(folder), "-c", "core.fsmonitor=false", *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise UpstreamError(f"git {args[0]} failed in {folder}: {result.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return result.stdout.decode("utf-8", "replace")


def declaring_files(folder, types):
    """{relative path: {type names it declares}} among the clone's C# files."""
    found = {}
    patterns = {t: re.compile(DECLARES.format(name=re.escape(t))) for t in types}
    for path in sorted(Path(folder).rglob("*.cs")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        here = {t for t, pattern in patterns.items() if t in text and pattern.search(text)}
        if here:
            found[path.relative_to(folder).as_posix()] = here
    return found


_COMMIT = re.compile(r"^\x00([0-9a-f]{7,40})\t(\S+)\t(.*)$")
_FILE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK = re.compile(r"^@@ [^@]* @@ ?(.*)$")


# A changed line that opens a member: then git's hunk header names the member before it, not the one changed.
_DECLARATION = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|static|override|virtual|abstract|"
                          r"sealed|async|extern|new|unsafe|partial)\s+)+[\w<>\[\],.? ]+\s+\w+\s*(?:<[^>]*>)?\s*\(")


def _hunk_names(header, changed, members):
    """The members a hunk changes: named in its changed lines, or in its header (the member it sits in, as git's C# rules find
    it) unless a changed line opens a member itself, when the header names the one before."""
    names = set()
    trust_header = not any(_DECLARATION.match(line) for line in changed)
    for member in members:
        pattern = re.compile(rf"\b{re.escape(member)}\b")
        if any(pattern.search(line) for line in changed) or (trust_header and pattern.search(header)):
            names.add(member)
    return names


def touched(log, files, members_of):
    """[(commit, date, subject, file, member)] from `git log -p` text: a hunk names a member of a type its file declares."""
    found, commit, current, header, changed = [], None, None, None, []

    def close():
        if current and commit and header is not None:
            for member in _hunk_names(header, changed, members_of(current)):
                found.append((*commit, current, member))

    for line in log.splitlines():
        head, name, hunk = _COMMIT.match(line), _FILE.match(line), _HUNK.match(line)
        if head or name or hunk:
            close()
            header, changed = None, []
        if head:
            commit, current = head.groups(), None
        elif name:
            current = name.group(1) if name.group(1) in files else None
        elif hunk:
            header = hunk.group(1)
        elif line[:1] in "+-" and not line.startswith(("+++", "---")):
            changed.append(line[1:])
    close()
    return sorted(set(found), key=lambda r: (r[1], r[0], r[3], r[4]), reverse=True)


def pending_rows(register, clones, wanted, days, run):
    """([(mod, date, commit, subject, member, ours)], [(mod, clone's newest commit date)], [(mod, why skipped)])."""
    by_type = defaultdict(set)
    for w in wanted.values():
        by_type[w.type].add(w.member)
    rows, fresh, skipped = [], [], []
    attributes = tempfile.NamedTemporaryFile("w", suffix=".gitattributes", delete=False, encoding="utf-8")
    with attributes:
        attributes.write("*.cs diff=csharp\n")     # git's own C# hunk headers name the method a change sits in
    try:
        for mod in register:
            if not mod.get("confirmed") or not mod.get("repository"):
                continue
            folder = Path(clones) / folder_name(mod["name"])
            if not (folder / ".git").exists():
                continue
            try:
                newest = _git(folder, ["log", "-1", "--format=%cs"], run).strip()
                fresh.append((mod["name"], newest))
                files = declaring_files(folder, by_type)
                if not files:
                    continue
                log = _git(folder, ["-c", f"core.attributesFile={attributes.name}", "log", f"--since={days}.days.ago",
                                    "--format=%x00%h%x09%cs%x09%s", "-p", "-U0", "--no-color", "--", *files], run)
            except UpstreamError as error:
                skipped.append((mod["name"], str(error)))
                continue
            members_of = lambda path, files=files: sorted({m for t in files[path] for m in by_type[t]})  # noqa: E731
            for commit, date, subject, path, member in touched(log, files, members_of):
                types = [t for t in files[path] if member in by_type[t]]
                ours = wanted.get((types[0], member)).where if types else ""
                rows.append((mod["name"], date, commit, subject[:90], f"{types[0] if types else '?'}.{member}", ours, path))
    finally:
        Path(attributes.name).unlink(missing_ok=True)
    return rows, fresh, skipped


# ---- The command ----

def _parser():
    p = argparse.ArgumentParser(prog="rimworld-upstream", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("report", nargs="?", choices=REPORTS, default="both", help="updates, pending or both (default)")
    p.add_argument("--root", default=".", help="the repository holding our C# (default: here)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"how far back to look (default {DEFAULT_DAYS})")
    p.add_argument("--file", help="updates: only this archived file (Vehicles.dll)")
    p.add_argument("--clones", help="pending: the folder rimworld-sources cloned into")
    p.add_argument("--clone-into", metavar="FOLDER",
                   help="pending: make or update lean clones of the register's confirmed repositories here, then read them")
    p.add_argument("--feed", metavar="FILE", help="pending: also write the findings as an upstream-watch feed file")
    p.add_argument("--register", default=REGISTER, help=f"pending: the source register, relative to the root (default {REGISTER})")
    p.add_argument("--archive", help="the assembly archive (else PHOBOS_ASSEMBLY_ARCHIVE, the settings file, the default)")
    p.add_argument("--decompiler", help="ilspycmd (else PHOBOS_MODKIT_ILSPYCMD, ilspycmdPath in the settings file, the PATH)")
    p.add_argument("--cache", help="the kit's cache folder")
    p.add_argument("--settings", help="a JSON settings file")
    p.add_argument("--top", type=int, default=25, help="rows per table (default 25)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _register(root, name):
    register_file = Path(root) / name
    try:
        register = json.loads(register_file.read_text(encoding="utf-8")).get("mods", {})
    except (OSError, ValueError) as error:
        raise UpstreamError(f"Cannot read the source register {register_file}: {error}") from error
    return list(register.values()) if isinstance(register, dict) else list(register)


def _commit_link(repository, commit):
    """The commit's page, for a repository on GitHub; None elsewhere."""
    found = re.match(r"https?://github\.com/([^/]+/[^/#?]+?)(?:\.git)?/?$", repository or "")
    return f"https://github.com/{found.group(1)}/commit/{commit}" if found else None


def build_report(args, wanted, environ, settings_file, run, now):
    """(report, whether anything was found, data): the data carries every finding, for a program or a feed."""
    report = Report("rimworld-upstream")
    report.lines.append(f"{len(wanted)} members on other authors' types are named by our C# under {args.root}; changes in the last "
                        f"{args.days} days are looked for.")
    data = {"days": args.days, "members": len(wanted), "updates": [], "pending": [], "clonesRead": [], "skipped": [], "clones": []}
    found_any = False
    if args.report in ("updates", "both"):
        archive = Archive(archive_root(args.archive, environ, settings_file))
        decompiled = derived.folder(code_compare.CACHE_FOLDER, args.cache, environ, settings_file)
        code_cache = derived.folder(code_index.CACHE_FOLDER, args.cache, environ, settings_file)
        rows, skipped, compared = update_rows(archive, wanted, args.days, now, decompiled, code_cache,
                                    lambda: code_compare._find_decompiler(args.decompiler, environ, settings_file), args.file)
        found_any |= bool(rows)
        data["updates"] = [{"mod": m, "file": f, "versions": v, "member": member, "change": change, "ours": ours}
                           for m, f, v, member, change, ours in rows]
        if rows:
            report.section("Updates that changed members we name", "The newest two versions the archive kept of each file updated in "
                           "the window. **Check each against our code before the owner plays**: a new signature or a removed member "
                           "can break a patch; a new body can change what our patch assumes.",
                           Table(["Mod", "File", "Versions", "Member", "Change", "Our code"], rows[:args.top], len(rows)))
        else:
            report.section("Updates that changed members we name", (f"None: {len(compared)} updated files compared ("
                           + ", ".join(compared[:args.top]) + "), and none changed a member our code names.") if compared
                           else "None: the archive kept no update in the window (rimworld-archive snapshot keeps them).")
        if skipped:
            report.section("Updates not compared", Bullets([f"{f}: {why}" for f, why in skipped[:args.top]]))
    if args.report in ("pending", "both"):
        clones = args.clone_into or args.clones
        if not clones:
            report.section("Commits in the public source", "Not looked for: name the clones folder with --clones, or --clone-into.")
        else:
            register = _register(args.root, args.register)
            if args.clone_into:
                wanted_repos = [(m["name"], m["repository"]) for m in register if m.get("confirmed") and m.get("repository")]
                outcomes = source_clones.ensure(wanted_repos, args.clone_into, refresh=True, run=run)
                data["clones"] = [{"mod": o.name, "action": o.action, "detail": o.detail} for o in outcomes]
                failed = [o for o in outcomes if o.action in ("failed", "refused")]
                if failed:
                    report.section("Clones not made or updated", Bullets([f"{o.name}: {o.action}, {o.detail}" for o in failed]))
            rows, fresh, skipped = pending_rows(register, clones, wanted, args.days, run)
            found_any |= bool(rows)
            where = {m.get("name"): m.get("repository") for m in register}
            data["pending"] = [{"mod": m, "date": d, "commit": c, "subject": s, "member": member, "ours": ours,
                                "repository": where.get(m), "link": _commit_link(where.get(m), c)}
                               for m, d, c, s, member, ours, _ in rows]
            data["clonesRead"] = [{"mod": m, "newest": newest} for m, newest in fresh]
            data["skipped"] = [{"mod": m, "why": why} for m, why in skipped]
            table = [(m, d, c, s, member, ours) for m, d, c, s, member, ours, _ in rows]
            if table:
                report.section("Commits since that touch members we name", "In the authors' public source, not necessarily in "
                               "the Workshop build yet: a warning ahead of an update.",
                               Table(["Mod", "Date", "Commit", "Subject", "Member", "Our code"], table[:args.top], len(table)))
            else:
                report.section("Commits since that touch members we name", f"None in {len(fresh)} cloned repositories.")
            if fresh:
                oldest = min(fresh, key=lambda f: f[1])
                report.lines.append(f"{len(fresh)} clones read; the one with the oldest newest commit is {oldest[0]} ({oldest[1]}). "
                                    "Bring them up to date with rimworld-sources first if that is old.")
            if skipped:
                report.section("Clones not read", Bullets([f"{m}: {why}" for m, why in skipped[:args.top]]))
    report.lines.append(LIMITS)
    return report, found_any, data


def main(argv=None, settings_file=None, environ=None, out=None, run=subprocess.run, now=None):
    import os
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
        wanted = wanted_members(args.root)
        if not wanted:
            raise UpstreamError(f"No member on another assembly's type is named by the C# under {args.root}.")
        moment = now or datetime.now(timezone.utc)
        report, _, data = build_report(args, wanted, environ, settings_file, run, moment)
        if args.feed:
            feeds.write_file(args.feed, "upstream-watch", {
                "game": "rimworld", "checked": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "days": args.days,
                "findings": data["pending"], "clonesRead": len(data["clonesRead"]), "skipped": data["skipped"]},
                volatile=("checked",))
    except (UpstreamError, ArchiveError, code_index.CodeError, feeds.FeedError) as error:
        report, code = Report("rimworld-upstream: error", [str(error)]), EXIT_FAILED
    print(envelope_text("rimworld-upstream", report, redact, data) if args.json else render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "reports": {None: {"effect": ONLINE, "when": "--clone-into"}},
            "note": "Runs ilspycmd on archived assemblies (reading them, never loading them) and git log on the source clones.",
            "question": "Did another author change a method we patch?"}
