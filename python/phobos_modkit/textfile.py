"""Reading text files that a running program may still be writing."""
from __future__ import annotations

from pathlib import Path


def read_text_shared(path):
    """The whole of a text file, decoded as UTF-8.

    The file is opened for reading only. CPython does not deny other programs read or write access to a file it
    opens, so a game that keeps its log open does not block this, provided the game itself lets others read it.
    A byte-order mark is dropped and undecodable bytes are replaced, so a line cut off mid-character at the end of
    a growing file still reads.
    """
    with open(Path(path), "rb") as fh:
        data = fh.read()
    return data.decode("utf-8-sig", errors="replace")
