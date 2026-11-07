"""The installed-mod index, built from synthetic mod folders in a temporary directory."""
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401
from phobos_modkit.games.rimworld.mods import ModIndex, default_roots, default_workshop, read_mod
from phobos_modkit.logs.model import Entry, Evidence


def about(folder, package_id, name, about_dir="About", file_name="About.xml"):
    target = Path(folder) / about_dir
    target.mkdir(parents=True, exist_ok=True)
    (target / file_name).write_text(f"<ModMetaData><name>{name}</name><packageId>{package_id}</packageId>"
                                    f"</ModMetaData>", encoding="utf-8")


def dll(folder, *names):
    Path(folder).mkdir(parents=True, exist_ok=True)
    for name in names:
        (Path(folder) / name).write_bytes(b"")


def fake_install(root):
    game, workshop = Path(root) / "RimWorld", Path(root) / "294100"
    about(game / "Data" / "Core", "Ludeon.RimWorld", "Core")
    about(game / "Mods" / "Example Local", "example.local", "Example Local")
    dll(game / "Mods" / "Example Local" / "Assemblies", "ExampleLocal.dll")
    about(workshop / "1111111111", "example.patches", "Example Patches")
    about(workshop / "2222222222", "Example.Widgets", "Example Widgets", "about", "about.xml")
    dll(workshop / "2222222222" / "1.7" / "Assemblies", "ExampleWidgets.dll", "0Harmony.dll")
    (workshop / "3333333333" / "About").mkdir(parents=True)
    (workshop / "3333333333" / "About" / "About.xml").write_text(
        "<ModMetaData><name>Tools & More</name><packageId>example.tools</packageId></ModMetaData>", encoding="utf-8")
    dll(workshop / "3333333333" / "Mods" / "Extra" / "1.7" / "Assemblies", "ExampleTools.dll")
    (workshop / "4444444444").mkdir()  # no About.xml: skipped
    return game, workshop


class Reading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game, self.workshop = fake_install(self.tmp.name)
        self.index = ModIndex.scan(default_roots(self.game, self.workshop))

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_mod_with_an_about_file_is_read(self):
        self.assertEqual(sorted(m.package_id for m in self.index.mods),
                         ["example.local", "example.patches", "example.tools", "example.widgets", "ludeon.rimworld"])

    def test_bare_ampersands_and_lower_case_folders_are_forgiven(self):
        tools = read_mod(self.workshop / "3333333333", "Workshop", "3333333333")
        self.assertEqual(tools.name, "Tools & More")
        self.assertEqual(tools.assemblies, ("exampletools",))

    def test_shared_harmony_copies_name_no_mod(self):
        widgets = read_mod(self.workshop / "2222222222", "Workshop")
        self.assertEqual(widgets.assemblies, ("examplewidgets",))

    def test_each_kind_of_clue_resolves(self):
        cases = [
            (Evidence("source", "example patches"), "Example Patches"),
            (Evidence("file", "workshop:1111111111"), "Example Patches"),
            (Evidence("file", "mods:Example Local"), "Example Local"),
            (Evidence("assembly", "ExampleWidgets.dll"), "Example Widgets"),
            (Evidence("namespace", "ExampleWidgets"), "Example Widgets"),
            (Evidence("namespace", "Widgets"), "Example Widgets"),  # the last part of the package ID
            (Evidence("caller", "ExampleTools"), "Tools & More"),
            (Evidence("patch", "EXAMPLE.WIDGETS"), "Example Widgets"),
            (Evidence("finalizer", "example.tools"), "Tools & More"),
            (Evidence("patch", "unknown.id"), ""),
            (Evidence("file", "workshop:9999999999"), ""),
        ]
        for evidence, expected in cases:
            self.assertEqual(self.index.resolve(evidence), expected, evidence)

    def test_annotate_fills_in_names(self):
        entry = Entry(1, "ERROR", "Verse", "x", evidence=[Evidence("assembly", "ExampleLocal.dll")])
        self.index.annotate([entry])
        self.assertEqual(entry.evidence[0].mod, "Example Local")

    def test_missing_folders_give_an_empty_index(self):
        self.assertEqual(ModIndex.scan(default_roots(Path(self.tmp.name) / "none", None)).mods, [])

    def test_the_workshop_sits_beside_the_game(self):
        game = Path("Steam") / "steamapps" / "common" / "RimWorld"
        self.assertEqual(default_workshop(game), Path("Steam") / "steamapps" / "workshop" / "content" / "294100")


if __name__ == "__main__":
    unittest.main()
