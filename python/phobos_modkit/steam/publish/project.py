"""A publishing project: the repository, its Workshop catalogue, its layout and the game adapter that reads its mods.

The catalogue (config/workshop-publishing.json by default) lists every mod with its Workshop item:

    {
      "appId": "294100",
      "layout": { ... optional, see LAYOUT ... },
      "mods": {
        "MyFramework": {"itemId": null, "requires": [], "hold": null},
        "MyContent":   {"itemId": "3814698904", "requires": ["MyFramework"], "hold": "Held: awaiting play checks",
                        "uploadedVersion": "0.4.1", "uploadedVisibility": "public"}
      },
      "externalRequiredItems": ["3741030124"],
      "externalRequiredItemNames": {"3741030124": "Someone's loader"}
    }

itemId is written only from what Steam returned; uploadedVersion and uploadedVisibility are written by the uploader.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess

from ... import cache as derived
from ...files import inside, read_tree, relative
from ..vdf import VISIBILITY

CATALOGUE = "config/workshop-publishing.json"
ITEM_ID = re.compile(r"[1-9][0-9]*")
# Single spaces between words are allowed (1.100.0): Kenshi's mods are named so ("Phobos Coil Rifle").
MOD_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]| (?=[A-Za-z0-9_.-]))*")
VERSION = re.compile(r"\d+(?:\.\d+){1,3}")
STAGING_CACHE = "steam-publish"

# Paths are relative to the repository and may hold {mod}, the mod's catalogue name. Defaults suit both
# phobos-ostranauts and phobos-rimworld; a catalogue's "layout" overrides any of them.
LAYOUT = {
    "mod": "mods/{mod}",                     # the mod's source folder; the adapter reads its metadata here
    "changelog": "mods/{mod}/CHANGELOG.md",
    "page": "workshop/{mod}/page.bbcode",    # the Workshop description, in BBCode
    "releases": "workshop/{mod}/releases",   # generated per-version change notes, <version>.bbcode
    "content": "mods/{mod}",                 # the folder uploaded, unless the project supplies its own payload
    "exclude": [],                           # globs left out of the content (by path or by file name)
    "preview": None,                         # the cover, relative to the content; None: the adapter's
    "textFolder": None,                      # a content folder to carry the page and change note, or None
    "scope": ["mods/{mod}/"],                # changes here need changelog and page edits in the same change
    "dirtyExempt": [],                       # uncommitted changes here do not block a wider-than-private upload
    "receipts": ".local/workshop-receipts",  # upload records; keep them, change-note worksheets read them
    "settings": ".local/workshop-settings.json",  # the uploader's SteamUser and SteamCmdPath, never a password
    "worksheets": ".local/workshop-change-notes",
    "staging": None,                         # None: the kit's cache folder, outside a cloud-synced repository
    "pageMaxBytes": 7500,                    # our headroom under Steam's 8,000 bytes, not a Valve figure
    "previewMaxBytes": 1_000_000,            # our cover budget, not a Valve figure
    "pageRules": {"title": True, "version": True, "status": True},
    "build": None,                           # a command run before preparing, e.g. ["python", "scripts/build.py", "{mod}"]
    "contentPrefix": None,                   # 1.100.0: a folder in the item the content goes under, e.g. Contents/mods/{mod}
    "previewSource": None,                   # 1.100.0: the cover's file in the repository, when it is not in the content
}


class PublishError(ValueError):
    pass


@dataclass(frozen=True)
class ModInfo:
    title: str
    version: str
    tags: tuple = ()


class Adapter:
    """What one game's mods look like. Subclasses in phobos_modkit.games.<game>.publish fill this in."""
    name = "generic"
    app_id = None
    metadata = None          # a file, relative to a mod folder, that marks it as a mod
    preview = "preview.png"  # the cover, relative to the content folder

    def read(self, folder, item=None, mod=None):
        """ModInfo for the mod in folder; item is its catalogue entry."""
        raise NotImplementedError

    def check(self, project, mod, item):
        """Problems with the catalogue's record of mod, as messages."""
        return []

    def item_recorded(self, project, mod, item_id):
        """Called after a new item ID is saved; returns the repository files it wrote."""
        return []

    def after_upload(self, project, mod):
        """Reminders printed after an upload, for things the owner must still do on Steam for this game."""
        return []

    def layout(self):
        """The game's own defaults for the catalogue's layout keys."""
        return dict(getattr(self, "spec", {}).get("layout", {}))


class Project:
    def __init__(self, root, config, catalogue_path, adapter, payload=None, cache_folder=None):
        self.root = Path(root).resolve()
        self.config = config
        self.catalogue_path = catalogue_path
        self.adapter = adapter
        self.layout = {**LAYOUT, **adapter.layout(), **config.get("layout", {})}
        self.payload_hook = payload
        self.cache_folder = cache_folder

    # ---- loading ----

    @classmethod
    def load(cls, root, adapters, catalogue=None, payload=None, cache_folder=None, validate=True):
        """The project at root. adapters maps Steam app IDs to Adapter instances."""
        root = Path(root).resolve()
        path = inside(root, catalogue or CATALOGUE)
        if not path.is_file():
            raise PublishError(f"No Workshop catalogue at {relative(root, path)}")
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        app = str(config.get("appId", ""))
        if isinstance(config.get("game"), dict):
            # A game nobody has written a game file for: the catalogue says it as data (steam/publish/game_data.py).
            from .game_data import DataAdapter
            adapter = DataAdapter({"appId": app, **config["game"]}, relative(root, path))
            if adapter.app_id != app:
                raise PublishError("The catalogue's game block names another Steam app than its appId")
        elif app in adapters:
            adapter = adapters[app]
        else:
            raise PublishError(f"No game file for Steam app {app or '(none)'}; known: {', '.join(sorted(adapters))}. "
                               "A catalogue can describe its game itself in a \"game\" block.")
        project = cls(root, config, path, adapter, payload, cache_folder)
        if validate:
            project.validate()
        return project

    # ---- paths and names ----

    def path(self, key, mod=None):
        return inside(self.root, self.layout[key].format(mod=mod))

    def rel(self, path):
        return relative(self.root, path)

    @property
    def mods(self):
        return self.config["mods"]

    def has_marker(self, folder, mod):
        marker = self.adapter.metadata
        if not marker:
            return True
        if hasattr(self.adapter, "metadata_path"):
            return self.adapter.metadata_path(folder, mod).is_file()
        from .game_data import find
        return find(folder, marker.format(mod=mod)).is_file()

    def on_disk(self):
        """Mod folders that hold the adapter's metadata file. A layout "mod" of "." is a repository holding one mod at its
        top (1.100.0): the catalogue then lists exactly that one, under its own name."""
        template = self.layout["mod"]
        if template == ".":
            if len(self.mods) != 1:
                raise PublishError('A repository whose layout "mod" is "." holds one mod: list exactly one')
            only = next(iter(self.mods))
            return [only] if self.has_marker(self.root, only) else []
        if not template.endswith("/{mod}"):
            raise PublishError('layout "mod" must end in /{mod}, or be "." for a repository of one mod')
        parent = inside(self.root, template[: -len("/{mod}")])
        return sorted(p.name for p in parent.iterdir() if p.is_dir() and self.has_marker(p, p.name))

    def resolve(self, name):
        """A catalogue name from its full form or a unique ending, ignoring case: Framework for PhobosFramework."""
        if name in self.mods:
            return name
        found = [m for m in self.mods if m.lower().endswith(name.lower())]
        if len(found) != 1:
            raise PublishError(f"Unknown mod: {name}" if not found else f"{name} matches {', '.join(found)}")
        return found[0]

    def select(self, names, default=None):
        names = [self.resolve(n) for n in names] if names else list(default if default is not None else self.order())
        if len(names) != len(set(names)):
            raise PublishError("A mod is named twice")
        return names

    def info(self, mod):
        info = self.adapter.read(self.path("mod", mod), self.mods[mod], mod)
        if not VERSION.fullmatch(info.version or ""):
            raise PublishError(f"{mod}: version {info.version!r} is not a number like 1.2.3")
        if not info.title or any(c in info.title for c in "[]\n\r"):
            raise PublishError(f"{mod}: unsafe or missing title")
        return info

    def staging(self):
        if self.layout["staging"]:
            return self.path("staging")
        # One folder per repository in the kit's cache: the root's name and a short hash of its full path.
        key = self.root.name + "-" + hashlib.sha256(str(self.root).lower().encode()).hexdigest()[:8]
        base = Path(self.cache_folder) if self.cache_folder else derived.folder(STAGING_CACHE)
        return base / "staging" / key

    # ---- the catalogue ----

    def validate(self):
        known = set(self.on_disk())
        if set(self.mods) != known:
            missing, extra = sorted(known - set(self.mods)), sorted(set(self.mods) - known)
            raise PublishError("The catalogue must list every mod" + (f"; missing {', '.join(missing)}" if missing else "")
                               + (f"; no such mod folder for {', '.join(extra)}" if extra else ""))
        ids = []
        for name, item in self.mods.items():
            if not MOD_NAME.fullmatch(name):
                raise PublishError(f"Invalid mod name: {name}")
            item_id = item.get("itemId")
            if item_id is not None:
                if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id):
                    raise PublishError("Item IDs must be positive decimal strings or null")
                ids.append(item_id)
            requires = item.get("requires", [])
            if set(requires) - known or name in requires:
                raise PublishError(f"{name}: invalid dependency")
            uploaded = item.get("uploadedVersion")
            if uploaded is not None and (item_id is None or not isinstance(uploaded, str) or not VERSION.fullmatch(uploaded)):
                raise PublishError("uploadedVersion must be a version number, and only on a mod with an item ID")
            if item.get("uploadedVisibility") is not None and (uploaded is None or item["uploadedVisibility"] not in VISIBILITY):
                raise PublishError("uploadedVisibility must be private, friends, unlisted or public, beside an uploadedVersion")
            for problem in self.adapter.check(self, name, item):
                raise PublishError(problem)
        names = self.config.get("externalRequiredItemNames", {})
        for item_id in self.config.get("externalRequiredItems", []):
            if not ITEM_ID.fullmatch(item_id) or item_id not in names:
                raise PublishError("External required items need a decimal ID and a name")
            ids.append(item_id)
        if len(ids) != len(set(ids)):
            raise PublishError("Duplicate Workshop item IDs")
        self.order()

    def order(self):
        """Dependencies first, then by name; a cycle cannot be published."""
        order, pending = [], dict(self.mods)
        while pending:
            ready = sorted(n for n, item in pending.items() if set(item.get("requires", [])) <= set(order))
            if not ready:
                raise PublishError("Circular dependencies between mods")
            order += ready
            for name in ready:
                del pending[name]
        return order

    def save(self):
        """Write the catalogue back, then check it."""
        from ...files import atomic_write
        atomic_write(self.catalogue_path, (json.dumps(self.config, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        self.validate()

    # ---- content ----

    def payload(self, mod):
        """{relative path: bytes} the item will hold: the project's own payload, or its content folder."""
        if self.payload_hook:
            return dict(self.payload_hook(self, mod))
        tree = read_tree(self.path("content", mod), [".git", *self.layout["exclude"]])   # version control never ships
        prefix = self.layout.get("contentPrefix")
        if prefix:
            prefix = prefix.format(mod=mod).strip("/")
            tree = {f"{prefix}/{name}": data for name, data in tree.items()}
        if self.layout.get("previewSource"):
            source = self.path("previewSource", mod)
            if source.is_file():
                tree[self.preview(mod)] = source.read_bytes()
        return tree

    def preview(self, mod=None):
        """The cover's path in the item; {mod} is the mod's catalogue name (Kenshi's _<mod>.img)."""
        return (self.layout["preview"] or self.adapter.preview).format(mod=mod or "")

    # ---- Git ----

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root)

    def commit(self):
        return self.git("rev-parse", "HEAD").decode().strip()

    def dirty(self):
        """Uncommitted changes outside the catalogue and the dirtyExempt folders. Every upload writes its own record
        to the catalogue, and the uploader checks it against the candidate, so that change never blocks one."""
        exempt = tuple(self.layout["dirtyExempt"])
        catalogue = self.rel(self.catalogue_path)
        entries = self.git("status", "--porcelain", "-z").decode("utf-8").split("\0")
        return any(e and e[3:] != catalogue and not e[3:].startswith(exempt) for e in entries)
