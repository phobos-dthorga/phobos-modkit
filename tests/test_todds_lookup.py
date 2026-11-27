"""Where todds is looked for without a setting (1.145.0): the PATH, then on its own, then RimSort's copy. Empty stand-in files only."""
from pathlib import Path
import tempfile
import unittest

from phobos_modkit.games.rimworld import programs
from phobos_modkit.games.rimworld.textures import DEFAULT_TODDS, default_todds, standalone_todds, todds_path

import support


class ToddsLookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = support.isolated_environ(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def place(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return path

    def test_todds_on_its_own_comes_before_rimsorts_and_the_path_before_both(self):
        own = self.place(standalone_todds(self.environ))
        self.assertEqual(own, Path(self.tmp.name) / "local-app-data" / "Programs" / "todds" / "todds.exe")
        self.assertEqual(default_todds(self.environ), own)
        self.assertEqual(todds_path(environ=self.environ), own)
        on_path = self.place(Path(self.tmp.name) / "bin" / "todds.exe")
        self.environ["PATH"] = str(on_path.parent)
        self.assertEqual(Path(default_todds(self.environ)).resolve(), on_path.resolve())

    def test_with_none_of_our_own_rimsorts_copy_or_where_ours_belongs(self):
        expected = DEFAULT_TODDS if DEFAULT_TODDS.is_file() else standalone_todds(self.environ)
        self.assertEqual(default_todds(self.environ), expected)
        found = programs.PROGRAMS[0].find(self.environ)
        if found.here:
            self.assertIn("RimSort's copy", found.how)
        else:
            self.assertIn(str(standalone_todds(self.environ).parent), found.how)
        self.assertIn("joseasoler/todds", programs.PROGRAMS[0].url)


if __name__ == "__main__":
    unittest.main()
