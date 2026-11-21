"""safe-copies: copies kept apart by kind, checked, and copied back (1.66.0). Every file here is made up in a temporary folder."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

import support
from phobos_modkit import safe_copies as sc

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

CONFIG = {
    "schemaVersion": 1, "game": "testgame",
    "sets": [
        {"name": "trainings", "root": "loraWorkPath", "units": True, "kind": "proven",
         "proof": {"marker": "dataset/own-art.json", "manifest": "manifest.json", "hashKey": "sha256",
                   "files": ["**/*.png", "**/*.jpg"]},
         "exclude": ["**/_t_e_cache", "**/_latent_cache"],
         "localOnly": ["output/**/*_0*.safetensors", "**/optimizer.pt"]},
        {"name": "models", "root": "comfyUiPath", "folder": "loras", "include": ["phobos-private-*.safetensors"],
         "kind": {"unitOf": "trainings", "pattern": "phobos-private-{unit}.safetensors"}},
        {"name": "plans", "root": "@repository", "folder": "plans", "include": ["*.json"], "kind": "own"},
    ],
    "provenance": [{"name": "base models", "file": "models.json"}],
}


def _remove(function, path, _):
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    function(path)


def _git(folder, *arguments):
    subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(folder), *arguments], check=True, capture_output=True)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="safe-copies-"))
        self.addCleanup(shutil.rmtree, self.base, onerror=_remove)
        self.repo = self.base / "repo"
        (self.repo / "config").mkdir(parents=True)
        (self.repo / "config" / "safe-copies.json").write_text(json.dumps(CONFIG), encoding="utf-8")
        (self.repo / "models.json").write_text("[]", encoding="utf-8")
        (self.repo / "plans").mkdir()
        (self.repo / "plans" / "night-1.json").write_text('[{"train": "x"}]', encoding="utf-8")
        (self.repo / "plans" / "picture.png").write_bytes(b"not taken: plans takes json only")
        self.work, self.comfy = self.base / "work", self.base / "comfy"
        self._training("ours", own=True)
        self._training("vanilla", own=False)
        (self.comfy / "loras").mkdir(parents=True)
        for name in ("ours", "vanilla", "stranger"):
            (self.comfy / "loras" / f"phobos-private-{name}.safetensors").write_bytes(f"model {name}".encode())
        (self.comfy / "loras" / "someone-elses.safetensors").write_bytes(b"not ours, not taken")
        (self.repo / ".local").mkdir()
        (self.repo / ".local" / "install-settings.json").write_text(json.dumps(
            {"loraWorkPath": str(self.work), "comfyUiPath": str(self.comfy)}), encoding="utf-8")
        self.local = self.base / "disk" / "safe-copies"
        sc.mark(self.local, "private-local", NOW)
        self.environ = support.isolated_environ(self.base, PHOBOS_SAFE_COPIES=str(self.local))

    def _training(self, name, own):
        unit = self.work / name
        dataset = unit / "dataset"
        (dataset / "_t_e_cache").mkdir(parents=True)
        (dataset / "_t_e_cache" / "cache.bin").write_bytes(b"x" * 100)
        pictures = {f"{name}-{i}.png": f"picture {name} {i}".encode() for i in range(3)}
        for file, data in pictures.items():
            (dataset / file).write_bytes(data)
            (dataset / file.replace(".png", ".txt")).write_text(f"caption {file}", encoding="utf-8")
        if own:
            (dataset / "own-art.json").write_text('{"own_art": true}', encoding="utf-8")
            (unit / "manifest.json").write_text(json.dumps([{"image": f, "sha256": _sha(d)} for f, d in pictures.items()]),
                                                encoding="utf-8")
        output = unit / "output" / f"phobos_{name}"
        output.mkdir(parents=True)
        (output / f"phobos_{name}.safetensors").write_bytes(b"final")
        (output / f"phobos_{name}_000000100.safetensors").write_bytes(b"checkpoint")
        (output / "optimizer.pt").write_bytes(b"resume")

    def make_repository(self):
        remote = self.base / "remote.git"
        _git(self.base, "init", "-q", "--bare", str(remote))
        clone = self.base / "clone"
        _git(self.base, "clone", "-q", str(remote), str(clone))
        for key, value in (("core.fsmonitor", "false"), ("user.name", "Test"), ("user.email", "test@example.invalid")):
            _git(clone, "config", key, value)
        sc.mark(clone, "repository", NOW)
        self.environ["PHOBOS_SAFE_COPIES_REPOSITORY"] = str(clone)
        return remote, clone

    def kinds(self):
        collection = sc.collect(self.repo, self.environ)
        return {item.key: item for item in collection.items}, collection


class KindTests(Fixture):
    def test_patterns_keep_single_stars_within_a_folder(self):
        self.assertTrue(sc.matches("a.json", ["*.json"]))
        self.assertFalse(sc.matches("deep/a.json", ["*.json"]))
        self.assertTrue(sc.matches("deep/er/a.png", ["**/*.png"]))
        self.assertTrue(sc.matches("a.png", ["**/*.png"]))

    def test_the_walk_skips_folders_the_list_could_never_take_a_file_from(self):
        notes = ["projects/*/memory/**"]
        self.assertTrue(sc.could_hold("projects/a/memory/deeper", notes))
        self.assertFalse(sc.could_hold("projects/a/subagents", notes))
        self.assertFalse(sc.could_hold("debug", ["CLAUDE.md", *notes]))
        self.assertTrue(sc.could_hold("anything/at/all", ["**"]))
        self.assertTrue(sc.could_hold("output/run", ["output/**/*_0*.safetensors"]))
        self.assertFalse(sc.could_hold("picks/deeper", ["picks/*.html"]))

    def test_a_proven_training_is_ours_and_an_unproven_one_is_game_derived(self):
        items, _ = self.kinds()
        self.assertEqual(items["testgame/trainings/ours/dataset/ours-0.png"].kind, sc.OWN)
        self.assertEqual(items["testgame/trainings/vanilla/dataset/vanilla-0.png"].kind, sc.GAME_DERIVED)

    def test_one_picture_the_manifest_does_not_hold_makes_the_whole_training_game_derived(self):
        (self.work / "ours" / "dataset" / "sneaked-in.png").write_bytes(b"a game's texture")
        items, collection = self.kinds()
        self.assertEqual(items["testgame/trainings/ours/dataset/ours-0.png"].kind, sc.GAME_DERIVED)
        why = next(u.why for u in collection.units if u.unit == "ours")
        self.assertIn("sneaked-in.png", why)

    def test_a_model_follows_its_training_and_an_unknown_one_is_game_derived(self):
        items, _ = self.kinds()
        self.assertEqual(items["testgame/models/phobos-private-ours.safetensors"].kind, sc.OWN)
        self.assertEqual(items["testgame/models/phobos-private-vanilla.safetensors"].kind, sc.GAME_DERIVED)
        self.assertEqual(items["testgame/models/phobos-private-stranger.safetensors"].kind, sc.GAME_DERIVED)
        self.assertNotIn("testgame/models/someone-elses.safetensors", items)

    def test_caches_are_left_out_and_checkpoints_are_local_only(self):
        items, _ = self.kinds()
        self.assertFalse(any("_t_e_cache" in key for key in items))
        self.assertTrue(items["testgame/trainings/ours/output/phobos_ours/phobos_ours_000000100.safetensors"].local_only)
        self.assertTrue(items["testgame/trainings/ours/output/phobos_ours/optimizer.pt"].local_only)
        self.assertFalse(items["testgame/trainings/ours/output/phobos_ours/phobos_ours.safetensors"].local_only)

    def test_a_root_not_set_is_a_note_not_a_failure(self):
        (self.repo / ".local" / "install-settings.json").write_text(json.dumps({"loraWorkPath": str(self.work)}), "utf-8")
        _, collection = self.kinds()
        self.assertTrue(any("comfyUiPath is not set" in note for note in collection.notes))

    def test_a_malformed_list_is_refused_in_words(self):
        (self.repo / "config" / "safe-copies.json").write_text(json.dumps({"game": "testgame", "sets": [
            {"name": "x", "root": "@repository", "kind": "maybe"}]}), encoding="utf-8")
        with self.assertRaises(sc.SafeCopiesError):
            sc.load_config(self.repo)


class DestinationTests(Fixture):
    def test_a_synced_folder_cannot_be_marked_private(self):
        synced = self.base / "nas"
        (synced / ".SynologyWorkingDirectory").mkdir(parents=True)
        with self.assertRaises(sc.SafeCopiesError):
            sc.mark(synced / "copies", "private-local")
        self.assertTrue(sc.shared_signs(self.base / "x" / "SynologyDrive" / "copies"))

    def test_game_derived_files_go_only_to_a_private_local_folder(self):
        plain = self.base / "plain"
        sc.mark(plain, "local", NOW)
        self.environ["PHOBOS_SAFE_COPIES"] = str(plain)
        sc.run(self.repo, self.environ, now=NOW)
        self.assertTrue((plain / "testgame/trainings/ours/dataset/ours-0.png").is_file())
        self.assertFalse((plain / "testgame/trainings/vanilla").exists())
        self.environ["PHOBOS_SAFE_COPIES"] = str(self.local)
        sc.run(self.repo, self.environ, now=NOW)
        self.assertTrue((self.local / "testgame/trainings/vanilla/dataset/vanilla-0.png").is_file())

    def test_a_mark_made_before_a_sync_tool_arrived_no_longer_counts(self):
        (self.local / ".SynologyWorkingDirectory").mkdir()
        local = next(d for d in sc.destinations(self.environ) if d.name == "local")
        self.assertFalse(local.private_local)
        item = sc.Item("g", "s", None, "a", Path("a"), 1, 1, sc.GAME_DERIVED, False)
        self.assertIsNotNone(sc.refusal(local, item))

    def test_an_unmarked_folder_is_not_ready(self):
        self.environ["PHOBOS_SAFE_COPIES"] = str(self.base)
        local = next(d for d in sc.destinations(self.environ) if d.name == "local")
        self.assertIn("not marked", local.problem)
        with self.assertRaises(sc.SafeCopiesError):
            sc.run(self.repo, self.environ, now=NOW)


class PersonalTests(Fixture):
    """1.67.0: notes about the owner and a game's settings stay on a private, local folder, as game-derived files do."""

    def setUp(self):
        super().setUp()
        home = self.base / "home"
        (home / ".claude" / "projects" / "some-project" / "memory").mkdir(parents=True)
        (home / ".claude" / "projects" / "some-project" / "memory" / "MEMORY.md").write_text("- a note", encoding="utf-8")
        (home / ".claude" / "projects" / "some-project" / "transcript.jsonl").write_text("{}", encoding="utf-8")
        (home / ".claude" / "CLAUDE.md").write_text("# the owner's rules", encoding="utf-8")
        config = json.loads((self.repo / "config" / "safe-copies.json").read_text(encoding="utf-8"))
        config["sets"].append({"name": "notes-about-you", "root": "claudeHomePath",
                               "include": ["CLAUDE.md", "projects/*/memory/**"], "kind": "personal"})
        (self.repo / "config" / "safe-copies.json").write_text(json.dumps(config), encoding="utf-8")
        self.environ["USERPROFILE"] = str(home)

    def test_a_set_with_no_value_set_finds_its_folder_by_the_settings_default(self):
        items, _ = self.kinds()
        self.assertIn("testgame/notes-about-you/CLAUDE.md", items)
        self.assertIn("testgame/notes-about-you/projects/some-project/memory/MEMORY.md", items)
        self.assertNotIn("testgame/notes-about-you/projects/some-project/transcript.jsonl", items)
        self.assertEqual(items["testgame/notes-about-you/CLAUDE.md"].kind, sc.PERSONAL)

    def test_personal_files_go_only_to_a_private_local_folder_never_a_repository(self):
        remote, clone = self.make_repository()
        _, results = sc.run(self.repo, self.environ, now=NOW)
        self.assertTrue((self.local / "testgame/notes-about-you/CLAUDE.md").is_file())
        self.assertFalse((clone / "testgame/notes-about-you").exists())
        repository = next(r for r in results if r["destination"] == "repository")
        self.assertIn("personal: never in a repository", repository["refused"])
        plain = self.base / "plain"
        sc.mark(plain, "local", NOW)
        local = next(d for d in sc.destinations(dict(self.environ, PHOBOS_SAFE_COPIES=str(plain))) if d.name == "local")
        item = sc.Item("g", "s", None, "a", Path("a"), 1, 1, sc.PERSONAL, False)
        self.assertIn("personal", sc.refusal(local, item))


class SavesTests(Fixture):
    """1.68.0: the newest few saves of a rotation, with a set number of earlier copies of each (the owner's word, 22 Nov 2026)."""

    def setUp(self):
        super().setUp()
        self.saves = self.base / "saves"
        self.saves.mkdir()
        for number, name in enumerate(("PG15.rws", "PG16.rws", "PG17.rws", "Autosave-1.rws")):
            path = self.saves / name
            path.write_bytes(f"{name} first".encode())
            os.utime(path, ns=(10**18 + number * 10**9, 10**18 + number * 10**9))
        settings = json.loads((self.repo / ".local" / "install-settings.json").read_text(encoding="utf-8"))
        settings["savesPath"] = str(self.saves)
        (self.repo / ".local" / "install-settings.json").write_text(json.dumps(settings), encoding="utf-8")
        config = json.loads((self.repo / "config" / "safe-copies.json").read_text(encoding="utf-8"))
        config["sets"].append({"name": "saves", "root": "savesPath", "include": ["*.rws"], "exclude": ["Autosave-*"],
                               "newest": 2, "keepEarlier": 2, "kind": "personal"})
        (self.repo / "config" / "safe-copies.json").write_text(json.dumps(config), encoding="utf-8")
        self.tick = 10**18 + 100 * 10**9

    def save_again(self, name):
        self.tick += 10**9
        path = self.saves / name
        path.write_bytes(f"{name} at {self.tick}".encode())
        os.utime(path, ns=(self.tick, self.tick))

    def saved(self):
        items, _ = self.kinds()
        return sorted(k.split("/")[-1] for k in items if k.startswith("testgame/saves/"))

    def test_only_the_newest_two_saves_and_never_an_autosave(self):
        self.assertEqual(self.saved(), ["PG16.rws", "PG17.rws"])
        self.save_again("PG15.rws")
        self.assertEqual(self.saved(), ["PG15.rws", "PG17.rws"])

    def test_each_save_keeps_two_earlier_copies_and_lets_the_oldest_go(self):
        let_go = []
        for moment in range(4):
            self.save_again("PG17.rws")
            _, results = sc.run(self.repo, self.environ, now=datetime(2026, 11, 22, 1, moment, tzinfo=timezone.utc))
            let_go += results[0]["letGo"]
        earlier = sorted((self.local / sc.BOOK / "earlier").rglob("PG17.rws"))
        self.assertEqual(len(earlier), 2)
        self.assertEqual(len(let_go), 1)
        self.assertTrue((self.local / "testgame/saves/PG17.rws").is_file())
        self.assertTrue((self.saves / "PG17.rws").is_file())
        # Other sets keep every earlier copy, as before.
        self.assertTrue(all("saves" in path for path in let_go))

    def test_a_save_that_falls_out_of_the_newest_keeps_its_copy_and_is_never_called_gone(self):
        sc.run(self.repo, self.environ, now=NOW)
        self.save_again("PG15.rws")
        _, results = sc.run(self.repo, self.environ, now=LATER)
        self.assertEqual(results[0]["gone"], 0)
        self.assertTrue((self.local / "testgame/saves/PG16.rws").is_file())

    def test_a_save_that_left_the_rotation_is_listed_and_let_go_only_on_request(self):
        sc.run(self.repo, self.environ, now=NOW)
        self.save_again("PG15.rws")
        sc.run(self.repo, self.environ, now=LATER)
        collection = sc.collect(self.repo, self.environ)
        local = next(d for d in sc.destinations(self.environ) if d.name == "local")
        kept = sc.kept_only(collection, local)
        self.assertEqual([(e["key"], e["why"]) for e in kept], [("testgame/saves/PG16.rws", "no longer among the newest 2")])
        preview = sc.let_go(self.repo, ["testgame/saves/PG16.rws"], self.environ)
        self.assertFalse(preview["applied"])
        self.assertTrue((self.local / "testgame/saves/PG16.rws").is_file())
        with self.assertRaises(sc.SafeCopiesError):
            sc.let_go(self.repo, ["testgame/saves/PG17.rws"], self.environ, apply=True)   # still in the rotation
        done = sc.let_go(self.repo, ["testgame/saves/PG16.rws"], self.environ, apply=True)
        self.assertEqual(done["letGo"], ["testgame/saves/PG16.rws"])
        self.assertFalse((self.local / "testgame/saves/PG16.rws").exists())
        self.assertTrue((self.saves / "PG16.rws").is_file(), "the save itself is never touched")
        self.assertNotIn("testgame/saves/PG16.rws", sc.read_state(self.local))
        self.assertEqual(sc.verify(self.environ)[0]["problems"], [])

    def test_a_number_that_is_not_a_whole_number_is_refused(self):
        config = json.loads((self.repo / "config" / "safe-copies.json").read_text(encoding="utf-8"))
        config["sets"][-1]["keepEarlier"] = 0
        (self.repo / "config" / "safe-copies.json").write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaises(sc.SafeCopiesError):
            sc.load_config(self.repo)


class RunTests(Fixture):
    def test_an_unchanged_file_is_not_copied_twice_and_a_changed_one_keeps_its_earlier_copy(self):
        _, first = sc.run(self.repo, self.environ, now=NOW)
        self.assertGreater(len(first[0]["copied"]), 10)
        _, second = sc.run(self.repo, self.environ, now=NOW)
        self.assertEqual(second[0]["copied"], [])
        caption = self.work / "ours" / "dataset" / "ours-0.txt"
        caption.write_text("a better caption, edited by hand", encoding="utf-8")
        _, third = sc.run(self.repo, self.environ, now=LATER)
        self.assertEqual([c["path"] for c in third[0]["copied"]], ["testgame/trainings/ours/dataset/ours-0.txt"])
        earlier = list((self.local / sc.BOOK / "earlier").rglob("ours-0.txt"))
        self.assertEqual(earlier[0].read_text(encoding="utf-8"), "caption ours-0.png")

    def test_nothing_at_the_source_is_ever_deleted_and_a_gone_file_keeps_its_copy(self):
        sc.run(self.repo, self.environ, now=NOW)
        (self.repo / "plans" / "night-1.json").unlink()
        _, results = sc.run(self.repo, self.environ, now=LATER)
        self.assertEqual(results[0]["gone"], 1)
        self.assertTrue((self.local / "testgame/plans/night-1.json").is_file())
        self.assertTrue((self.work / "ours" / "dataset" / "ours-0.png").is_file())

    def test_a_missing_root_does_not_mark_its_copies_gone(self):
        sc.run(self.repo, self.environ, now=NOW)
        (self.repo / ".local" / "install-settings.json").write_text(json.dumps({"loraWorkPath": str(self.work)}), "utf-8")
        _, results = sc.run(self.repo, self.environ, now=LATER)
        self.assertEqual(results[0]["gone"], 0)

    def test_each_run_writes_its_record_and_the_history_log(self):
        _, results = sc.run(self.repo, self.environ, now=NOW)
        record = json.loads(Path(results[0]["record"]).read_text(encoding="utf-8"))
        self.assertEqual(record["provenance"]["base models"], _sha(b"[]"))
        log = Path(self.environ["PHOBOS_HISTORY"]) / "testgame.jsonl"
        self.assertIn('"kind": "safe-copies"', log.read_text(encoding="utf-8"))

    def test_verify_finds_a_damaged_copy(self):
        sc.run(self.repo, self.environ, now=NOW)
        self.assertEqual(sc.verify(self.environ)[0]["problems"], [])
        copy = self.local / "testgame/trainings/ours/dataset/ours-1.png"
        copy.write_bytes(b"pictur3 ours 1")
        problems = sc.verify(self.environ)[0]["problems"]
        self.assertEqual([p["path"] for p in problems], ["testgame/trainings/ours/dataset/ours-1.png"])


class RepositoryTests(Fixture):
    def test_the_repository_takes_our_own_final_files_and_pushes_them(self):
        remote, clone = self.make_repository()
        _, results = sc.run(self.repo, self.environ, now=NOW)
        repository = next(r for r in results if r["destination"] == "repository")
        self.assertTrue(repository["git"]["committed"])
        self.assertTrue(repository["git"]["pushed"])
        held = subprocess.run(["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.split()
        self.assertIn("testgame/trainings/ours/dataset/ours-0.png", held)
        self.assertIn("testgame/models/phobos-private-ours.safetensors", held)
        self.assertIn("testgame/trainings/ours/output/phobos_ours/phobos_ours.safetensors", held)
        self.assertFalse(any("vanilla" in path or "stranger" in path for path in held), held)
        self.assertFalse(any("_000000100" in path or "optimizer.pt" in path for path in held), held)
        self.assertNotIn(f"{sc.BOOK}/lock", held)
        self.assertIn(f"{sc.BOOK}/state.json", held)

    def test_commits_not_sent_yet_stay_counted_until_a_run_sends_them(self):
        _, clone = self.make_repository()
        sc.run(self.repo, self.environ, now=NOW, push=False)
        self.assertGreater(sc.unsent(clone), 0)
        sc.run(self.repo, self.environ, now=LATER)
        self.assertEqual(sc.unsent(clone), 0)

    def test_a_second_run_with_nothing_new_makes_no_commit(self):
        self.make_repository()
        sc.run(self.repo, self.environ, now=NOW)
        _, results = sc.run(self.repo, self.environ, now=LATER)
        git = next(r for r in results if r["destination"] == "repository")["git"]
        self.assertFalse(git["committed"])
        self.assertFalse(git["pushed"])

    def test_a_training_that_turns_out_unproven_is_flagged_if_already_in_the_repository(self):
        self.make_repository()
        sc.run(self.repo, self.environ, now=NOW)
        (self.work / "ours" / "dataset" / "sneaked-in.png").write_bytes(b"a game's texture")
        _, results = sc.run(self.repo, self.environ, now=LATER)
        warnings = next(r for r in results if r["destination"] == "repository")["warnings"]
        self.assertTrue(any("earlier run put it in the repository" in w for w in warnings))


class RestoreTests(Fixture):
    def test_restore_copies_a_training_back_and_refuses_to_write_over_a_different_file(self):
        sc.run(self.repo, self.environ, now=NOW)
        target = self.base / "restored"
        done = sc.restore("testgame", "trainings", target, unit="ours", environ=self.environ)
        self.assertGreater(done["restored"], 5)
        self.assertEqual((target / "dataset" / "ours-0.png").read_bytes(), b"picture ours 0")
        edited = target / "dataset" / "ours-0.txt"
        edited.write_text("changed after the restore", encoding="utf-8")
        with self.assertRaises(sc.SafeCopiesError):
            sc.restore("testgame", "trainings", target, unit="ours", environ=self.environ)
        with self.assertRaises(sc.SafeCopiesError):
            sc.restore("testgame", "trainings", target, unit="ours", overwrite=True, environ=self.environ)
        sc.restore("testgame", "trainings", target, unit="ours", overwrite=True, overwrite_newer=True, environ=self.environ)
        self.assertEqual(edited.read_text(encoding="utf-8"), "caption ours-0.png")

    def test_restore_brings_back_one_file_a_set_lists_on_its_own(self):
        # 1.70.1: status names an installed model by its file, and Restore passes that name as the unit.
        sc.run(self.repo, self.environ, now=NOW)
        target = self.base / "one-model"
        done = sc.restore("testgame", "models", target, unit="phobos-private-ours.safetensors", environ=self.environ)
        self.assertEqual(done["restored"], 1)
        self.assertEqual((target / "phobos-private-ours.safetensors").read_bytes(), b"model ours")

    def test_restore_never_writes_inside_the_copies(self):
        sc.run(self.repo, self.environ, now=NOW)
        with self.assertRaises(sc.SafeCopiesError):
            sc.restore("testgame", "trainings", self.local / "inside", environ=self.environ)


class CommandTests(Fixture):
    def call(self, *argv):
        out = io.StringIO()
        code = sc.main([*argv, "--json"], out, self.environ)
        return code, json.loads(out.getvalue())

    def test_plan_status_and_verify_answer_in_the_envelope(self):
        code, planned = self.call("plan", "--root", str(self.repo))
        self.assertEqual(code, sc.EXIT_OK)
        local = next(d for d in planned["data"]["destinations"] if d["name"] == "local")
        self.assertTrue(local["privateLocal"])
        self.assertTrue(local["copy"])
        sc.run(self.repo, self.environ, now=NOW)
        code, found = self.call("status", "--root", str(self.repo))
        ours = next(s for s in found["data"]["sets"] if s["unit"] == "ours")
        self.assertEqual(ours["destinations"]["local"]["state"], "copied")
        self.assertEqual(ours["destinations"]["repository"]["state"], "not ready")
        code, checked = self.call("verify", "--root", str(self.repo))
        self.assertEqual(code, sc.EXIT_OK)

    def test_status_says_when_something_was_never_copied(self):
        code, found = self.call("status", "--root", str(self.repo))
        self.assertIn("never copied", found["report"]["title"])

    def test_a_refusal_exits_three_with_its_reason(self):
        code, refused = self.call("restore", "--root", str(self.repo), "--set", "trainings", "--to", str(self.base / "out"))
        self.assertEqual(code, sc.EXIT_REFUSED)
        self.assertIn("nothing is copied", refused["data"]["refusal"])


class OwnershipTests(Fixture):
    """1.71.0: two lists of one game, as two repositories of one game, or a game's saves kept apart from its art."""

    def second_list(self, set_name="notes"):
        other = self.base / "other"
        (other / "config").mkdir(parents=True)
        (other / "notes").mkdir()
        (other / "notes" / "a.md").write_text("a", encoding="utf-8")
        (other / "notes" / "b.md").write_text("b", encoding="utf-8")
        (other / "config" / "safe-copies.json").write_text(json.dumps(
            {"game": "testgame", "sets": [{"name": set_name, "root": "@repository", "folder": "notes", "include": ["*.md"],
                                           "kind": "own"}]}), encoding="utf-8")
        return other

    def state(self):
        return sc.read_state(self.local)

    def test_one_list_never_marks_anothers_copies_gone_or_offers_them(self):
        other = self.second_list()
        sc.run(self.repo, self.environ, push=False, now=NOW)
        sc.run(other, self.environ, push=False, now=NOW)
        self.assertFalse([k for k, r in self.state().items() if r.get("gone")], "neither list took the other's files away")
        (other / "notes" / "b.md").unlink()
        collection, _ = sc.run(other, self.environ, push=False, now=LATER)
        gone = sorted(k for k, r in self.state().items() if r.get("gone"))
        self.assertEqual(gone, ["testgame/notes/b.md"])
        mine = sc.collect(self.repo, self.environ)
        local = next(d for d in sc.destinations(self.environ) if d.name == "local")
        self.assertEqual(sc.kept_only(mine, local), [], "the first list does not offer the second's copy to let go")
        self.assertEqual([e["key"] for e in sc.kept_only(collection, local)], ["testgame/notes/b.md"])

    def test_each_copy_says_which_list_made_it(self):
        sc.run(self.repo, self.environ, push=False, now=NOW)
        self.assertEqual({r["from"] for r in self.state().values()}, {"repo"})

    def test_two_lists_naming_one_set_are_refused_until_one_is_renamed(self):
        sc.run(self.repo, self.environ, push=False, now=NOW)
        other = self.second_list("plans")
        with self.assertRaises(sc.SafeCopiesError) as refused:
            sc.run(other, self.environ, push=False, now=NOW)
        self.assertIn("testgame/plans from repo", str(refused.exception))
        collection, _, _ = sc.status(other, self.environ)
        self.assertTrue(any("from repo too" in note for note in collection.notes))

    def test_a_copy_recorded_before_lists_had_names_is_still_its_lists(self):
        sc.run(self.repo, self.environ, push=False, now=NOW)
        state = self.state()
        for record in state.values():
            record.pop("from")
        sc._write_json(self.local / sc.BOOK / "state.json", {"format": sc.FORMAT, "files": state})
        sc.run(self.repo, self.environ, push=False, now=LATER)
        self.assertEqual({r.get("from") for r in self.state().values()}, {"repo"}, "an unchanged copy learns its list")


class GameListTests(Fixture):
    """1.71.0: a game's own list kept by any repository, saves that are folders, and the daily run's wait for fresh files."""

    def setUp(self):
        super().setUp()
        self.saves = self.base / "game-data" / "Saves"
        for number, name in enumerate(("pg1", "pg2", "pg3", "autosave_9_pg3")):
            folder = self.saves / name
            folder.mkdir(parents=True)
            for part in ("ship.json", "crew.json"):
                (folder / part).write_text(f"{name} {part}", encoding="utf-8")
                moment = NOW.timestamp() - 3600 + number * 60
                os.utime(folder / part, (moment, moment))
        (self.repo / "config" / "safe-copies").mkdir()
        self.write_list({"game": "spacegame", "sets": [
            {"name": "saves", "root": "gameDataPath", "folder": "Saves", "units": True, "unitExclude": ["autosave*"], "newest": 2,
             "keepEarlier": 2, "kind": "personal"}]})
        self.environ["PHOBOS_TEST_GAME_DATA"] = str(self.base / "game-data")

    def write_list(self, data):
        (self.repo / "config" / "safe-copies" / "spacegame.json").write_text(json.dumps(data), encoding="utf-8")
        settings = json.loads((self.repo / ".local" / "install-settings.json").read_text(encoding="utf-8"))
        settings["gameDataPath"] = str(self.base / "game-data")
        (self.repo / ".local" / "install-settings.json").write_text(json.dumps(settings), encoding="utf-8")

    def plain_folder(self):
        return next(d for d in sc.destinations(self.environ) if d.name == "local")

    def test_a_games_list_is_its_own_list_beside_the_repositorys(self):
        collection = sc.collect(self.repo, self.environ, game="spacegame")
        self.assertEqual((collection.game, collection.source), ("spacegame", "repo:spacegame"))
        self.assertEqual(sc.collect(self.repo, self.environ).game, "testgame", "the repository's own list is untouched")
        with self.assertRaises(sc.SafeCopiesError):
            sc.collect(self.repo, self.environ, game="othergame")
        self.write_list({"game": "wrong", "sets": [{"name": "x", "root": "@repository"}]})
        with self.assertRaises(sc.SafeCopiesError) as refused:
            sc.collect(self.repo, self.environ, game="spacegame")
        self.assertIn("names the game wrong", str(refused.exception))

    def test_the_newest_saves_are_whole_folders_and_autosaves_are_left_out(self):
        collection = sc.collect(self.repo, self.environ, game="spacegame")
        self.assertEqual(sorted({i.unit for i in collection.items}), ["pg2", "pg3"])
        self.assertEqual(len(collection.items), 4)

    def test_a_save_that_leaves_the_newest_pair_is_offered_whole_and_let_go_whole(self):
        sc.run(self.repo, self.environ, push=False, now=NOW, game="spacegame")
        newer = self.saves / "pg4"
        newer.mkdir()
        (newer / "ship.json").write_text("pg4", encoding="utf-8")
        sc.run(self.repo, self.environ, push=False, now=LATER, game="spacegame")
        collection = sc.collect(self.repo, self.environ, game="spacegame")
        kept = sc.kept_only(collection, self.plain_folder())
        self.assertEqual([(e["key"], e["files"]) for e in kept], [("spacegame/saves/pg2", 2)])
        self.assertIn("no longer among the newest 2", kept[0]["why"])
        done = sc.let_go(self.repo, ["spacegame/saves/pg2"], self.environ, apply=True, game="spacegame")
        self.assertEqual(len(done["letGo"]), 2)
        self.assertNotIn("keys", done["chosen"][0], "the list of every file stays out of what is shown")
        copies = self.local / "spacegame" / "saves" / "pg2"
        self.assertFalse(copies.exists() and any(copies.rglob("*.json")))
        self.assertTrue((self.saves / "pg2" / "ship.json").is_file(), "the save itself is never touched")

    def test_the_daily_run_leaves_a_save_still_being_written_for_next_time(self):
        os.utime(self.saves / "pg3" / "crew.json", (NOW.timestamp() - 30, NOW.timestamp() - 30))
        collection = sc.collect(self.repo, self.environ, game="spacegame", settle=True, now=NOW)
        self.assertEqual(sorted({i.unit for i in collection.items}), ["pg2"], "pg3 waits whole, never half copied")
        self.assertTrue(any("pg3: written in the last 2 minutes" in note for note in collection.notes))
        local = self.plain_folder()
        sc.run(self.repo, self.environ, push=False, now=NOW, game="spacegame", settle=True)
        self.assertEqual(sc.kept_only(sc.collect(self.repo, self.environ, game="spacegame"), local), [])
        self.assertEqual(len(sc.collect(self.repo, self.environ, game="spacegame").items), 4, "a run without waiting takes it")

    def test_a_fresh_loose_file_waits_and_nothing_is_called_gone_meanwhile(self):
        sc.run(self.repo, self.environ, push=False, now=NOW)
        fresh = self.repo / "plans" / "night-2.json"
        fresh.write_text("[]", encoding="utf-8")
        os.utime(fresh, (LATER.timestamp() - 10, LATER.timestamp() - 10))
        collection = sc.collect(self.repo, self.environ, settle=True, now=LATER)
        self.assertNotIn("testgame/plans/night-2.json", {i.key for i in collection.items})
        self.assertNotIn(("plans", None), collection.walked)


if __name__ == "__main__":
    unittest.main()
