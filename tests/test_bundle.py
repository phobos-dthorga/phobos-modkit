"""bundle: a script and the kit modules it imports as one file that runs with Python alone, the same bytes every time.

The scripts and the small made-up kits here are written in a temporary folder; the bundled file is run in its own process,
isolated (-I) and from another folder, so only what it carries can be imported.
"""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the import path)
from phobos_modkit import __version__
from phobos_modkit import bundle as bundling
from phobos_modkit.bundle_cli import main

SCRIPT = '''"""A tool for people without the kit."""
from __future__ import annotations

import sys

from phobos_modkit import __version__
from phobos_modkit.games.rimworld.loading import version_key
from phobos_modkit.games.rimworld.xml_patches import xpath_targets


def main():
    print(__version__, version_key('1.10'), xpath_targets(None, 'Other/Thing'), sys.modules['phobos_modkit.dotnet_metadata'].__name__)


if __name__ == '__main__':
    main()
'''


class Folder(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, relative, content):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def fake_kit(self, modules):
        """A made-up kit of these {relative path: source} modules; returns its package folder."""
        self.write("kit/phobos_modkit/__init__.py", "__version__ = '9.9.9'\n")
        for relative, source in modules.items():
            self.write(f"kit/phobos_modkit/{relative}", source)
        return self.folder / "kit" / "phobos_modkit"


class Bundling(Folder):
    def test_the_bundled_script_runs_alone_and_gives_the_same_bytes_each_time(self):
        script = self.write("tool.py", SCRIPT)
        made = bundling.bundle(script, python=(3, 9))
        self.assertEqual([name for name, _ in made.modules], [
            "phobos_modkit.games.rimworld.loading", "phobos_modkit.dotnet_metadata", "phobos_modkit.games.rimworld.mod_xml",
            "phobos_modkit.games.rimworld.xml_patches"], "each module after the ones it imports")
        self.assertEqual(bundling.bundle(script, python=(3, 9)).text, made.text)
        self.assertTrue(made.text.startswith('"""A tool for people without the kit."""\nfrom __future__ import annotations\n\n# ---'))
        self.assertNotIn(str(self.folder), made.text)
        out = self.write("elsewhere/tool.py", made.text)
        run = subprocess.run([sys.executable, "-I", str(out)], cwd=str(self.folder / "elsewhere"), capture_output=True, text=True)
        self.assertEqual(run.stderr, "")
        self.assertEqual(run.stdout, f"{__version__} (1, 10) None phobos_modkit.dotnet_metadata\n")

    def test_what_a_bundle_cannot_carry_is_refused(self):
        kit = self.fake_kit({"a.py": "import json\nfrom . import b\n", "b.py": "import requests\n", "c.py": "x = 1\n",
                             "games/__init__.py": "THING = 1\n", "loop1.py": "from . import loop2\n",
                             "loop2.py": "from .loop1 import x\n", "new.py": "match 1:\n    case _:\n        pass\n"})
        cases = {"from phobos_modkit import a\n": "imports requests, which is not in the standard library",
                 "from phobos_modkit.games import THING\n": "takes THING from the package phobos_modkit.games",
                 "import phobos_modkit.missing\n": "the kit has no module phobos_modkit.missing",
                 "from phobos_modkit import loop1\n": "import one another in a loop",
                 "from phobos_modkit import new\n": "not valid Python 3.9",
                 "import json\n": "imports nothing from phobos_modkit"}
        for source, refusal in cases.items():
            with self.subTest(source=source):
                script = self.write("tool.py", source)
                with self.assertRaises(bundling.BundleError) as raised:
                    bundling.bundle(script, python=(3, 9), kit_root=kit, version="9.9.9")
                self.assertIn(refusal, str(raised.exception))
        made = bundling.bundle(self.write("tool.py", "from phobos_modkit import c, __version__\n"), kit_root=kit, version="9.9.9")
        self.assertEqual(made.modules, [("phobos_modkit.c", 1)])

    def test_a_module_a_raw_string_cannot_hold_is_written_escaped(self):
        kit = self.fake_kit({"quotes.py": "Q = '''three'''\nBACK = '\\\\'\n"})
        script = self.write("tool.py", "from phobos_modkit.quotes import Q, BACK\nprint(Q, BACK)\n")
        made = bundling.bundle(script, kit_root=kit, version="9.9.9")
        out = self.write("elsewhere/tool.py", made.text)
        run = subprocess.run([sys.executable, "-I", str(out)], cwd=str(self.folder / "elsewhere"), capture_output=True, text=True)
        self.assertEqual(run.stdout, "three \\\n")


class Command(Folder):
    def run_main(self, *argv):
        out = io.StringIO()
        return main(list(argv), out=out), out.getvalue()

    def test_out_writes_check_compares(self):
        script = self.write("tool.py", SCRIPT)
        target = self.folder / "dist" / "tool.py"
        code, text = self.run_main(str(script), "--check", str(target))
        self.assertEqual(code, 1)
        self.assertIn("missing", text)
        code, text = self.run_main(str(script), "--out", str(target), "--python", "3.9")
        self.assertEqual(code, 0)
        self.assertIn("written", text)
        code, text = self.run_main(str(script), "--check", str(target), "--python", "3.9", "--json")
        self.assertEqual(code, 0)
        data = json.loads(text)["data"]
        self.assertEqual((data["state"], data["python"], len(data["modules"])), ("up to date", "3.9", 4))
        target.write_text(target.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
        code, text = self.run_main(str(script), "--check", str(target), "--python", "3.9")
        self.assertEqual(code, 1)
        self.assertIn("out of date", text)

    def test_a_refusal_and_usage(self):
        script = self.write("tool.py", "import json\n")
        code, text = self.run_main(str(script), "--out", str(self.folder / "x.py"))
        self.assertEqual(code, 1)
        self.assertIn("cannot be bundled", text)
        self.assertFalse((self.folder / "x.py").exists())
        self.assertEqual(self.run_main(str(script))[0], 2)
        self.assertEqual(self.run_main(str(script), "--out", "a", "--python", "three")[0], 1)


if __name__ == "__main__":
    unittest.main()
