"""The Python package, the Rust workspace and Cargo.lock must name one version, or --locked builds refuse to start."""
import re
import unittest

from support import ROOT
from phobos_modkit import __version__


class OneVersion(unittest.TestCase):
    def test_package_workspace_and_lock_agree(self):
        workspace = re.search(r'\[workspace\.package\]\s*\nversion = "([^"]+)"',
                              (ROOT / "Cargo.toml").read_text(encoding="utf-8")).group(1)
        locked = re.search(r'name = "xml-index"\nversion = "([^"]+)"',
                           (ROOT / "Cargo.lock").read_text(encoding="utf-8")).group(1)
        self.assertEqual((__version__, workspace, locked), (__version__, __version__, __version__))


if __name__ == "__main__":
    unittest.main()
