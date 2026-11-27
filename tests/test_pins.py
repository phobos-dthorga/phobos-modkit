"""pins: which version of the kit each repository pins, and what moving the pin would bring (1.38.0)."""
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import pins

FIRST_LOG = """# Kit changelog

## [Unreleased]

## [1.0.0] - 2026-11-01

### Added

- **Lamps.** They shine.
"""

SECOND_LOG = """# Kit changelog

## [Unreleased]

- **Not yet.** Still being written.

## [1.1.0] - 2026-11-02

### Added

- **Brighter lamps.** They shine brighter.
- **Dimmer.** A switch.

## [1.0.0] - 2026-11-01

### Added

- **Lamps.** They shine.
"""


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def new_repository(path):
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "core.fsmonitor", "false")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PinsTests(unittest.TestCase):
    def test_a_pin_names_its_version_and_the_versions_it_lacks(self):
        # TemporaryDirectory clears git's read-only object files itself.
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp) / "kit"
            new_repository(kit)
            write(kit / pins.VERSION_FILE, '__version__ = "1.0.0"\n')
            write(kit / "CHANGELOG.md", FIRST_LOG)
            git(kit, "add", "-A")
            git(kit, "commit", "-q", "-m", "1.0.0")
            first = git(kit, "rev-parse", "HEAD")
            write(kit / pins.VERSION_FILE, '__version__ = "1.1.0"\n')
            write(kit / "CHANGELOG.md", SECOND_LOG)
            git(kit, "commit", "-q", "-am", "1.1.0")

            game = Path(tmp) / "game"
            new_repository(game)
            write(game / ".gitmodules", '[submodule "external/kit"]\n\tpath = external/kit\n\turl = https://example.com/kit.git\n'
                                        '[submodule "external/other"]\n\tpath = external/other\n\turl = https://example.com/o.git\n')
            git(game, "add", ".gitmodules")
            git(game, "update-index", "--add", "--cacheinfo", f"160000,{first},external/kit")
            git(game, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},external/other")
            git(game, "commit", "-q", "-m", "pin the kit")

            found = pins.status([game], kit_root=kit, kit_version="1.1.0")
            self.assertEqual(len(found), 1)
            pin = found[0]
            self.assertEqual((pin["repository"], pin["path"], pin["version"], pin["behind"], pin["ahead"]),
                             ("game", "external/kit", "1.0.0", 1, False))
            self.assertEqual(pin["versions"], [{"version": "1.1.0", "heading": "2026-11-02",
                                                "entries": ["Brighter lamps.", "Dimmer."]}])

            # The version it pins (1.137.0): from the commit while nothing is checked out; then from its checkout, which a kit
            # older than the pin can read though it does not know the pinned commit.
            self.assertEqual("1.0.0", pins.repository_kit(game, kit_root=kit))
            write(game / "external/kit" / pins.VERSION_FILE, '__version__ = "1.2.0"\n')
            write(game / "external/kit/python/phobos_modkit/pins.py", "")
            self.assertEqual("1.2.0", pins.repository_kit(game, kit_root=kit))

    def test_a_repository_that_pins_no_kit_has_no_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain"
            new_repository(plain)
            self.assertIsNone(pins.repository_kit(plain))


if __name__ == "__main__":
    unittest.main()
