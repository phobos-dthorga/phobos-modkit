"""Install backups kept as one zip each (1.96.0; the owner's choice of 23 Nov 2026, "One zip per backup", over plain folders and a
store keeping each file once).

Measured on the owner's 27 RimWorld install backups (4,254 MB): one zip each, about 855 MB. The kind of compression barely
mattered (zip's own deflate 232 MB against 7-Zip's LZMA 216 MB, once repeats were taken out), so plain zip was chosen: Python
makes and reads it with nothing installed, Windows opens it, and one file inside is read without unpacking the rest.

A backup is still named `<mod>-<yyyymmdd>-<hhmmss>`; kept as a zip it is that name with `.zip`. Older backups stay folders until
`installs pack` (or the tidying after an install or a go-back) turns them into zips, each checked file for file before its
folder goes. This module names no game.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import zipfile

SUFFIX = ".zip"
PARTIAL = ".partial"
LEVEL = 6                     # deflate's usual level; 9 gave next to nothing more on textures (agent's measurement)
_MARK = ".from"               # in a peek folder: the archive's size and time it was taken from


class ArchiveError(ValueError):
    """An archive this module will not read or write, with the reason in words."""


def archive_of(backups, name):
    """Where a backup kept as a zip lives."""
    return Path(backups) / f"{name}{SUFFIX}"


def stored(backups, name):
    """Where a backup is: its zip, else its folder; None when it is neither."""
    archive = archive_of(backups, name)
    if archive.is_file():
        return archive
    folder = Path(backups) / name
    return folder if folder.is_dir() else None


def is_archive(path):
    return Path(path).suffix.lower() == SUFFIX and Path(path).is_file()


def names(backups):
    """Every backup's name in a folder: folders, and zips without their suffix. A half-written one (.partial) is left out."""
    try:
        entries = list(Path(backups).iterdir())
    except OSError:
        return []
    found = set()
    for entry in entries:
        if entry.name.endswith(PARTIAL):
            continue
        if entry.is_dir():
            found.add(entry.name)
        elif entry.suffix.lower() == SUFFIX and entry.is_file():
            found.add(entry.name[: -len(SUFFIX)])
    return sorted(found)


def members(archive):
    """(relative path, ZipInfo) for every file in an archive, by path; refuses a path that would leave the folder it unpacks to."""
    with zipfile.ZipFile(archive) as opened:
        found = []
        for info in opened.infolist():
            if info.is_dir():
                continue
            found.append((_safe(info.filename), info))
    return sorted(found, key=lambda pair: pair[0])


def _safe(name):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise ArchiveError(f"the archive holds {name!r}, which would land outside its folder; it was not read")
    return path.as_posix()


def files_of(folder):
    """(relative path, full path) for every file under a folder, by path."""
    folder = Path(folder)
    return sorted(((p.relative_to(folder).as_posix(), p) for p in folder.rglob("*") if p.is_file()), key=lambda pair: pair[0])


def unpacked_size(archive):
    with zipfile.ZipFile(archive) as opened:
        return sum(info.file_size for info in opened.infolist())


def write(folder, archive, progress=None):
    """Writes every file under folder into a new zip at archive, through a .partial file renamed only once the zip is whole and
    reads back with every file's check sum right. Returns the zip's size. Raises ArchiveError, leaving nothing behind, on failure."""
    archive = Path(archive)
    if archive.exists():
        raise ArchiveError(f"{archive.name} already exists")
    partial = archive.with_name(archive.name + PARTIAL)
    files = files_of(folder)
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=LEVEL) as out:
            for position, (relative, path) in enumerate(files, 1):
                if progress and position % 200 == 0:
                    progress(position, len(files))
                out.write(path, relative)
        with zipfile.ZipFile(partial) as check:
            bad = check.testzip()
            written = {_safe(n) for n in check.namelist() if not n.endswith("/")}
        if bad is not None:
            raise ArchiveError(f"{bad} did not read back right")
        if written != {relative for relative, _ in files}:
            raise ArchiveError("the zip does not hold every file of the folder")
        partial.replace(archive)
    except (OSError, zipfile.BadZipFile, ArchiveError) as error:
        _gone(partial)
        raise ArchiveError(f"{archive.name} could not be written ({error})") from None
    return archive.stat().st_size


def unpack(archive, folder):
    """Unpacks every file of an archive into folder, which must not exist yet."""
    folder = Path(folder)
    with zipfile.ZipFile(archive) as opened:
        for relative, info in members(archive):
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with opened.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)


def peek(archive, wanted, folder):
    """Unpacks the archive's files that `wanted` (a function of a relative path) asks for into folder, for reading as plain files:
    a mod's name and version, its changelog, its install record, a changed picture. A backup never changes, so what is there is
    kept; a folder taken from another archive of the same name is emptied first. Returns folder."""
    archive, folder = Path(archive), Path(folder)
    stat = archive.stat()
    mark = f"{stat.st_size} {int(stat.st_mtime)}"
    try:
        same = (folder / _MARK).read_text(encoding="utf-8") == mark
    except OSError:
        same = False
    if not same and folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / _MARK).write_text(mark, encoding="utf-8")
    with zipfile.ZipFile(archive) as opened:
        for relative, info in members(archive):
            target = folder / relative
            if not wanted(relative) or target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with opened.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
    return folder


def _gone(path):
    try:
        os.remove(path)
    except OSError:
        pass
