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

from .installs import CHANGELOG, UNRELEASED, parse_changelog

SKIP_FOLDERS = {"node_modules", "external", "obj", "bin", "target", "dist", "artifacts", "__pycache__"}
SEARCH_DEPTH = 3                 # folders below the repository's root a changelog may sit in
KEY_LENGTH = 100                 # characters of an entry's first line that name it
NEEDLE_LENGTHS = (80, 48, 28)    # characters of an entry's opening tried, longest first
MIN_NEEDLE = 12                  # an opening shorter than this could be anyone's
MAX_FILES = 400                  # files listed for one commit
MAX_FILE_LINES = 600             # diff lines kept for one file
MAX_TOTAL_LINES = 8000           # diff lines kept for one answer
NEW_FILE_BYTES = 2 * 1024 * 1024  # a new file larger than this is listed, not read (agent default)
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

# What a file that isn't text is, so a program can choose how to show it (1.78.0): a picture or a sound drawn and played, a
# texture decoded, the rest named in words with their sizes. Never how to draw it; extensions any game's mods use.
MEDIA = {
    **dict.fromkeys((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tga", ".tif", ".tiff", ".ico", ".psd", ".xcf",
                     ".kra"), "picture"),
    **dict.fromkeys((".dds", ".ktx", ".ktx2", ".basis"), "texture"),
    **dict.fromkeys((".ogg", ".wav", ".mp3", ".flac", ".opus", ".m4a", ".aac", ".aif", ".aiff"), "sound"),
    **dict.fromkeys((".mp4", ".webm", ".mkv", ".mov", ".avi", ".ogv", ".bik"), "video"),
    **dict.fromkeys((".blend", ".fbx", ".obj", ".gltf", ".glb", ".i3d", ".shapes", ".3ds", ".dae", ".mesh"), "model"),
    **dict.fromkeys((".ttf", ".otf", ".woff", ".woff2", ".fnt"), "font"),
    **dict.fromkeys((".pdf", ".docx", ".odt", ".xlsx", ".ods", ".pptx", ".rtf"), "document"),
    **dict.fromkeys((".zip", ".7z", ".rar", ".gz", ".tar", ".bundle", ".unity3d", ".pak"), "archive"),
    **dict.fromkeys((".dll", ".exe", ".so", ".dylib", ".pdb", ".jar", ".class", ".msi"), "program"),
}

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


def read_listed(root, changelog):
    """A changelog that changelogs(root) has just listed, read straight from disk: no second walk of the repository to check it,
    which cost about 0.09 s a changelog in a large repository."""
    return parse_changelog((Path(root) / changelog).read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- naming a product

_DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def pending(root):
    """What each of a repository's changelogs has not released: entries not yet in a version, and versions still marked Draft
    (the newest first, with its date, and how many older drafts). Changelogs with nothing pending are left out. Reads the files only,
    never git, so it is quick enough for a program's first page."""
    found = []
    for path in changelogs(root):
        log = read_listed(root, path)
        unreleased = sum(1 for e in log.entries if e.version == UNRELEASED)
        drafts = [(v, rest) for v, rest in log.headings.items() if v != UNRELEASED and "draft" in rest.lower()]
        if not unreleased and not drafts:
            continue
        newest = drafts[0] if drafts else (None, "")
        day = _DAY.search(newest[1])
        found.append({"changelog": path, "product": product_name(log.title, path, root), "unreleased": unreleased,
                      "draftVersion": newest[0], "draftDate": day.group(1) if day else None,
                      "earlierDrafts": max(len(drafts) - 1, 0)})
    return found


def product_name(title, path, root):
    """"D'thorga Framework changelog" names D'thorga Framework and "Changelog (PhobosLib)" PhobosLib; a bare "Changelog" is named
    by its folder, or by the repository."""
    name = title.strip()
    if name.lower().endswith("changelog"):
        name = name[:-len("changelog")].strip()
    elif name.lower().startswith("changelog"):
        name = name[len("changelog"):].strip(" ()-:")
    return name or Path(path).parent.name or Path(root).name


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


def entry_commits(root, changelog, at=None):
    """Every entry's commit, two ways, in one map:

    - (version, first-line key) -> the commit that last wrote that line where it stands now (git blame, about 0.1 s a changelog).
      This is the answer for an entry in the changelog as it is: a line that many versions repeat word for word ("Not yet tested
      in game.") gets each version's own commit. A line no commit holds yet maps to None.
    - first-line key -> the oldest commit that ever added a line opening that way (git log -p), for an entry no longer in the
      changelog, such as one an installed copy has and the repository has since dropped.

    With at (a commit), both are read as the changelog stood at that commit: history up to it, and blame of the file there.
    """
    found = {}
    upto = [at] if at else []
    history = git(root, "log", "-p", "--reverse", "--format=%x00%H", "--unified=0", "--no-color", "--no-ext-diff", *upto, "--",
                  changelog, check=False)
    commit = None
    for line in history.split("\n"):
        if line.startswith("\x00"):
            commit = line[1:].strip()
        elif commit and line.startswith(("+- ", "+* ")):
            found.setdefault(line_key(line[3:]), commit)
    blame = git(root, "blame", "--line-porcelain", *upto, "--", changelog, check=False)
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
    size_before: int | None = None    # a binary file's bytes before and after the change (1.78.0); None where it did not exist
    size_after: int | None = None

    @property
    def media(self):
        """What a binary file is ("picture", "sound", "texture"...), "other" when the kit does not know; None for a text file."""
        return MEDIA.get(Path(self.path).suffix.lower(), "other") if self.binary else None

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


SIZE_BATCH = 100                 # paths given to one git ls-tree, to stay under Windows' command-line length


def tree_sizes(root, revision, paths):
    """{path: bytes} for the files of paths that revision holds; one git call a hundred paths. Empty when revision is not there
    (the first commit's parent, or HEAD before any commit)."""
    found = {}
    paths = sorted(set(paths))
    if not paths or not git(root, "rev-parse", "--verify", "-q", f"{revision}^{{tree}}", check=False).strip():
        return found
    for start in range(0, len(paths), SIZE_BATCH):
        out = git(root, "ls-tree", "-r", "-l", "-z", revision, "--", *paths[start:start + SIZE_BATCH], check=False)
        for record in out.split("\0"):
            info, _, path = record.partition("\t")
            parts = info.split()
            if path and len(parts) == 4 and parts[1] == "blob" and parts[3].isdigit():
                found[path] = int(parts[3])
    return found


def add_sizes(root, commit, files):
    """Gives each binary file its size before and after: the commit's parent and the commit, or for changes in no commit yet, the
    last commit and the file on disk. A program shows them for files it cannot draw, and they say how large the bytes it asks for
    will be."""
    binary = [f for f in files if f.binary]
    if not binary:
        return
    before_revision = f"{commit.hash}^" if commit else "HEAD"
    before = tree_sizes(root, before_revision, [f.old_path or f.path for f in binary if f.change != "added"])
    after = tree_sizes(root, commit.hash, [f.path for f in binary if f.change != "removed"]) if commit else {}
    for found in binary:
        if found.change != "added":
            found.size_before = before.get(found.old_path or found.path)
        if found.change == "removed":
            continue
        if commit:
            found.size_after = after.get(found.path)
        else:
            on_disk = Path(root) / found.path
            found.size_after = on_disk.stat().st_size if on_disk.is_file() else None


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


def commit_code(root, changelog, commit_hash):
    """What one commit changed, as entry_code gives it, with every entry it wrote into the changelog: for a fact on the timeline,
    whose entries may since have been reworded or removed. changelog may be one the repository no longer has."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit_hash or ""):
        raise ChangesError(f"{commit_hash!r} is not a commit.")
    commit = describe(root, commit_hash)
    if commit is None:
        raise ChangesError(f"{commit_hash[:12]} is not a commit of this repository.")
    diff = git(root, "show", commit.hash, "--format=", "--find-renames", "--unified=3", "--no-color", "--no-ext-diff")
    written = entries_written(git(root, "show", commit.hash, "--format=", "--unified=0", "--no-color", "--no-ext-diff", "--",
                                  changelog))
    files = ordered(parse_diff(diff), changelog)
    add_sizes(root, commit, files[:MAX_FILES])
    return EntryCode(commit, files[:MAX_FILES], written, max(0, len(files) - MAX_FILES))


def new_files_diff(root):
    """Every file git has not been told of yet (ignored ones left out), as a diff adding it whole (1.57.1).

    `git diff HEAD` leaves these out, so an entry in no commit showed only the edits to files git knew, and a new feature, mostly new
    files, looked a fraction of its size (the owner's "it doesn't seem to be showing the full extent", 20 Nov 2026: 25 files and 104
    lines shown of 113 files and 5,432 lines). A file with a NUL byte in its first 8 KB, or over NEW_FILE_BYTES, counts as binary."""
    listed = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    parts = []
    for path in sorted(p for p in listed.split("\0") if p):
        if any(part in SKIP_FOLDERS for part in Path(path).parts[:-1]):
            continue
        head = f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        try:
            data = (Path(root) / path).read_bytes()
        except OSError:
            continue
        if len(data) > NEW_FILE_BYTES or b"\0" in data[:8192]:
            parts.append(head + f"Binary files /dev/null and b/{path} differ\n")
            continue
        lines = data.decode("utf-8", "replace").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if not lines:
            parts.append(head)
            continue
        parts.append(head + f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines))
    return "".join(parts)


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
        diff = git(root, "diff", "HEAD", "--find-renames", "--unified=3", "--no-color", "--no-ext-diff") + new_files_diff(root)
        written = entries_written(git(root, "diff", "HEAD", "--unified=0", "--no-color", "--no-ext-diff", "--", changelog))
    else:
        diff = git(root, "show", commit.hash, "--format=", "--find-renames", "--unified=3", "--no-color", "--no-ext-diff")
        written = entries_written(git(root, "show", commit.hash, "--format=", "--unified=0", "--no-color", "--no-ext-diff", "--",
                                      changelog))
    files = ordered(parse_diff(diff), changelog)
    add_sizes(root, commit, files[:MAX_FILES])
    opening = (needles(text) or [flat])[-1]
    others = [w for w in written if not w.startswith(opening)]     # both as written, bold marks and all
    return EntryCode(commit, files[:MAX_FILES], others, max(0, len(files) - MAX_FILES))
