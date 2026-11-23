"""settings: the central settings file as a layer between a repository's own file and a default, the list of settings with where
each value comes from, and setting one centrally. Every file is written by hand in temporary folders."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import kit_settings, paths, settings_cli


def central(tmp, values):
    path = Path(tmp) / "settings.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return support.isolated_environ(tmp)


class LayerTests(unittest.TestCase):
    def test_argument_then_environment_then_repository_then_central_then_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = central(tmp, {"historyPath": "C:/central"})
            own = Path(tmp) / "own.json"
            own.write_text(json.dumps({"historyPath": "C:/own"}), encoding="utf-8")
            key, var = "historyPath", "PHOBOS_TEST_ONLY"
            self.assertEqual(paths.where(key, var, "C:/arg", {**env, var: "C:/env"}, own), ("argument", "C:/arg"))
            self.assertEqual(paths.where(key, var, None, {**env, var: "C:/env"}, own), ("environment", "C:/env"))
            self.assertEqual(paths.where(key, var, None, env, own), ("repository", "C:/own"))
            self.assertEqual(paths.where(key, var, None, env, None), ("central", "C:/central"))
            self.assertEqual(paths.resolve(key, var, Path("C:/default"), None, support.isolated_environ(Path(tmp) / "none")),
                             Path("C:/default"))

    def test_an_unreadable_central_file_is_no_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "settings.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(paths.where("historyPath", "PHOBOS_TEST_ONLY", None, support.isolated_environ(tmp), None))


class ListTests(unittest.TestCase):
    def test_each_setting_says_where_its_value_comes_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = central(tmp, {"assemblyArchivePath": str(Path(tmp))})
            # The kit's cache left to its default here, so one setting shows that layer (isolated_environ sets it since 1.103.0).
            env.pop("PHOBOS_MODKIT_CACHE", None)
            repo = Path(tmp) / "repo"
            (repo / "config").mkdir(parents=True)
            (repo / ".local").mkdir()
            (repo / ".local" / "install-settings.json").write_text(json.dumps({"artWorkPath": "K:/art"}), encoding="utf-8")
            (repo / "config" / "settings.json").write_text(json.dumps({"schemaVersion": 1, "settings": [
                {"key": "artWorkPath", "env": "PHOBOS_ART_WORK", "name": "Art", "description": "Art work files"}]}),
                encoding="utf-8")
            out = io.StringIO()
            code = settings_cli.main(["list", "--root", str(repo), "--json", "--no-redact"], environ=env, out=out)
            data = json.loads(out.getvalue())["data"]
            found = {s["key"]: s for s in data["settings"]}
            self.assertEqual(code, 0)
            self.assertEqual((found["assemblyArchivePath"]["layer"], found["assemblyArchivePath"]["exists"]), ("central", True))
            self.assertEqual(found["historyPath"]["layer"], "environment")
            self.assertEqual((found["artWorkPath"]["layer"], found["artWorkPath"]["repository"], found["artWorkPath"]["declaredBy"]),
                             ("repository", "repo", "repo"))
            self.assertEqual(found["modkitCachePath"]["layer"], "default")
            self.assertTrue(data["centralExists"])
            self.assertEqual((found["historyPath"]["name"], found["artWorkPath"]["name"]),
                             ("Record of what happened on this PC", "Art"))

    def test_every_kit_setting_has_a_few_words_to_list_it_by(self):
        known = kit_settings._known()
        self.assertEqual({s.key for s in known} - set(kit_settings.NAMES), set())
        self.assertEqual(set(kit_settings.NAMES) - {s.key for s in known}, set())
        self.assertTrue(all(0 < len(name) <= 40 for name in kit_settings.NAMES.values()))

    def test_a_malformed_repository_declaration_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config").mkdir()
            (Path(tmp) / "config" / "settings.json").write_text(json.dumps({"settings": [{"key": "x", "kind": "colour"}]}),
                                                                 encoding="utf-8")
            with self.assertRaises(kit_settings.SettingsError):
                kit_settings.declared(tmp)


class SetTests(unittest.TestCase):
    def test_set_and_clear_write_only_the_central_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = support.isolated_environ(tmp)
            out = io.StringIO()
            target = str(Path(tmp) / "history")
            self.assertEqual(settings_cli.main(["set", "--key", "historyPath", "--value", target, "--json"], environ=env, out=out), 0)
            self.assertEqual(json.loads((Path(tmp) / "settings.json").read_text(encoding="utf-8")), {"historyPath": target})
            settings_cli.main(["set", "--key", "historyPath", "--clear", "--json"], environ=env, out=io.StringIO())
            self.assertEqual(json.loads((Path(tmp) / "settings.json").read_text(encoding="utf-8")), {})

    def test_an_unknown_key_or_a_relative_path_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = support.isolated_environ(tmp)
            for argv in (["--key", "nothing", "--value", str(tmp)], ["--key", "historyPath", "--value", "relative/folder"]):
                out = io.StringIO()
                code = settings_cli.main(["set", *argv, "--json"], environ=env, out=out)
                self.assertEqual((code, json.loads(out.getvalue())["data"]["ok"]), (1, False))
            self.assertFalse((Path(tmp) / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
