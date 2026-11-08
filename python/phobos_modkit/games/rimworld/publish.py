"""RimWorld's side of Workshop publishing: a mod's title and version, its cover, and its Workshop ID file.

Format facts, in our words:

- A mod's About/About.xml names it in <name> and gives its version in <modVersion> (a field RimWorld added in 1.4).
- Its cover is About/Preview.png.
- The game's own uploader writes the item's ID into About/PublishedFileId.txt beside About.xml, as decimal text. A
  folder with that file is the same Workshop item, so the catalogue and the file must agree; when the uploader
  here records a new item, it writes the file too.
- SteamCMD's upload file sets no tags. RimWorld's own uploader tags an item "Mod" and with each supported version;
  a SteamCMD upload leaves those to be set another way. Source: a Ludeon forum report
  (https://ludeon.com/forums/index.php?msg=337218); not checked against Valve's documentation.
"""
from __future__ import annotations

from ...files import atomic_write, inside
from ...steam.publish.project import Adapter, ModInfo, PublishError
from .mods import APP_ID, _about_root, _text

ID_FILE = "About/PublishedFileId.txt"


class RimWorld(Adapter):
    name = "rimworld"
    app_id = APP_ID
    metadata = "About/About.xml"
    preview = "About/Preview.png"

    def read(self, folder):
        root = _about_root(folder)
        if root is None:
            raise PublishError(f"No readable About/About.xml in {folder}")
        return ModInfo(_text(root, "name"), _text(root, "modVersion"))

    def check(self, project, mod, item):
        path = inside(project.root, project.path("mod", mod) / ID_FILE)
        if not path.is_file():
            return []
        found = path.read_text(encoding="utf-8-sig").strip()
        if found != (item.get("itemId") or ""):
            return [f"{mod}: {project.rel(path)} says {found} but the catalogue says {item.get('itemId')}; the game's "
                    "own uploader may have made this item. Make them agree before preparing an upload."]
        return []

    def item_recorded(self, project, mod, item_id):
        path = inside(project.root, project.path("mod", mod) / ID_FILE)
        if path.is_file() and path.read_text(encoding="utf-8-sig").strip() == item_id:
            return []
        atomic_write(path, item_id.encode("ascii"))
        return [project.rel(path)]

    def after_upload(self, project, mod):
        return ["RimWorld: SteamCMD sets no tags, so check that the item shows its Mod and game-version tags "
                "(such as 1.7); players and mod managers filter by them. The game's own uploader sets them. "
                "(Ludeon forum report; not checked against Valve's documentation.)"]
