"""Changelogs in the Phobos form: one Unreleased section, then dated release entries marked Draft or Released.

    # Some mod changelog

    ## [Unreleased]

    ## [1.2.0] - 2026-11-08 - Draft

    ### Added

    - A thing.

Anything before the Unreleased heading is free text. Each entry's body is kept as written; renderers such as
phobos_modkit.steam.bbcode turn it into a store page's markup.

A heading ending in "history" after the releases (## Old Mod history) closes the mod's own log: when mods are merged,
the old mods' changelogs follow under such headings, kept as written and never read as this mod's releases.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

VERSION = r"\d+(?:\.\d+){1,3}"
VERSION_PATTERN = re.compile(VERSION)
RELEASE = re.compile(r"^## \[(" + VERSION + r")\] - (\d{4}-\d{2}-\d{2}) - (Draft|Released)$")
UNRELEASED = "## [Unreleased]"
HISTORY = re.compile(r"^## [^\[].* history$")
DRAFT, RELEASED = "Draft", "Released"


class ChangelogError(ValueError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    date: str          # YYYY-MM-DD: preparation for a Draft, publication for a Released entry
    status: str        # Draft or Released
    body: str          # the entry's lines as written, without the heading


def version_key(version):
    """A version as a tuple of numbers, for ordering: 1.10.0 comes after 1.9.0."""
    return tuple(int(part) for part in version.split("."))


def parse(text):
    """{version: Release} in the order written, after checking the structure. Raises ChangelogError."""
    releases, current, body, unreleased = {}, None, [], False

    def finish():
        if current:
            joined = "\n".join(body).strip("\n")
            if not joined.strip():
                raise ChangelogError(f"Empty release entry: {current[0]}")
            releases[current[0]] = Release(current[0], current[1], current[2], joined)

    for line in text.splitlines():
        if line.startswith("## "):
            finish()
            body = []
            if HISTORY.fullmatch(line) and unreleased:
                current = None
                break
            if line == UNRELEASED:
                if unreleased or releases or current:
                    raise ChangelogError("Unreleased must appear once, before version entries")
                unreleased, current = True, None
                continue
            match = RELEASE.fullmatch(line)
            if not match:
                raise ChangelogError(f"Invalid release heading: {line}")
            current = match.groups()
            try:
                date.fromisoformat(current[1])
            except ValueError:
                raise ChangelogError(f"Invalid date in heading: {line}") from None
            if current[0] in releases:
                raise ChangelogError(f"Duplicate release version: {current[0]}")
        elif current:
            body.append(line)
    finish()
    if not unreleased:
        raise ChangelogError(f"Missing {UNRELEASED} section")
    return releases


def mark_released(text, version, on):
    """text with version's Draft heading changed to Released on the date on (YYYY-MM-DD); None when it has none."""
    heading = re.compile(r"(?m)^## \[" + re.escape(version) + r"\] - \d{4}-\d{2}-\d{2} - Draft$")
    if not heading.search(text):
        return None
    return heading.sub(f"## [{version}] - {on} - {RELEASED}", text)
