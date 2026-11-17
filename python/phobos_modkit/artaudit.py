"""Every shipped image paired with the record that says how it was made, and every picture a Def or class borrows.

Two inputs, both the repository's own:

- **Images and their records.** A record is a file beside the image whose name is the image's stem plus a record suffix
  (`.record.md`, `.export.json`, as the repository's config names them). An image without one of its own takes the record of the
  name before its last underscore, then the one before that (`Tank_DamageBody_east.png` -> `Tank_DamageBody` -> `Tank`), then
  the record named after its folder. The record's text says how the image was made: the kind whose pattern matches **first** in
  the text wins, so a generated picture whose record later mentions the stand-in it replaced is still generated.
- **Where pictures are used.** A game adapter (`games/<game>/art.py`) says which names each image answers to in the game and
  finds every use in the repository's Defs and code. A use is **borrowed** when the picture is not one of ours, or when other
  users share a word with its path and this one shares none (the shower trailer drawing the fuel bowser's body). A picture
  nobody's name matches is **shared**, not borrowed: several loadouts on one button, a blueprint on its vehicle's body.

Project policy lives in the repository's `config/art-audit.json`: where images are, the record suffixes, the kinds and their
patterns, what calls an image a stand-in, words too common to count, and accepted images and borrowings with their reasons.
Game-free: a game enters through the config's `game` and its adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from importlib import import_module
import json
from pathlib import Path, PurePosixPath
import re

CONFIG = Path("config") / "art-audit.json"
UNCLASSIFIED = "unclassified"
NO_RECORD = "no-record"
EVIDENCE_CHARS = 160
# Use statuses: own (its name matches the picture, or it is the only user), shared (nobody's name matches),
# borrowed (others' names match, its own does not), not-ours (no image of ours answers to the name).
OWN, SHARED, BORROWED, NOT_OURS = "own", "shared", "borrowed", "not-ours"
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
MIN_WORD = 3


class ArtAuditError(Exception):
    """The config is missing or wrong; the message says which and what to do."""


@dataclass
class Kind:
    kind: str
    label: str
    patterns: list
    listed: bool = False        # the report lists every open image of this kind (drawn in code, say)


@dataclass
class Accepted:
    reason: str
    image: str = None           # a glob over the image's repository path
    texture: str = None         # a glob over the name a Def or class uses
    owner: str = None           # a glob over the Def's or class's name, when only some users are accepted

    def takes_image(self, path):
        return self.image is not None and fnmatchcase(path.lower(), self.image.lower())

    def takes_use(self, use):
        if self.texture is None or not fnmatchcase(use.texture.lower(), self.texture.lower()):
            return False
        return self.owner is None or fnmatchcase(use.owner.lower(), self.owner.lower())


@dataclass
class Image:
    path: str                   # repository-relative, with forward slashes
    group: str                  # the mod or folder it belongs to
    records: list = field(default_factory=list)
    paired_by: str = ""         # own, prefix, folder, or "" when no record
    kind: str = NO_RECORD
    evidence: str = ""          # the record's words that decided the kind
    stand_in: str = ""          # the record's words calling it a stand-in, if any
    accepted: str = ""          # the reason, when the config accepts it as it is
    names: list = field(default_factory=list)   # the names the game knows it by (from the adapter)


@dataclass
class Use:
    owner_type: str             # ThingDef, VehicleDef, C#, Patch ...
    owner: str                  # defName, Name, class name
    field: str                  # graphicData/texPath, comps/li/icon ...
    texture: str                # the name as written
    file: str                   # repository-relative
    part: str = ""              # a list item's key inside the Def, such as an upgrade node
    inherited_from: str = ""    # the parent Def it came from, when inherited
    loose: bool = False         # its owner is code, not the thing drawn: it is judged only on whether the picture is ours
    images: list = field(default_factory=list)  # our images that answer to the name
    group: str = ""             # the mod or folder the using file belongs to
    status: str = ""
    owners: list = field(default_factory=list)  # for borrowed: the users whose names match the picture
    accepted: str = ""


@dataclass
class Audit:
    images: list
    uses: list
    kinds: list
    unreadable: list = field(default_factory=list)
    limits: list = field(default_factory=list)
    game: str = None


# ---- Config ----

def load_config(root):
    path = Path(root) / CONFIG
    if not path.is_file():
        raise ArtAuditError(f"No {CONFIG.as_posix()} in {root}: the repository's config names its images, records and kinds.")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ArtAuditError(f"{CONFIG.as_posix()} could not be read: {error}") from None
    if not isinstance(config, dict) or not isinstance(config.get("kinds", []), list):
        raise ArtAuditError(f"{CONFIG.as_posix()} must be an object whose kinds is a list.")
    return config


def kinds_of(config):
    found = []
    for entry in config.get("kinds", []):
        try:
            found.append(Kind(entry["kind"], entry.get("label", entry["kind"]),
                              [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in entry.get("patterns", [])],
                              bool(entry.get("listed", False))))
        except (KeyError, TypeError, re.error) as error:
            raise ArtAuditError(f"A kind in {CONFIG.as_posix()} is wrong ({error}): each needs kind and patterns.") from None
    return found


def accepted_of(config):
    found = []
    for entry in config.get("accepted", []):
        if not entry.get("reason") or not (entry.get("image") or entry.get("texture")):
            raise ArtAuditError(f"Every accepted entry in {CONFIG.as_posix()} needs a reason and an image or a texture.")
        found.append(Accepted(entry["reason"], entry.get("image"), entry.get("texture"), entry.get("owner")))
    return found


def adapter(game):
    """The game's art module, or None when the config names no game or the kit has no adapter for it."""
    if not game:
        return None
    try:
        return import_module(f".games.{game}.art", __package__)
    except ImportError:
        return None


# ---- Images and records ----

def find_images(root, patterns):
    root = Path(root)
    found = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                found.add(path.relative_to(root).as_posix())
    return sorted(found)


def group_of(path, group_globs):
    """The folder the file belongs to: the last part of the leading folders that match one of group_globs (mods/* -> the mod)."""
    globs = [group_globs] if isinstance(group_globs, str) else list(group_globs or ())
    parts = PurePosixPath(path).parts
    for group_glob in globs:
        depth = len(PurePosixPath(group_glob).parts)
        if len(parts) > depth and fnmatchcase("/".join(parts[:depth]), group_glob):
            return parts[depth - 1]
    return ""


def record_index(root, images, suffixes):
    """{folder: {name: [record paths]}} for every folder holding an image."""
    root = Path(root)
    index = {}
    for folder in sorted({str(PurePosixPath(p).parent) for p in images}):
        names = {}
        directory = root / folder
        for entry in sorted(directory.iterdir()) if directory.is_dir() else ():
            for suffix in suffixes:
                if entry.is_file() and entry.name.endswith(suffix) and len(entry.name) > len(suffix):
                    names.setdefault(entry.name[:-len(suffix)], []).append(f"{folder}/{entry.name}")
        index[folder] = names
    return index


def candidates(path, prefixes=True, folder_record=True):
    """(name, how) in the order a record is looked for: the stem, shorter names before each underscore, the folder's name."""
    pure = PurePosixPath(path)
    stem = pure.stem
    found = [(stem, "own")]
    if prefixes:
        while "_" in stem:
            stem = stem.rsplit("_", 1)[0]
            if stem:
                found.append((stem, "prefix"))
    if folder_record and pure.parent.name:
        found.append((pure.parent.name, "folder"))
    return found


def pair(path, index, prefixes=True, folder_record=True):
    """(records, how): every record the image's names find, nearest first, and how the nearest was found."""
    names = index.get(str(PurePosixPath(path).parent), {})
    records, how = [], ""
    for name, found_by in candidates(path, prefixes, folder_record):
        if name in names:
            records += [r for r in names[name] if r not in records]
            how = how or found_by
    return records, how


def _snippet(text, start, end):
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start:line_end if line_end >= 0 else len(text)]
    offset = start - line_start
    first = max(0, offset - 40)
    piece = line[first:first + EVIDENCE_CHARS].strip()
    return ("..." if first else "") + piece


def classify(text, kinds):
    """(kind, evidence): the kind whose pattern matches earliest in the text; ties go to the kind listed first."""
    best = None
    for order, kind in enumerate(kinds):
        for pattern in kind.patterns:
            match = pattern.search(text)
            if match and (best is None or (match.start(), order) < (best[0], best[1])):
                best = (match.start(), order, kind.kind, match.end())
    if best is None:
        return UNCLASSIFIED, ""
    return best[2], _snippet(text, best[0], best[3])


def stand_in(text, patterns):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return _snippet(text, match.start(), match.end())
    return ""


def read_records(root, records):
    """The records' text, nearest first and Markdown before JSON, so a record's own words come before an export's file names."""
    ordered = sorted(records, key=lambda r: r.endswith(".json"))
    texts = []
    for record in ordered:
        try:
            texts.append((Path(root) / record).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n\n".join(texts)


# ---- Uses ----

def words(text, common=()):
    """The words of a name or path, lower case, at least three letters, without the common ones."""
    return {w.lower() for w in _WORD.findall(text) if len(w) >= MIN_WORD} - set(common)


def _alike(a, b):
    """The same word, or one inside the other when the shorter has four letters or more (light, headlights)."""
    shorter, longer = sorted((a, b), key=len)
    return shorter == longer or (len(shorter) > MIN_WORD and shorter in longer)


def relates(use, common):
    mine = words(use.owner, common) | words(use.part, common)
    theirs = words(use.texture, common)
    return any(_alike(a, b) for a in mine for b in theirs)


def judge_uses(uses, common, accepted):
    """Set each use's status: own, shared, borrowed or not-ours; then the accepted reason, if any."""
    by_texture = {}
    for use in uses:
        by_texture.setdefault(use.texture.lower(), []).append(use)
    for users in by_texture.values():
        related = [u for u in users if relates(u, common)]
        related_ids = {id(u) for u in related}
        owners = sorted({u.owner for u in related})
        for use in users:
            if not use.images:
                use.status = NOT_OURS
            elif id(use) in related_ids or len({u.owner for u in users}) == 1:
                use.status = OWN
            elif related and use.owner not in owners and not use.loose:
                use.status, use.owners = BORROWED, owners
            else:
                use.status = SHARED
    for use in uses:
        if use.status in (BORROWED, NOT_OURS):
            use.accepted = next((a.reason for a in accepted if a.takes_use(use)), "")
    return uses


# ---- The audit ----

def audit(root, config):
    root = Path(root)
    kinds = kinds_of(config)
    accepted = accepted_of(config)
    stand_ins = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in config.get("standIn", [])]
    records_config = config.get("records", {})
    suffixes = records_config.get("suffixes", [".record.md"])
    prefixes = records_config.get("sharedByPrefix", True)
    folder_record = records_config.get("folderRecord", True)
    game = adapter(config.get("game"))

    paths = find_images(root, config.get("images", ["**/*.png"]))
    index = record_index(root, paths, suffixes)
    images = []
    for path in paths:
        image = Image(path, group_of(path, config.get("groupBy", "")))
        image.records, image.paired_by = pair(path, index, prefixes, folder_record)
        if image.records:
            text = read_records(root, image.records)
            image.kind, image.evidence = classify(text, kinds)
            image.stand_in = stand_in(text, stand_ins)
        image.accepted = next((a.reason for a in accepted if a.takes_image(path)), "")
        if game is not None:
            image.names = game.image_names(path)
        images.append(image)

    uses, unreadable, limits = [], [], []
    if game is not None:
        names = {}
        for image in images:
            for name in image.names:
                names.setdefault(name.lower(), []).append(image.path)
        uses, unreadable = game.find_uses(root, config, names)
        for use in uses:
            use.group = group_of(use.file, config.get("groupBy", ""))
        judge_uses(uses, {w.lower() for w in config.get("commonWords", [])}, accepted)
        limits = list(getattr(game, "LIMITS", ()))
    elif config.get("game"):
        limits = [f"The kit has no art adapter for {config['game']}, so no uses were read."]
    return Audit(images, uses, kinds, unreadable, limits, config.get("game"))
