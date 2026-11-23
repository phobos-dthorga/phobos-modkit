"""The names other repositories may import (docs/library-api.md) still exist, and the doc lists each of them.

Removing or changing one of these raises the major version: this test is the reminder.
"""
from importlib import import_module
import inspect
from pathlib import Path
import unittest

import support  # noqa: F401  (puts the package on the import path)

DOC = Path(__file__).resolve().parents[1] / "docs" / "library-api.md"

# Each command module's main, with the keyword arguments consumers pass to it.
ENTRY_POINTS = {
    "artaudit_cli": ("out",),
    "changes_cli": ("out",),
    "cleanup_cli": (),
    "code.cli": ("settings_file", "out"),
    "crashdump_cli": ("out",),
    "doc_tables": ("out",),
    "gate.cli": (),
    "history_cli": ("out",),
    "installs_cli": ("out",),
    "release.cli": (),
    "safe_copies": ("out",),
    "settings_cli": ("out",),
    "steam.publish.cli": ("root",),
    "testpass_cli": ("out",),
    "windows_dumps": ("out",),
    "games.rimworld.archive_cli": ("settings_file", "out"),
    "games.rimworld.cli": ("settings_file", "out"),
    "games.rimworld.defs_cli": ("settings_file", "out"),
    "games.rimworld.patches_cli": ("settings_file", "out"),
    "games.rimworld.perf_cli": ("settings_file", "out"),
    "games.rimworld.readiness_cli": ("settings_file", "out"),
    "games.rimworld.save_cli": ("settings_file", "out"),
    "games.rimworld.settings_cli": ("settings_file", "out"),
    "games.rimworld.sources_cli": ("settings_file", "out"),
    "games.rimworld.startup_cli": ("settings_file", "out"),
    "games.rimworld.targets_cli": ("settings_file", "out"),
    "games.rimworld.textures_cli": ("out",),
    "games.rimworld.update_check_cli": ("settings_file", "out"),
    "games.rimworld.upstream_cli": ("settings_file", "out"),
    "games.rimworld.workshop_cli": ("settings_file", "out", "post", "pacer", "clock"),
}

STABLE = {
    "paths": ("resolve", "central_settings_file", "read_settings_file"),
    "cache": ("folder",),
    "progress": ("Progress",),
    "build_lock": ("held", "BuildBusy"),
    "installs": ("load_config", "record_for", "write_record", "place", "tidy", "tidy_lines"),
    "games.rimworld.installs": ("identity",),
    "games.rimworld.paths": ("config_path",),
    "games.rimworld.textures": ("DEFAULT_TODDS", "RIMSORT_OPTIMIZED", "trim_folder"),
    "artaudit": ("record_home", "mirrors_of"),
    "picks": ("offer",),
}


class LibraryApiTest(unittest.TestCase):
    def test_entry_points_take_what_consumers_pass(self):
        for module, keywords in ENTRY_POINTS.items():
            with self.subTest(module=module):
                main = import_module(f"phobos_modkit.{module}").main
                parameters = inspect.signature(main).parameters
                self.assertIn("argv", parameters)
                for keyword in keywords:
                    self.assertIn(keyword, parameters, f"{module}.main no longer takes {keyword}=")

    def test_stable_names_exist(self):
        for module, names in STABLE.items():
            found = import_module(f"phobos_modkit.{module}")
            for name in names:
                with self.subTest(name=f"{module}.{name}"):
                    self.assertTrue(hasattr(found, name), f"{module}.{name} is listed as stable in docs/library-api.md")

    def test_the_doc_lists_every_stable_name(self):
        text = DOC.read_text(encoding="utf-8")
        listed = [f"{m}.main" for m in ENTRY_POINTS] + [f"{m}.{n}" for m, names in STABLE.items() for n in names]
        missing = [name for name in listed if f"`{name}`" not in text]
        self.assertEqual([], missing, "docs/library-api.md does not list these stable names")
        self.assertEqual(51, len(listed), "the doc's count of stable names")


if __name__ == "__main__":
    unittest.main()
