"""Files inside a project folder: link refusal, whole-tree reads, hashes and atomic writes.

Release tools write into the owner's repository (generated notes, catalogue records), so every path they touch is
checked to stay inside it and never to pass through a symbolic link or a Windows junction.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
import stat
import tempfile

REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafePath(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def is_link(path):
    """True for a symbolic link or a Windows reparse point such as a junction."""
    path = Path(path)
    try:
        info = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)


def inside(root, path):
    """path, made absolute, after refusing one that leaves root or passes through a link below root."""
    root = Path(root).resolve()
    path = Path(path) if Path(path).is_absolute() else root / path
    if not path.resolve().is_relative_to(root):
        raise UnsafePath(f"Path leaves the project folder: {path}")
    for part in (path, *path.parents):
        if part == root or len(part.parts) <= len(root.parts):
            break
        if is_link(part):
            raise UnsafePath(f"Filesystem link refused: {part}")
    return path


def relative(root, path):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def excluded(name, patterns):
    """True when a slash-separated relative path matches one of the glob patterns, by full path or file name."""
    base = name.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(base, p) or name.startswith(p.rstrip("/") + "/")
               for p in patterns)


def read_tree(folder, exclude=()):
    """{relative path: bytes} of every file under folder, in sorted order, refusing links."""
    folder = Path(folder)
    if is_link(folder) or not folder.is_dir():
        raise UnsafePath(f"Missing folder or link: {folder}")
    found = {}
    for path in sorted(folder.rglob("*")):
        if is_link(path):
            raise UnsafePath(f"Filesystem link refused: {path}")
        name = path.relative_to(folder).as_posix()
        if path.is_file() and not excluded(name, exclude):
            found[name] = path.read_bytes()
    return found


def atomic_write(path, data):
    """Replace path with data through a temporary file beside it, keeping the old file's permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    handle, temporary = tempfile.mkstemp(prefix=".modkit-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
