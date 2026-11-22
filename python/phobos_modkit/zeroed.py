"""zeroed: files a crash left filled with zero bytes, across the owner's repositories and the tools' own folders (1.81.0). Game-free.

    zeroed check [--days N | --all] [--root PATH ...] [--games FILE]   every zero-filled file, what it is and what puts it right
    zeroed restore [--days N | --all] [--root PATH ...] [--apply]      put each zero-filled file git tracks back from the last commit

A file written at the moment a PC crashes or loses power can be left at its full size but filled with zero bytes (seen 23 Nov 2026:
two of the kit's version files, and a test assembly the kit builds, all written seconds before a crash). Nothing says so until a
program trips over one. The owner's choice (23 Nov 2026): a check to run after a crash, by hand or from D'thorga Companion.

Where it looks, unless `--root` names folders: every repository on the Companion's games list (their `.git` folders too), the kit's
build folder and D'thorga Companion's own data folder. **Only files written in the last three days are opened** (`--days N` for
more, `--all` for every file): a crash damages only what was being written, and opening every file of those folders took over ten
minutes on the owner's PC, while the dates come with the folder listing. Each file is judged by its first bytes, and read in full
only when those are all zero. A file found is placed in one of these kinds, each with what to do:

- **tracked**: git has it, and the last commit holds a real copy: `restore --apply` writes that copy back (any change made since
  the last commit was lost to the crash already);
- **committed**: git's last commit holds the zeros too: an older commit or a safe copy is needed;
- **untracked**: in a repository but not in git: a safe copy, or making it again;
- **git's own store**: inside a `.git` folder: `git fsck` in that repository says what is damaged; the check changes nothing there;
- **built**: in the kit's build folder: made by a build, so a full rebuild makes it again (it is never deleted here);
- **Companion data**: D'thorga Companion's own records: its backups, or the safe copies.

Some files are all zeros by design (an empty disk image, a placeholder); the report says where each is, so one can be told apart.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
import subprocess
import sys

from . import native
from .manifest import READS, WRITES
from .paths import companion_data
from .progress import Progress
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FOUND, EXIT_USAGE = 0, 1, 2
HEAD_BYTES = 64                 # a file whose first bytes are not all zero is passed at once
CHUNK = 1024 * 1024
DAYS = 3                        # files written this recently are opened (agent default): a crash damages what it interrupts
TRACKED, COMMITTED, UNTRACKED, GIT_STORE, BUILT, COMPANION, OTHER = (
    "tracked", "committed", "untracked", "git's own store", "built", "Companion data", "other")
ADVICE = {
    TRACKED: "git's last commit holds a real copy: `zeroed restore --apply` writes it back.",
    COMMITTED: "the last commit holds the zeros too: an older commit or a safe copy is needed.",
    UNTRACKED: "not in git: a safe copy, or make it again.",
    GIT_STORE: "inside git's own store: run `git fsck` in that repository; nothing here is changed.",
    BUILT: "made by a build: a full rebuild makes it again (`--no-incremental` for .NET, `cargo clean -p` for Rust).",
    COMPANION: "D'thorga Companion's own records: its backups, or the safe copies.",
    OTHER: "look at what made it.",
}


def all_zero(path):
    """True when a file holds bytes and every one is zero."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(HEAD_BYTES)
            if not head or head.count(0) != len(head):
                return False
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    return True
                if chunk.count(0) != len(chunk):
                    return False
    except OSError:
        return False


def _files(root, since):
    """(path, entry) of every file under root written at or after `since` (seconds since 1970; 0 for all), from the listing's own
    dates, without opening a file."""
    waiting = [str(root)]
    while waiting:
        try:
            entries = list(os.scandir(waiting.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    waiting.append(entry.path)
                elif entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_mtime >= since:
                    yield entry.path
            except OSError:
                continue


def find(roots, progress=None, since=0):
    """Every zero-filled file under the roots written at or after `since`, each once."""
    progress = progress or (lambda *a, **k: None)
    found, seen = [], set()
    for n, root in enumerate(roots, 1):
        progress(f"Looking through {Path(root).name}", n - 1, len(roots))
        for name in _files(root, since):
            key = os.path.normcase(name)
            if key in seen:
                continue
            seen.add(key)
            if all_zero(name):
                found.append(Path(name))
    progress("Done", len(roots), len(roots))
    return found


def _repository_of(path):
    for parent in path.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _git(repository, *arguments):
    return subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, check=False)


def _committed(repository, relative):
    """The last commit's copy of a file, or None when git has none."""
    result = _git(repository, "show", f"HEAD:{relative}")
    return result.stdout if result.returncode == 0 else None


def classify(path, build=None, data=None):
    """(kind, repository or None, the last commit's copy or None) for one zero-filled file."""
    path = Path(path)
    for folder, kind in ((build, BUILT), (data, COMPANION)):
        if folder is not None and _inside(path, folder):
            return kind, None, None
    repository = _repository_of(path)
    if repository is None:
        return OTHER, None, None
    relative = path.relative_to(repository).as_posix()
    if relative.split("/")[0] == ".git":
        return GIT_STORE, repository, None
    if _git(repository, "ls-files", "--error-unmatch", "--", relative).returncode != 0:
        return UNTRACKED, repository, None
    copy = _committed(repository, relative)
    if copy is None or (copy and copy.count(0) == len(copy)):
        return COMMITTED, repository, None
    return TRACKED, repository, copy


def _inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


def default_roots(environ=None, games=None):
    """The repositories on the games list (when there is one), the kit's build folder and the Companion's own folder."""
    from .safe_copies_daily import DailyError, games_file, repositories
    roots = []
    try:
        roots += [r for r in repositories(games_file(games, environ)) if r.is_dir()]
    except DailyError:
        pass
    for folder in (native.build_dir(environ), companion_data(environ)):
        if Path(folder).is_dir():
            roots.append(Path(folder))
    return roots


def survey(roots, environ=None, progress=None, since=0):
    build, data = native.build_dir(environ), companion_data(environ)
    rows = []
    for path in find(roots, progress, since):
        kind, repository, copy = classify(path, build, data)
        try:
            stat = path.stat()
            size, changed = stat.st_size, stat.st_mtime
        except OSError:
            size, changed = 0, 0
        rows.append({"path": str(path), "kind": kind, "repository": str(repository) if repository else "", "size": size,
                     "changed": changed, "advice": ADVICE[kind], "restorable": copy is not None})
    rows.sort(key=lambda r: -r["changed"])
    return rows


def restore(rows):
    """Writes the last commit's copy over each zero-filled file git tracks. Returns the paths put back."""
    done = []
    for row in rows:
        if not row["restorable"]:
            continue
        path = Path(row["path"])
        copy = _committed(Path(row["repository"]), path.relative_to(row["repository"]).as_posix())
        if copy is None or not all_zero(path):
            continue
        partial = path.with_name(path.name + ".zeroed-partial")
        partial.write_bytes(copy)
        os.replace(partial, path)
        done.append(str(path))
    return done


def _parser():
    p = argparse.ArgumentParser(prog="zeroed", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, words in (("check", "every zero-filled file, what it is and what puts it right"),
                        ("restore", "put zero-filled files git tracks back as the last commit has them; only with --apply")):
        each = sub.add_parser(name, help=words)
        each.add_argument("--root", action="append", metavar="PATH", help="look only here (again for several)")
        when = each.add_mutually_exclusive_group()
        when.add_argument("--days", type=float, default=DAYS, metavar="N",
                          help=f"open files written in the last N days (default {DAYS})")
        when.add_argument("--all", action="store_true", help="open every file, however old (slow on large folders)")
        each.add_argument("--games", metavar="FILE", help="the games list naming the repositories (else the Companion's)")
        each.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        each.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
        if name == "restore":
            each.add_argument("--apply", action="store_true", help="write them back; without it, only say which")
    return p


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    roots = [Path(r) for r in args.root] if args.root else default_roots(environ, args.games)
    since = 0 if args.all else time.time() - max(args.days, 0) * 86400
    rows = survey(roots, environ, Progress(environ), since)
    data = {"roots": [str(r) for r in roots], "files": rows, "restored": [], "applied": False,
            "days": None if args.all else args.days}
    if args.report == "restore" and args.apply:
        data.update(restored=restore(rows), applied=True)
    if not rows:
        report = Report(f"Zero-filled files: none in {len(roots)} folders")
        report.lines.append("Nothing a crash left filled with zeros was found"
                            + ("." if args.all else f" among files written in the last {args.days:g} days."))
    else:
        report = Report(f"Zero-filled files: {len(rows)} found")
        report.section("Found, newest first", Table(["File", "Kind", "Bytes", "What puts it right"],
                                                    [[r["path"], r["kind"], str(r["size"]), r["advice"]] for r in rows]))
        if args.report == "restore":
            if args.apply:
                report.section("Put back from the last commit", Bullets(data["restored"] or ["None could be."]))
            else:
                report.lines.append("**Preview only. Add --apply to write the tracked ones back.**")
    report.section("Looked through", Bullets([str(r) for r in roots] or ["No folder: name one with --root."]))
    out.write((envelope_text("zeroed", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "question": "Did a crash leave any files filled with zeros?",
            "reports": {"check": {"question": "Did a crash leave any files filled with zeros?"},
                        "restore": {"effect": WRITES, "when": "--apply", "question": None}}}


if __name__ == "__main__":
    sys.exit(main())
