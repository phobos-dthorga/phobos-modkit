"""SteamCMD's workshop_build_item file: a "workshopitem" block of quoted keys and values.

Valve's SteamCMD Workshop guide (https://partner.steamgames.com/doc/features/workshop/implementation#SteamCmd) shows
the keys: appid, publishedfileid (0 creates an item, and SteamCMD writes the new ID back into the file), contentfolder,
previewfile, visibility, title, description and changenote. Valve does not document how values are escaped, so
values that would need escaping are refused: text keeps literal line breaks, paths use forward slashes, and ASCII
double quotes and backslashes are never written.

Steamworks' ISteamUGC limits (https://partner.steamgames.com/doc/api/ISteamUGC), counted in UTF-8 bytes with the
terminating NUL: k_cchPublishedDocumentTitleMax is 129, k_cchPublishedDocumentDescriptionMax and
k_cchPublishedDocumentChangeDescriptionMax are 8000.
"""
from __future__ import annotations

import re

TITLE_MAX_BYTES = 128
TEXT_MAX_BYTES = 7999
# EWorkshopFileVisibility, named as catalogues record them.
VISIBILITY = {"public": 0, "friends": 1, "private": 2, "unlisted": 3}
VISIBILITY_NAMES = {value: name for name, value in VISIBILITY.items()}


class VdfError(ValueError):
    pass


def quote(value):
    value = str(value).replace("\r", "")
    if '"' in value or "\\" in value:
        raise VdfError('Workshop text and paths must not contain " or \\ (use typographic quotes and forward slashes)')
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise VdfError("Unsupported control character in Workshop text")
    return '"' + value + '"'


def workshop_item(values):
    """The file's text for an ordered mapping of keys to values."""
    return '"workshopitem"\n{\n' + "".join(f"  {quote(k)} {quote(v)}\n" for k, v in values.items()) + "}\n"


def limit(label, data, maximum):
    if len(data) > maximum:
        raise VdfError(f"{label} is {len(data)} UTF-8 bytes; Steam accepts at most {maximum}. Shorten it before upload")


def item_id(text):
    """The publishedfileid in a file's text, or "0". SteamCMD rewrites a create's file with the new ID."""
    match = re.search(r'"publishedfileid"\s+"(\d+)"', text)
    return match[1] if match else "0"


def change_note(text):
    """The changenote value: one quoted string with literal newlines and never an inner quote, or None."""
    match = re.search(r'(?m)^\s*"changenote"\s+"([^"]*)"', text)
    return match[1] if match else None
