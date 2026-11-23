"""Generated blocks in a Markdown file: the one mechanism command-docs and doc-tables share (1.107.0).

A block is the text between `<!-- generated: KEY -->` and `<!-- end generated -->`. Everything outside the marks is the file's
own and is never touched. A file keeps its own line endings: it is read with LF and written back as it came.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

END = "<!-- end generated -->"


def start(key):
    return f"<!-- generated: {key} -->"


def keys(text):
    """Every block's key in text, in order."""
    return re.findall(r"<!-- generated: (.+?) -->", text)


def replace_block(text, key, body):
    """(text with the block's lines replaced by body, whether the block was there). Text uses LF."""
    mark = start(key)
    at = text.find(mark)
    if at < 0:
        return text, False
    end = text.find(END, at)
    if end < 0:
        return text, False
    return text[:at] + mark + "\n" + "\n".join(body) + "\n" + text[end:], True


def append_section(text, heading, blocks):
    """text with (key, subheading or None, body) blocks added under heading at its end; heading only if not there yet."""
    out = text.rstrip("\n") + "\n"
    if not re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE):
        out += f"\n{heading}\n"
    for key, sub, body in blocks:
        if sub:
            out += f"\n{sub}\n"
        out += "\n" + start(key) + "\n" + "\n".join(body) + "\n" + END + "\n"
    return out


def read(path):
    """(the file's text with LF, whether it used CRLF)."""
    raw = Path(path).read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def write(path, text, crlf=False):
    """Write text (LF) to path in the line endings the file had."""
    Path(path).write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def write_changed(root, files):
    """Write each file (with .path relative to root, .before, .after and .crlf) whose text changed. Returns the paths written."""
    written = []
    for file in files:
        if file.before is None or file.after is None or file.after == file.before:
            continue
        write(Path(root) / file.path, file.after, file.crlf)
        written.append(file.path)
    return written


def relative(target, doc):
    """A link from doc to target, both relative to the repository, with forward slashes on every system."""
    there, here = PurePosixPath(target).parts, PurePosixPath(doc).parent.parts
    same = 0
    while same < min(len(there), len(here)) and there[same] == here[same]:
        same += 1
    return "/".join([".."] * (len(here) - same) + list(there[same:]))
