"""The code behind a changelog entry: the commit that wrote the entry into its changelog, and what that commit changed.

No game in it, and nothing asked of how a changelog is written beyond what the kit already reads (## version headings, - entries).
Where a repository's rule is that a change and its changelog entry go in one commit, the commit that first wrote the entry is the
change itself. git finds it: the first commit, oldest first, in which the entry's opening words appear in that changelog
(git log -S). An entry no commit holds yet is still in the working tree, and its code is the uncommitted changes.

What this cannot know: which lines of a commit belong to which entry, when one commit wrote several. The answer names the other
entries that came with the commit, so a reader is never told that a whole commit is one entry's work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess

from .installs import CHANGELOG, parse_changelog

SKIP_FOLDERS = {"node_modules", "external", "obj", "bin", "target", "dist", "artifacts", "__pycache__"}
SEARCH_DEPTH = 3                 # folders below the repository's root a changelog may sit in
KEY_LENGTH = 100                 # characters of an entry's first line that name it
NEEDLE_LENGTHS = (80, 48, 28)    # characters of an entry's opening tried, longest first
MIN_NEEDLE = 12                  # an opening shorter than this could be anyone's
MAX_FILES = 400                  # files listed for one commit
MAX_FILE_LINES = 600             # diff lines kept for one file
MAX_TOTAL_LINES = 8000           # diff lines kept for one answer
GIT_TIMEOUT = 120

# What a file is, for ordering (code first) and for a program choosing how to colour it. Never a colour itself.
LANGUAGES = {
    ".cs": "csharp", ".lua": "lua", ".py": "python", ".rs": "rust", ".ts": "typescript", ".js": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".svelte": "svelte", ".java": "java", ".cpp": "cpp", ".h": "cpp", ".c": "c", ".go": "go",
    ".ps1": "powershell", ".sh": "bash", ".bat": "dos", ".cmd": "dos", ".sql": "sql",
    ".xml": "xml", ".csproj": "xml", ".props": "xml", ".targets": "xml", ".html": "xml", ".svg": "xml", ".i3d": "xml",
    ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".ini": "ini", ".cfg": "ini", ".css": "css",
    ".md": "markdown", ".txt": "plain", ".tsv": "plain", ".csv": "plain",
}
CODE = {"csharp", "lua", "python", "rust", "typescript", "javascript", "svelte", "java", "cpp", "c", "go", "powershell", "bash",
        "dos", "sql", "css"}
DATA = {"xml", "json", "toml", "yaml", "ini"}
KINDS = ("code", "data", "words", "other")

_DIFF_HEAD = re.compile(r"^diff --git a/(.*?) b/(.*)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


class ChangesError(ValueError):
    """A question this tool cannot answer, with the reason in words."""


def git(root, *arguments, check=True):
    """git's output as text (UTF-8), reading only: no optional locks, no file watcher, paths unquoted."""
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", "-C", str(root), *arguments]
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise ChangesError(f"git could not be run ({error}).") from None
    if result.returncode != 0 and check:
        raise ChangesError(f"git could not answer: {result.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return result.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- changelogs in a repository

def changelogs(root):
    """Every changelog in a repository, as paths relative to it, the root's own first. Build and dependency folders are skipped."""
    root = Path(root)
    found = []
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.is_file() and entry.name == CHANGELOG:
                found.append(entry.relative_to(root).as_posix())
            elif entry.is_dir() and depth < SEARCH_DEPTH and not entry.name.startswith(".") and entry.name not in SKIP_FOLDERS:
                stack.append((entry, depth + 1))
    return sorted(found, key=lambda p: (p.count("/"), p.lower()))


def read(root, changelog):
    """The parsed changelog at a path relative to the repository; raises ChangesError when it is not one of the repository's."""
    if changelog not in changelogs(root):
        raise ChangesError(f"{changelog!r} is not a changelog of this repository.")
    return parse_changelog((Path(root) / changelog).read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- the commit that wrote an entry

@dataclass
class Commit:
    hash: str
    time: int                 # seconds since 1970
    author: str
    subject: str


def needles(text):
    """Openings of an entry to look for, longest first: enough to be its own, short enough to sit on the entry's first line (an
    entry may run over several lines, and git looks for text as the file holds it). Its bold opening is tried too."""
    flat = " ".join(text.split())
    found = []
    bold = re.match(r"\*\*.+?\*\*", flat)
    for needle in [flat[:length].rstrip() for length in NEEDLE_LENGTHS] + ([bold.group(0)] if bold else []):
        if len(needle) >= MIN_NEEDLE and needle not in found:
            found.append(needle)
    return sorted(found, key=len, reverse=True) or ([flat] if flat else [])


def line_key(line):
    """An entry's first line as a key: spacing ignored, cut to KEY_LENGTH characters."""
    return " ".join(line.split())[:KEY_LENGTH]


NOT_COMMITTED = "0" * 40


def entry_commits(root, changelog):
    """Every entry's commit, two ways, in one map:

    - (version, first-line key) -> the commit that last wrote that line where it stands now (git blame, about 0.1 s a changelog).
      This is the answer for an entry in the changelog as it is: a line that many versions repeat word for word ("Not yet tested
      in game.") gets each version's own commit. A line no commit holds yet maps to None.
    - first-line key -> the oldest commit that ever added a line opening that way (git log -p), for an entry no longer in the
      changelog, such as one an installed copy has and the repository has since dropped.
    """
    found = {}
    history = git(root, "log", "-p", "--reverse", "--format=%x00%H", "--unified=0", "--no-color", "--no-ext-diff", "--", changelog,
                  check=False)
    commit = None
    for line in history.split("\n"):
        if line.startswith("\x00"):
            commit = line[1:].strip()
        elif commit and line.startswith(("+- ", "+* ")):
            found.setdefault(line_key(line[3:]), commit)
    blame = git(root, "blame", "--line-porcelain", "--", changelog, check=False)
    version, commit, seen_version = None, None, False
    for line in blame.split("\n"):
        if line.startswith("\t"):
            text = line[1:]
            if text.startswith("## "):
                heading = re.match(r"^## \[([^\]]+)\]", text.strip())
                if seen_version and not heading and text.strip().endswith("history"):
                    version = None           # a merged mod's old log follows; its lines are not this mod's entries
                    continue
                version = heading.group(1).strip() if heading else text[3:].strip()
                version = "Unreleased" if version.lower() == "unreleased" else version
                seen_version = True
            elif version and text.startswith(("- ", "* ")):
                found[(version, line_key(text[2:]))] = None if commit == NOT_COMMITTED else commit
        elif len(line) >= 40 and all(c in "0123456789abcdef" for c in line[:40]) and line[40:41] == " ":
            commit = line[:40]
    return found


def commit_of(entry, commits):
    """The commit that wrote an entry, from entry_commits: where it stands in the changelog now, else the oldest that ever added
    it; None when no commit holds it yet."""
    key = line_key(entry.first or entry.text)
    placed = (entry.version, key)
    return commits[placed] if placed in commits else commits.get(key)


def describe(root, commit):
    """A commit's hash, time, author and subject."""
    out = git(root, "show", "-s", "--format=%H%x1f%at%x1f%an%x1f%s", commit).strip()
    parts = out.split("\x1f")
    return Commit(parts[0], int(parts[1] or 0), parts[2], parts[3]) if len(parts) == 4 else None


def first_commit(root, changelog, text):
    """The oldest commit in which the entry's opening appears in the changelog; None when no commit holds it yet."""
    for needle in needles(text):
        out = git(root, "log", "--reverse", "--format=%H%x1f%at%x1f%an%x1f%s", "-S", needle, "--", changelog)
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                return Commit(parts[0], int(parts[1] or 0), parts[2], parts[3])
    return None


def entries_written(diff_text):
    """The openings of the changelog entries a commit's diff of the changelog added."""
    found = []
    for line in diff_text.splitlines():
        if line.startswith(("+- ", "+* ")) and not line.startswith("+++"):
            found.append(" ".join(line[3:].split()))
    return found


# ---------------------------------------------------------------- reading a diff

@dataclass
class FileChange:
    path: str
    change: str = "changed"           # added, removed, changed or renamed
    old_path: str = ""
    binary: bool = False
    additions: int = 0
    deletions: int = 0
    hunks: list = field(default_factory=list)     # {"header", "lines": [{"kind", "old", "new", "text"}]}
    truncated: bool = False

    @property
    def language(self):
        return LANGUAGES.get(Path(self.path).suffix.lower(), "plain")

    @property
    def kind(self):
        language = self.language
        if language in CODE:
            return "code"
        if language in DATA:
            return "data"
        return "words" if language in ("markdown", "plain") and not self.binary else "other"


def parse_diff(text, max_file_lines=MAX_FILE_LINES, max_total_lines=MAX_TOTAL_LINES):
    """The files of a unified diff, each with its hunks. Lines past the limits are counted, not kept, and the file says so."""
    files, current, hunk = [], None, None
    old_no = new_no = kept = total = 0
    for line in text.split("\n"):
        head = _DIFF_HEAD.match(line)
        if head:
            current = FileChange(head.group(2), old_path=head.group(1))
            files.append(current)
            hunk, kept = None, 0
            continue
        if current is None:
            continue
        if hunk is None or not line[:1] in ("+", "-", " ", "\\"):
            if line.startswith("new file mode"):
                current.change = "added"
            elif line.startswith("deleted file mode"):
                current.change, current.path = "removed", current.old_path
            elif line.startswith("rename to "):
                current.change, current.path = "renamed", line[len("rename to "):]
            elif line.startswith("rename from "):
                current.old_path = line[len("rename from "):]
            elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
                current.binary = True
            mark = _HUNK.match(line)
            if mark:
                old_no, new_no = int(mark.group(1)), int(mark.group(3))
                hunk = {"header": mark.group(5).strip(), "lines": []}
                current.hunks.append(hunk)
            continue
        if line.startswith("\\"):            # "\ No newline at end of file"
            continue
        kind, body = line[0], line[1:].rstrip("\r")
        if kind == "+":
            current.additions += 1
            numbers = (None, new_no)
            new_no += 1
        elif kind == "-":
            current.deletions += 1
            numbers = (old_no, None)
            old_no += 1
        else:
            numbers = (old_no, new_no)
            old_no += 1
            new_no += 1
        if kept < max_file_lines and total < max_total_lines:
            hunk["lines"].append({"kind": kind, "old": numbers[0], "new": numbers[1], "text": body})
            kept += 1
            total += 1
        else:
            current.truncated = True
    for found in files:
        found.hunks = [h for h in found.hunks if h["lines"]]
    return files


def ordered(files, changelog):
    """Code first, then data, then words, then the rest; within each, by path. The changelog itself is left out."""
    rank = {kind: position for position, kind in enumerate(KINDS)}
    kept = [f for f in files if f.path != changelog]
    return sorted(kept, key=lambda f: (rank[f.kind], f.path.lower()))


# ---------------------------------------------------------------- the answer

@dataclass
class EntryCode:
    commit: Commit = None             # None: the entry is in no commit yet
    files: list = field(default_factory=list)
    written_with: list = field(default_factory=list)   # openings of the other entries the same commit wrote
    files_left_out: int = 0


def entry_code(root, changelog, text):
    """The code behind one entry of a changelog: its commit's changes, or the uncommitted changes when no commit holds it."""
    log = read(root, changelog)
    flat = " ".join(text.split())
    entry = next((e for e in log.entries if " ".join(e.text.split()) == flat or e.lead == flat), None)
    if entry is None:
        raise ChangesError("That entry is not in this changelog as it stands now.")
    text = entry.text
    # The same answer the list gives: the commit that first added the entry's first line, else a search for its opening.
    known = commit_of(entry, entry_commits(root, changelog))
    commit = describe(root, known) if known else first_commit(root, changelog, text)
    if commit is None:
        diff = git(root, "diff", "HEAD", "--find-renames", "--unified=3", "--no-color", "--no-ext-diff")
        written = entries_written(git(root, "diff", "HEAD", "--unified=0", "--no-color", "--no-ext-diff", "--", changelog))
    else:
        diff = git(root, "show", commit.hash, "--format=", "--find-renames", "--unified=3", "--no-color", "--no-ext-diff")
        written = entries_written(git(root, "show", commit.hash, "--format=", "--unified=0", "--no-color", "--no-ext-diff", "--",
                                      changelog))
    files = ordered(parse_diff(diff), changelog)
    opening = (needles(text) or [flat])[-1]
    others = [w for w in written if not w.startswith(opening)]     # both as written, bold marks and all
    return EntryCode(commit, files[:MAX_FILES], others, max(0, len(files) - MAX_FILES))
