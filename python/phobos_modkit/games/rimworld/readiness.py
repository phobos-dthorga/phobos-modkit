"""Which active mods are ready for a game version, and which would be likeliest to break if they are not.

Per mod: the versions its About.xml declares, its Steam version tags, its Harmony transpilers (they rewrite the game's own
instructions, so they depend most closely on them), and a byte scan of its assemblies for Prepatcher and of its folder for Unity
asset bundles. A byte scan finds a name; it does not prove a mod uses it. All of this is the author's statement or a mod's shape,
not a test of whether it works.
"""
from __future__ import annotations

import mmap
import os
from pathlib import Path

from .mods import _about_root

SNAPSHOT_FORMAT = 1
PREPATCHER_MARK = b"Prepatcher"
BUNDLE_FOLDER = "assetbundles"
BUNDLE_SUFFIX = ".bundle"


def declared_versions(folder):
    """The versions a mod's About.xml lists under supportedVersions, in its order."""
    about = _about_root(Path(folder))
    versions = about.find("supportedVersions") if about is not None else None
    return [li.text.strip() for li in (versions if versions is not None else []) if li.text and li.text.strip()]


def mentions_prepatcher(dlls):
    """Whether any of the assemblies holds the name, read as bytes and never loaded."""
    for dll in dlls:
        try:
            with open(dll, "rb") as file:
                if os.fstat(file.fileno()).st_size == 0:
                    continue
                with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
                    if data.find(PREPATCHER_MARK) >= 0:
                        return True
        except OSError:
            continue
    return False


def has_asset_bundles(folder):
    """Whether the mod's folder holds an AssetBundles folder with a file in it, or a file ending .bundle."""
    for current, _, files in os.walk(folder):
        if files and Path(current).name.lower() == BUNDLE_FOLDER:
            return True
        if any(name.lower().endswith(BUNDLE_SUFFIX) for name in files):
            return True
    return False


def assess(active, assemblies, transpilers, steam_tags, target):
    """One row per active mod that is not the game's own, in load order. assemblies: package ID -> DLL paths; transpilers:
    package ID -> count; steam_tags: Workshop ID -> version list, for the mods the cache knows."""
    rows = []
    for entry in active:
        mod = entry.mod
        if mod is None or mod.source == "Ludeon":
            continue
        about = declared_versions(mod.folder)
        steam = steam_tags.get(mod.workshop_id, []) if mod.workshop_id else []
        rows.append({
            "position": entry.position, "name": mod.name, "package_id": mod.package_id, "about": about, "steam": steam,
            "declares": target in about or target in steam, "transpilers": transpilers.get(mod.package_id, 0),
            "prepatcher": mentions_prepatcher(assemblies.get(mod.package_id, [])), "bundles": has_asset_bundles(mod.folder),
        })
    return rows


def risk(row):
    """How much of a mod depends on the game's insides: transpilers count for most, then Prepatcher and asset bundles."""
    return row["transpilers"] * 3 + (5 if row["prepatcher"] else 0) + (2 if row["bundles"] else 0)


def riskiest(rows):
    return sorted(rows, key=lambda r: (-risk(r), r["position"]))


def snapshot(rows, target):
    return {"schemaVersion": SNAPSHOT_FORMAT, "target": target,
            "mods": {r["package_id"]: {k: r[k] for k in ("name", "declares", "transpilers", "prepatcher", "bundles")} for r in rows}}


def changes(before, after):
    """[(mod, what changed)] between two snapshots, sorted."""
    was, now = before.get("mods", {}), after["mods"]
    found = []
    for package in sorted(now.keys() | was.keys()):
        old, new = was.get(package), now.get(package)
        if old is None:
            found.append((new["name"], "newly active"))
        elif new is None:
            found.append((old["name"], "no longer active"))
        else:
            if old["declares"] != new["declares"]:
                found.append((new["name"], "now declares the version" if new["declares"] else "no longer declares the version"))
            if old["transpilers"] != new["transpilers"]:
                found.append((new["name"], f"transpilers {old['transpilers']} to {new['transpilers']}"))
            for key, label in (("prepatcher", "Prepatcher"), ("bundles", "asset bundles")):
                if old[key] != new[key]:
                    found.append((new["name"], f"{label} {'added' if new[key] else 'gone'}"))
    return sorted(found)
