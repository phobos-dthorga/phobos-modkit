"""Files kept compressed with zstd, checked before anything is let go (1.149.0).

Two forms, both game-free:

- **One file packed in place**: `pack` writes `<file>.zst` beside it, reads it back to check its bytes give the same SHA-256, and
  only then removes the plain file; `unpack` gives the plain file back. For what cannot be made again but is seldom opened: a
  recording of a running game, a heap snapshot.
- **A store keeping each file once** (`Store`): files named by their SHA-256 under `objects/`, each compressed. For copies taken
  again and again whose files mostly repeat, such as the Companion's records copies every six hours.

Python 3.14's own `compression.zstd` (the owner's choice of 28 Nov 2026, "Raise the floor to 3.14"), at level 3: measured the same
day on the owner's files, a .NET trace came out 11 times smaller at about 350 MB a second; level 19 gained about a quarter more at a
twentieth of the speed. Already-compressed files (pictures) pass through nearly unchanged, at little cost.

Every write goes to a `.partial` beside its place and is renamed when whole, so a stopped run leaves no half file under the real name.
"""
from __future__ import annotations

from compression import zstd
import hashlib
import os
from pathlib import Path
import shutil

SUFFIX = ".zst"
PARTIAL = ".partial"
LEVEL = 3
CHUNK = 1 << 20
OBJECTS = "objects"


class PackError(ValueError):
    """A file this module will not pack or unpack, with the reason in words."""


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def packed_sha256(path):
    """The SHA-256 of what a packed file holds, read without writing it out."""
    digest = hashlib.sha256()
    with zstd.open(path, "rb") as source:
        for block in iter(lambda: source.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _partial(path):
    return Path(f"{path}.{os.getpid()}{PARTIAL}")


def _compress(source, target, level):
    """Compresses source into target through a partial file; returns nothing. Leaves no partial behind on failure."""
    partial = _partial(target)
    try:
        with open(source, "rb") as plain, zstd.open(partial, "wb", level=level) as out:
            shutil.copyfileobj(plain, out, CHUNK)
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()


def _decompress(source, target):
    partial = _partial(target)
    try:
        with zstd.open(source, "rb") as packed, open(partial, "wb") as out:
            shutil.copyfileobj(packed, out, CHUNK)
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()


def packed_of(path):
    """Where a file lives once packed."""
    return Path(f"{path}{SUFFIX}")


def is_packed(path):
    return Path(path).name.endswith(SUFFIX)


def present(path):
    """The plain file if it is there, else its packed form if that is, else None."""
    path = Path(path)
    if path.is_file():
        return path
    packed = packed_of(path)
    return packed if packed.is_file() else None


def pack(path, level=LEVEL):
    """Packs a file in place: writes `<file>.zst`, checks it holds the same bytes, then removes the plain file. Returns the packed
    path. A file already packed is left as it is."""
    path = Path(path)
    target = packed_of(path)
    if not path.is_file():
        if target.is_file():
            return target
        raise PackError(f"{path} is not there to pack")
    expected = sha256_of(path)
    original = path.stat()
    _compress(path, target, level)
    if packed_sha256(target) != expected:
        target.unlink()
        raise PackError(f"{target} did not read back the same as {path}; the plain file is kept")
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
    path.unlink()
    return target


def unpack(packed, target=None, keep=True):
    """Writes a packed file out plain: beside it with `.zst` taken off, or to target. Refuses to write over a file already there.
    With keep=False the packed file is removed once the plain one is whole. Returns the plain path."""
    packed = Path(packed)
    if not is_packed(packed) or not packed.is_file():
        raise PackError(f"{packed} is not a packed file ({SUFFIX})")
    target = Path(target) if target is not None else packed.with_name(packed.name[: -len(SUFFIX)])
    if target.exists():
        raise PackError(f"{target} is already there; nothing was written over it")
    target.parent.mkdir(parents=True, exist_ok=True)
    _decompress(packed, target)
    stamp = packed.stat()
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    if not keep:
        packed.unlink()
    return target


def read_bytes(path):
    """A file's bytes, plain or packed: the name given, or its packed form when only that is there."""
    found = present(path) or (Path(path) if is_packed(path) and Path(path).is_file() else None)
    if found is None:
        raise FileNotFoundError(str(path))
    if is_packed(found):
        with zstd.open(found, "rb") as source:
            return source.read()
    return found.read_bytes()


class Store:
    """Files kept once each, by SHA-256, compressed, under `<folder>/objects/<first two>/<sha256>.zst`."""

    def __init__(self, folder, level=LEVEL):
        self.folder = Path(folder)
        self.objects = self.folder / OBJECTS
        self.level = level

    def path_of(self, sha):
        return self.objects / sha[:2] / f"{sha}{SUFFIX}"

    def has(self, sha):
        return self.path_of(sha).is_file()

    def put(self, source):
        """Keeps a file; returns (sha256, bytes). It is read once, hashed and compressed together, so a file another program is
        still appending to is kept as it was read, under the name of what was read. A file already kept is not written again; a
        new one is read back and checked before it counts."""
        self.objects.mkdir(parents=True, exist_ok=True)
        partial = _partial(self.objects / "incoming")
        digest, size = hashlib.sha256(), 0
        try:
            with open(source, "rb") as plain, zstd.open(partial, "wb", level=self.level) as out:
                for block in iter(lambda: plain.read(CHUNK), b""):
                    digest.update(block)
                    size += len(block)
                    out.write(block)
            sha = digest.hexdigest()
            target = self.path_of(sha)
            if target.is_file():
                return sha, size
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(partial, target)
        finally:
            if partial.exists():
                partial.unlink()
        if packed_sha256(target) != sha:
            target.unlink()
            raise PackError(f"the kept copy of {source} did not read back the same")
        return sha, size

    def get(self, sha, target):
        """Writes a kept file out to target, which must not exist yet, and checks it."""
        source = self.path_of(sha)
        if not source.is_file():
            raise PackError(f"the store has no file {sha}")
        target = Path(target)
        if target.exists():
            raise PackError(f"{target} is already there; nothing was written over it")
        target.parent.mkdir(parents=True, exist_ok=True)
        _decompress(source, target)
        if sha256_of(target) != sha:
            target.unlink()
            raise PackError(f"{target} did not come out the same as the file kept")
        return target

    def check(self, sha):
        """Whether a kept file is there and still reads back to its name."""
        path = self.path_of(sha)
        try:
            return path.is_file() and packed_sha256(path) == sha
        except (OSError, zstd.ZstdError):
            return False

    def kept(self):
        """{sha256: bytes on disk} of every file kept."""
        found = {}
        if not self.objects.is_dir():
            return found
        for path in self.objects.glob(f"*/*{SUFFIX}"):
            found[path.name[: -len(SUFFIX)]] = path.stat().st_size
        return found

    def let_go(self, shas):
        """Removes the kept files named; returns (count, bytes) removed."""
        count = size = 0
        for sha in shas:
            path = self.path_of(sha)
            try:
                bytes_ = path.stat().st_size
                path.unlink()
            except OSError:
                continue
            count += 1
            size += bytes_
            try:
                path.parent.rmdir()
            except OSError:
                pass
        return count, size
