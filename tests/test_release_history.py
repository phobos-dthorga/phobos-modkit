"""The history screen on a made-up repository. The fake key and path are assembled at run time, so this file does not
match its own patterns."""
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401
from phobos_modkit.release.cli import main
from phobos_modkit.release.history import screen

FAKE_KEY = "AK" + "IA" + "EXAMPLEEXAMPLE12"
FAKE_PATH = "C:" + "/Users/" + "someone/Documents/notes.txt"


def git(root, *args):
    subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True)


class History(unittest.TestCase):
    def test_findings_name_paths_never_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "clean.md").write_text("Nothing here.\n", encoding="utf-8")
            (root / "config.txt").write_text(f"key = {FAKE_KEY}\n", encoding="utf-8")
            (root / "notes.md").write_text(f"See {FAKE_PATH}\n", encoding="utf-8")
            (root / "Example.dll").write_bytes(b"MZ\0\0")
            # Forced, so a global ignore list (many ignore *.dll) cannot keep a file out of the history.
            git(root, "add", "-f", "clean.md", "config.txt", "notes.md", "Example.dll")
            git(root, "commit", "-q", "-m", "one")
            (root / "config.txt").write_text("key removed\n", encoding="utf-8")
            git(root, "commit", "-q", "-am", "two")
            findings, blobs = screen(root)
            self.assertEqual(blobs, 5)
            self.assertEqual([(c, p) for c, p, _ in findings], [("credential-pattern", "config.txt"),
                                                                 ("personal-machine-path", "notes.md"),
                                                                 ("refused-file-type", "Example.dll")])
            out = io.StringIO()
            self.assertEqual(main(["history", "--root", str(root)], out=out), 1)
            self.assertNotIn(FAKE_KEY, out.getvalue())
            self.assertIn("3 findings", out.getvalue())


if __name__ == "__main__":
    unittest.main()
