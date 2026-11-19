"""A thing's own history: the commits that changed its lines, each with the changelog entries that commit wrote.

git's line-range log (`git log -L start,end:file`) follows a thing's lines back through every commit that changed them, as the
lines moved. Since the Phobos repositories put a change and its changelog entry in one commit, the entries a commit wrote say why
the thing changed (D'thorga Companion's cross-links, L2).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from .. import changes

MAX_COMMITS = 25
LIMIT_CEILING = 500     # the most commits one request may ask for
_PATH = re.compile(r"^\+\+\+ b/(.+)$")


def commits_touching(root, file, start, end, limit=MAX_COMMITS):
    """[(hash, unix time, subject)] of the commits that changed lines start to end of a file, newest first."""
    out = changes.git(root, "log", f"-L{start},{end}:{file}", f"--max-count={limit + 1}", "--format=%x00%H%x1f%at%x1f%s",
                      "--no-color", check=False)
    found = []
    for line in out.splitlines():
        if line.startswith("\x00"):
            parts = line[1:].split("\x1f")
            if len(parts) == 3:
                found.append((parts[0], int(parts[1] or 0), parts[2]))
    return found


def _product(root, commit, path):
    text = changes.git(root, "show", f"{commit}:{path}", check=False)
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "")
    return changes.product_name(title, path, root)


def entries_written(root, commit):
    """Every changelog entry a commit wrote, as {changelog, product, text}, in the order its diff lists them."""
    diff = changes.git(root, "show", "--format=", "--unified=0", "--no-color", "--no-ext-diff", commit, "--", "*CHANGELOG.md",
                       "CHANGELOG.md", check=False)
    found, path, section = [], None, []

    def close():
        if path:
            product = None
            for text in changes.entries_written("\n".join(section)):
                product = product or _product(root, commit, path)
                found.append({"changelog": path, "product": product, "text": text})

    for line in diff.splitlines():
        match = _PATH.match(line)
        if match:
            close()
            path, section = match.group(1).strip(), []
        elif line.startswith("+++ "):
            close()
            path, section = None, []
        else:
            section.append(line)
    close()
    return found


def history(root, node, limit=MAX_COMMITS):
    """A thing's history: its commits, newest first, each with the entries it wrote. node is a thing as the graph holds it."""
    found = commits_touching(root, node["file"], node["line"], node["end"] or node["line"], limit)
    commits = [{"hash": h, "time": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds"), "subject": s,
                "entries": entries_written(root, h)} for h, t, s in found[:limit]]
    return {"commits": commits, "more": len(found) > limit, "file": node["file"],
            "lines": [node["line"], node["end"] or node["line"]], "exists": Path(root, node["file"]).is_file()}
