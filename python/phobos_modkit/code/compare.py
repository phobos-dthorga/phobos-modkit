"""code compare: what changed between two builds of an assembly, declaration by declaration.

Each side is a .dll (decompiled once with ilspycmd and kept in the kit's cache), an indexed corpus, or a folder of C#.
Declarations are paired by full name and parameters, so a member keeps its identity however the file around it moved.
Comments and layout are ignored; strings and numbers are compared, and a change that touches nothing else is called
"values only". Reading source this way ignores what a rebuild alone disturbs in the compiled file, such as metadata
tokens, retargeted references and the numbers in compiler-generated names.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
import difflib
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .. import __version__, paths
from .. import cache as derived
from ..report import Code, Report, Table
from . import index
from .scan import DECOMPILER_NOTE, blank, uncommented

CACHE_FOLDER = "decompiled"
DECOMPILER = ("ilspycmdPath", "PHOBOS_MODKIT_ILSPYCMD")
DECOMPILE_FORMAT = "1"
DECOMPILE_SECONDS = 1800
DECOMPILES_KEPT = 12
COMPLETE_MARKER = "phobos-modkit-source.json"
EXIT_OK, EXIT_FAILED = 0, 1
CONTAINER_KINDS = ("class", "struct", "interface", "record")      # a member's changes are reported on the member
NUMBER = re.compile(r"(?<![\w.])(?:0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)[fFdDmMuUlL]*(?!\w)")
FAILURE_LINES = 8
LIMITS = ("Compared as C# source, ignoring comments and layout; strings and numbers count. A renamed declaration shows as "
          "one removed and one added. Attributes on a type are not compared. Both sides of a .dll comparison should use "
          "the same --reference folders.")


# ---- Getting source from an assembly ----

def _find_decompiler(explicit, environ, settings_file):
    found = paths.resolve(*DECOMPILER, None, explicit, environ, settings_file)
    if found is not None:
        if not Path(found).is_file():
            raise index.CodeError(f"No decompiler at {found}")
        return str(found)
    on_path = shutil.which("ilspycmd")
    if on_path is None:
        raise index.CodeError("Comparing a .dll needs ilspycmd. Name it with --decompiler, PHOBOS_MODKIT_ILSPYCMD or "
                              "ilspycmdPath in the settings file, or put it on the PATH.")
    return on_path


def _key(content, references):
    """What makes a decompile reusable: the assembly's bytes, the folders it was read against, the format."""
    folders = sorted(str(Path(r).resolve()).lower() for r in references)
    text = "\n".join([DECOMPILE_FORMAT, content, *folders])
    return hashlib.sha256(text.encode()).hexdigest()[:derived.DIGEST_LENGTH]


def decompile(dll, cache, find_tool, references=(), rebuild=False, run=subprocess.run):
    """The folder holding dll's decompiled source, decompiling only when no finished copy exists. Returns (folder, built).

    A folder counts as finished only once its marker is written, so an interrupted run is never read as a whole build.
    """
    dll, cache = Path(dll), Path(cache)
    content = hashlib.sha256(dll.read_bytes()).hexdigest()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", dll.stem)[:60]
    target = cache / f"{safe}-{_key(content, references)}"
    marker = target / COMPLETE_MARKER
    if marker.is_file() and not rebuild:
        os.utime(marker)                                     # the newest used are the ones kept
        return target, False
    tool = find_tool()
    building = target.with_name(target.name + ".building")
    for stale in (building, target):
        if stale.exists():
            shutil.rmtree(stale)
    building.mkdir(parents=True)
    command = [tool, "-p", "-o", str(building)]
    for reference in references:
        command += ["-r", str(reference)]
    command.append(str(dll))
    try:
        done = run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=DECOMPILE_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        shutil.rmtree(building, ignore_errors=True)
        raise index.CodeError(f"The decompiler could not read {dll.name}: {error}") from error
    if done.returncode != 0 or not any(building.rglob("*.cs")):
        said = "\n".join(((done.stderr or "") + (done.stdout or "")).strip().splitlines()[-FAILURE_LINES:])
        shutil.rmtree(building, ignore_errors=True)
        raise index.CodeError(f"The decompiler produced no source for {dll.name} (exit {done.returncode}). {said}".strip())
    (building / COMPLETE_MARKER).write_text(json.dumps(
        {"source": dll.name, "sha256": content, "references": [str(r) for r in references], "kit_version": __version__},
        indent=1), encoding="utf-8")
    building.replace(target)
    return target, True


def evict(cache, keep=DECOMPILES_KEPT):
    """Delete all but the most recently used decompiles: one game assembly is tens of megabytes of source."""
    cache = Path(cache)
    if not cache.is_dir():
        return
    finished = [p for p in cache.iterdir() if (p / COMPLETE_MARKER).is_file()]
    finished.sort(key=lambda p: ((p / COMPLETE_MARKER).stat().st_mtime_ns, p.name), reverse=True)
    for folder in finished[keep:]:
        shutil.rmtree(folder)


def _side(spec, known, decompiled, find_tool, references, rebuild):
    """A side named on the command line as (Corpus, built now)."""
    path = Path(spec)
    if spec.lower().endswith(".dll"):
        if not path.is_file():
            raise index.CodeError(f"No assembly at {spec}")
        folder, built = decompile(path, decompiled, find_tool, references, rebuild)
        return index.Corpus(f"{path.name}@{folder.name.rsplit('-', 1)[-1][:8]}", folder), built
    exact = [c for c in known if c.name.lower() == spec.lower()]
    if exact:
        return exact[0], False
    if path.is_dir() or (path.is_file() and path.suffix.lower() == ".cs"):
        return index.Corpus(path.name or spec, path), False
    raise index.CodeError(f"{spec} is not a .dll, a corpus or a folder of C#. The summary report lists the corpora.")


# ---- Reading declarations ----

@dataclass(frozen=True)
class Item:
    kind: str
    name: str
    full: str
    signature: str
    path: str
    start: int
    end: int


class Source:
    """One side's declarations and, read once each, its files."""

    def __init__(self, corpus, index_file):
        self.corpus = corpus
        self.root = Path(corpus.root)
        with closing(derived.open_read_only(index_file)) as conn:
            rows = conn.execute('SELECT d.kind, d.name, d.full, d.signature, f.path, d.start, d."end" FROM decls d '
                                "JOIN files f ON f.id = d.file WHERE d.kind <> 'namespace' "
                                "ORDER BY d.full COLLATE NOCASE, f.path, d.start").fetchall()
        self.items = [Item(*row) for row in rows]
        self._raw, self._code, self._shape = {}, {}, {}

    def raw(self, path):
        if path not in self._raw:
            source = self.root if self.root.is_file() else self.root / path
            self._raw[path] = source.read_text(encoding="utf-8", errors="replace")
        return self._raw[path]

    def code(self, path):
        """Each line of the file without comments, literals as written."""
        if path not in self._code:
            self._code[path] = uncommented(self.raw(path)).split("\n")
        return self._code[path]

    def shape(self, path):
        """Each line of the file without comments, literals blanked."""
        if path not in self._shape:
            self._shape[path] = blank(self.raw(path)).split("\n")
        return self._shape[path]

    def display(self, item):
        lines = self.raw(item.path).split("\n")[item.start - 1:item.end]
        return [line.rstrip() for line in lines if not DECOMPILER_NOTE.match(line)]


def _squash(text):
    return " ".join(text.split())


def declared(signature):
    """A signature without what a body holds: the scanner's includes an expression body and a field's initialiser."""
    depth = 0
    for i, char in enumerate(signature):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "=" and depth == 0 and signature[i - 1:i] not in ("=", "!", "<", ">") and signature[i + 1:i + 2] != "=":
            return _squash(signature[:i])
    return _squash(signature)


def _balanced(text, at):
    """The text inside the bracket opening at index at, or the rest of text when it never closes."""
    pairs, depth = {"(": ")", "[": "]"}, 0
    opener, closer = text[at], pairs[text[at]]
    for i in range(at, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[at + 1:i]
    return text[at + 1:]


def parameters(item):
    """The parameter list that tells overloads apart; empty for what cannot be overloaded."""
    if item.kind == "indexer":
        match = re.search(r"\bthis\s*\[", item.signature)
        return _squash(_balanced(item.signature, match.end() - 1)) if match else ""
    if item.kind not in ("method", "constructor", "operator", "delegate"):
        return ""
    match = re.search(re.escape(item.name.split()[-1]) + r"\s*(?:<[^()]*>)?\s*\(", item.signature)
    at = match.end() - 1 if match else item.signature.find("(")
    return _squash(_balanced(item.signature, at)) if at >= 0 else ""


def _pair(left, right):
    """(pairs, removed, added): by full name and parameters, then what is left of one name, in order."""
    def group(items, key):
        grouped = defaultdict(list)
        for item in items:
            grouped[key(item)].append(item)
        return grouped

    def exact(item):
        return item.full, parameters(item)

    pairs, rest_left, rest_right = [], [], []
    by_left, by_right = group(left, exact), group(right, exact)
    for key in sorted(by_left.keys() | by_right.keys()):
        a, b = by_left.get(key, []), by_right.get(key, [])
        pairs += list(zip(a, b))
        rest_left += a[len(b):]
        rest_right += b[len(a):]
    by_left, by_right = group(rest_left, lambda i: i.full), group(rest_right, lambda i: i.full)
    removed, added = [], []
    for key in sorted(by_left.keys() | by_right.keys()):
        a, b = by_left.get(key, []), by_right.get(key, [])
        pairs += list(zip(a, b))
        removed += a[len(b):]
        added += b[len(a):]
    return pairs, removed, added


# ---- Comparing ----

def _is_container(item):
    return item.kind.startswith(CONTAINER_KINDS)


def _is_type(item):
    return item.kind.startswith(index.TYPE_KINDS)


def _body(source, item, lines_of):
    return _squash(" ".join(lines_of(item.path)[item.start - 1:item.end]))


@dataclass
class Change:
    left: Item
    right: Item
    signature: bool
    body: str               # "", "code" or "values only"
    added_lines: int = 0
    removed_lines: int = 0


def _counts(old, new):
    added = removed = 0
    for line in list(difflib.unified_diff([_squash(x) for x in old], [_squash(x) for x in new], lineterm="", n=0))[2:]:
        added += line.startswith("+")
        removed += line.startswith("-")
    return added, removed


def _difference(source_a, source_b, a, b):
    """The Change between a paired declaration's two sides, or None when they are the same."""
    signature = declared(a.signature) != declared(b.signature)
    if _is_container(a) and _is_container(b):
        return Change(a, b, True, "") if signature else None
    same_place = a.path == b.path and (a.start, a.end) == (b.start, b.end)
    if same_place and source_a.raw(a.path) == source_b.raw(b.path):
        return None
    body = ""
    if _body(source_a, a, source_a.code) != _body(source_b, b, source_b.code):
        shape_a = NUMBER.sub("#", _body(source_a, a, source_a.shape))
        shape_b = NUMBER.sub("#", _body(source_b, b, source_b.shape))
        body = "values only" if shape_a == shape_b else "code"
    if not signature and not body:
        return None
    added, removed = _counts(source_a.display(a), source_b.display(b)) if body else (0, 0)
    return Change(a, b, signature, body, added, removed)


def _wanted(patterns):
    lowered = [p.lower() for p in patterns]
    return lambda item: not lowered or any(fnmatch.fnmatchcase(item.full.lower(), p) for p in lowered)


def _named(name):
    wanted, suffix = name.lower(), "." + name.lower()
    return lambda item: item.full.lower() == wanted or item.full.lower().endswith(suffix)


def _diff_lines(old, new, limit):
    lines = list(difflib.unified_diff(old, new, lineterm="", n=2))[2:]
    if not lines:                                     # only comments or layout differ, or one side alone is shown
        lines = [f"- {x}" for x in old] + [f"+ {x}" for x in new]
    if limit > 0 and len(lines) > limit:
        lines = lines[:limit] + [f"... {len(lines) - limit} more lines (--lines 0 shows all)"]
    return lines


def compare(left, right, patterns=()):
    """(changes, removed, added, same, left total, right total) for two Sources."""
    wanted = _wanted(patterns)
    left_items = [i for i in left.items if wanted(i)]
    right_items = [i for i in right.items if wanted(i)]
    pairs, removed, added = _pair(left_items, right_items)
    changes = [c for c in (_difference(left, right, a, b) for a, b in pairs) if c is not None]
    return changes, removed, added, len(pairs) - len(changes), len(left_items), len(right_items)


def _not_inside(items):
    """items without those whose owner is itself in items: a new type is one row, not one row per member."""
    types = {i.full for i in items if _is_type(i)}
    return [i for i in items if i.full.rsplit(".", 1)[0] not in types]


def _where(item):
    return f"{item.path}:{item.start}"


def _show(report, name, left, right, changes, removed, added, limit):
    matches = _named(name)
    shown = 0
    for change in changes:
        if matches(change.right):
            report.section(f"{change.right.kind} {change.right.full}",
                           Code(_diff_lines(left.display(change.left), right.display(change.right), limit), "diff"))
            shown += 1
    for item, source, mark, verb in [(i, left, "-", "removed") for i in removed] + [(i, right, "+", "added") for i in added]:
        if matches(item):
            text = [f"{mark} {line}" for line in source.display(item)]
            cut = text[:limit] + [f"... {len(text) - limit} more lines (--lines 0 shows all)"] if 0 < limit < len(text) else text
            report.section(f"{item.kind} {item.full} ({verb})", Code(cut, "diff"))
            shown += 1
    if not shown:
        report.lines.append(f"{name} did not change. Without --show the report lists what did.")
    return shown


def run(args, known, cache, decompiled, environ, settings_file):
    """The compare report and its exit code."""
    def find_tool():
        return _find_decompiler(args.decompiler, environ, settings_file)

    corpus_a, built_a = _side(args.left, known, decompiled, find_tool, args.reference, args.rebuild)
    corpus_b, built_b = _side(args.right, known, decompiled, find_tool, args.reference, args.rebuild)
    evict(decompiled)
    index_a, _ = index.ensure(corpus_a, cache, args.rebuild)
    index_b, _ = index.ensure(corpus_b, cache, args.rebuild)
    left, right = Source(corpus_a, index_a), Source(corpus_b, index_b)
    for source, spec in ((left, args.left), (right, args.right)):
        if not source.items:                          # an empty side must never read as "everything was removed"
            raise index.CodeError(f"{spec} holds no C# declarations, so there is nothing to compare.")
    changes, removed, added, same, total_a, total_b = compare(left, right, args.only)

    report = Report(f"code compare {corpus_a.name} {corpus_b.name}")
    report.lines.append(f"{corpus_a.name} has {total_a} declarations; {corpus_b.name} has {total_b}.")
    made = [c.name for c, built in ((corpus_a, built_a), (corpus_b, built_b)) if built]
    if made:
        report.lines.append(f"Decompiled now: {', '.join(made)}.")
    if args.show:
        return report, EXIT_OK if _show(report, args.show, left, right, changes, removed, added, args.lines) else EXIT_FAILED

    signatures = [c for c in changes if c.signature]
    bodies = sorted((c for c in changes if c.body and not c.signature),
                    key=lambda c: (-(c.added_lines + c.removed_lines), c.right.full.lower(), c.right.start))
    values = sum(1 for c in bodies if c.body == "values only")
    report.lines.append(f"{len(added)} added, {len(removed)} removed, {len(signatures)} with a new signature, "
                        f"{len(bodies)} with a new body ({values} of them values only), {same} the same.")
    if not (added or removed or changes):
        report.lines.append("Nothing differs.")
    if total_a and total_b and not (same or changes):
        report.lines.append("**The two sides share no declarations by name, so they may not be builds of the same thing.**")
    report.lines.append(LIMITS)

    def listed(heading, items, verb):
        items = _not_inside(items)
        if items:
            rows = [[i.kind, i.full, _squash(i.signature), _where(i)] for i in items[:args.top]]
            report.section(f"{heading} {verb} ({len(items)})", Table(["Kind", "Name", "Signature", "Where"], rows,
                                                                     total=len(items), widths={2: 110}))

    listed("Declarations", added, "added")
    listed("Declarations", removed, "removed")
    if signatures:
        rows = [[c.right.full, declared(c.left.signature), declared(c.right.signature), c.body or "same", _where(c.right)]
                for c in signatures[:args.top]]
        report.section(f"New signatures ({len(signatures)})", Table(["Name", "Was", "Now", "Body", "Where"], rows,
                                                                    total=len(signatures), widths={1: 90, 2: 90}))
    if bodies:
        rows = [[c.right.full, c.body, f"+{c.added_lines} -{c.removed_lines}", _where(c.right)] for c in bodies[:args.top]]
        report.section(f"New bodies, largest first ({len(bodies)})", Table(["Name", "Change", "Lines", "Where"], rows,
                                                                           total=len(bodies)))
        report.lines.append("--show NAME prints one declaration's changes as a diff.")
    return report, EXIT_OK
