"""Message signatures: one message's text with the parts that change between occurrences blanked out.

Two messages share a signature when they differ only in numbers, hexadecimal codes, GUIDs or the numeric IDs
games append to object names. Names, words and paths otherwise stay, so different problems stay apart.
"""
from __future__ import annotations

import re

MAX_LENGTH = 240
BLANK = "#"

_RULES = (
    # GUIDs.
    (re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"), BLANK),
    # Hexadecimal literals: 0x1A2B.
    (re.compile(r"\b0x[0-9A-Fa-f]+"), BLANK),
    # Runs of eight or more hex digits holding at least one digit: hashes and reference codes.
    (re.compile(r"\b(?=[0-9A-Fa-f]*\d)[0-9A-Fa-f]{8,}\b"), BLANK),
    # IDs appended to a name: Thing123456, FOP_CGL19172768 (three or more digits after a letter or underscore).
    (re.compile(r"(?<=[A-Za-z_])\d{3,}\b"), BLANK),
    # Free-standing numbers, including decimals, versions, times and coordinates: 5.5, 1.7.5000, 21:23:32.
    (re.compile(r"(?<![A-Za-z_\d])-?\d+(?:[.,:]\d+)*"), BLANK),
    # Runs of whitespace.
    (re.compile(r"\s+"), " "),
)


def normalise(text, max_length=MAX_LENGTH):
    """The signature of one message's text. Normalising a signature again changes nothing."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    text = text.strip()
    if len(text) > max_length:
        text = text[:max_length].rstrip() + "..."
    return text
