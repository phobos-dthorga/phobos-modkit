"""repos status and the GitHub reader's shared allowance, conditional requests and last answers (1.89.0). GitHub is made-up
answers here; nothing reaches the network. The repositories are throwaway git repositories with a GitHub address as their remote
and the remote's branch set by hand, so nothing is pushed."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import repos
from phobos_modkit.github import API, AUTOMATIC_FLOOR, Client, GitHubError, RateLimited

NOW = 1_800_000_000          # a fixed clock, in seconds
HOUR_TURNS = NOW + 1800


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def repository(path, name="me/thing", schedule=False):
    """A repository with two commits; the remote's main is the first, so one commit is not pushed."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for key, value in (("core.fsmonitor", "false"), ("user.email", "test@example.com"), ("user.name", "Test")):
        git(path, "config", key, value)
    write(path / "a.txt", "one\n")
    if schedule:
        write(path / ".github" / "workflows" / "night.yml", "on:\n  schedule:\n    - cron: '17 16 * * *'\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "one")
    git(path, "remote", "add", "origin", f"https://github.com/{name}.git")
    git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(path, "config", "branch.main.remote", "origin")
    git(path, "config", "branch.main.merge", "refs/heads/main")
    pushed = git(path, "rev-parse", "HEAD")
    write(path / "a.txt", "two\n")
    git(path, "commit", "-q", "-am", "two")
    write(path / "a.txt", "three\n")     # a tracked file changed, not committed
    return pushed


def run(event, sha, status="completed", conclusion="success", name="Checks", when="2027-01-15T08:00:00Z"):
    return {"name": name, "path": f".github/workflows/{name.lower()}.yml", "event": event, "status": status,
            "conclusion": conclusion, "head_sha": sha, "created_at": when, "html_url": f"https://github.com/x/{name}"}


class FakeGitHub:
    """URL -> list of runs; counts the calls; answers with the allowance it is given, and 304 to a matching ETag."""

    def __init__(self, remaining=50):
        self.pages = {}
        self.calls = []
        self.remaining = remaining
        self.offline = False

    def runs_for(self, name, runs, branch="main"):
        self.pages[f"{API}/repos/{name}/actions/runs?branch={branch}&per_page={repos.PUSH_RUNS}"] = runs

    def nightly_for(self, name, runs):
        self.pages[f"{API}/repos/{name}/actions/runs?event=schedule&per_page={repos.NIGHTLY_RUNS}"] = runs

    def __call__(self, url, headers=None):
        if self.offline:
            raise GitHubError("GitHub could not be reached: made up")
        self.calls.append((url, dict(headers or {})))
        self.remaining -= 1
        allowance = {"X-RateLimit-Remaining": str(self.remaining), "X-RateLimit-Limit": "60",
                     "X-RateLimit-Reset": str(HOUR_TURNS), "X-RateLimit-Resource": "core"}
        if url not in self.pages:
            return 404, b"", allowance
        body = json.dumps({"workflow_runs": self.pages[url]}).encode("utf-8")
        etag = f'"{hash(body)}"'
        if (headers or {}).get("If-None-Match") == etag:
            return 304, b"", allowance
        return 200, body, {**allowance, "ETag": etag}


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "thing"
        self.pushed = repository(self.repo)
        self.cache = self.root / "cache"
        self.fake = FakeGitHub()
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, automatic=False):
        return Client(self.cache, get=self.fake, sleep=lambda s: None, clock=self.clock, automatic=automatic, keep_last=True)

    def look(self, automatic=False):
        return repos.status([self.repo], self.client(automatic), automatic, self.cache, self.clock)[0]

    def test_local_facts_need_no_network(self):
        found = repos.status([self.repo])[0]
        self.assertEqual((found["github"], found["branch"], found["ahead"], found["behind"], found["changed"]),
                         ("me/thing", "main", 1, 0, 1))
        self.assertNotIn("checks", found)

    def test_each_light_from_the_runs_for_the_last_push(self):
        cases = [([run("push", self.pushed)], "passed"),
                 ([run("push", self.pushed, conclusion="failure"), run("push", self.pushed, name="Lint")], "failed"),
                 ([run("push", self.pushed, status="in_progress", conclusion=None)], "running"),
                 ([run("push", "0" * 40)], "waiting"),
                 ([run("workflow_dispatch", self.pushed)], "no-push-checks"),
                 ([], "none")]
        for runs, expected in cases:
            with self.subTest(expected=expected):
                state, _ = repos.push_state(runs, self.pushed)
                self.assertEqual(state, expected)

    def test_a_failed_check_is_named_in_the_report(self):
        self.fake.runs_for("me/thing", [run("push", self.pushed, conclusion="failure")])
        out = io.StringIO()
        code = repos.main(["status", "--root", str(self.repo), "--online", "--cache", str(self.cache)], out=out,
                          environ={}, get=self.fake, clock=self.clock)
        self.assertEqual(code, repos.EXIT_OK)
        self.assertIn("failed (Checks)", out.getvalue())
        self.assertIn("calls left this hour", out.getvalue())

    def test_an_automatic_look_asks_again_only_when_the_push_moved(self):
        self.fake.runs_for("me/thing", [run("push", self.pushed)])
        self.assertEqual(self.look(automatic=True)["checks"]["state"], "passed")
        self.clock.now += 3600
        self.look(automatic=True)
        self.assertEqual(len(self.fake.calls), 1, "nothing moved, so the last answer is used")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")     # as if the second commit were pushed
        self.assertEqual(self.look(automatic=True)["checks"]["state"], "waiting")
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(self.fake.calls[1][1].get("If-None-Match") is not None, True, "asked again with its ETag")

    def test_a_run_still_going_is_asked_about_after_five_minutes(self):
        self.fake.runs_for("me/thing", [run("push", self.pushed, status="in_progress", conclusion=None)])
        self.look(automatic=True)
        self.clock.now += 60
        self.look(automatic=True)
        self.assertEqual(len(self.fake.calls), 1)
        self.fake.runs_for("me/thing", [run("push", self.pushed)])
        self.clock.now += repos.RUNNING_FRESH_SECONDS
        self.assertEqual(self.look(automatic=True)["checks"]["state"], "passed")

    def test_unchanged_answers_are_confirmed_with_the_etag(self):
        self.fake.runs_for("me/thing", [run("push", self.pushed)])
        self.look()
        self.clock.now += repos.PRESS_FRESH_SECONDS + 1
        client = self.client()
        repos.status([self.repo], client, False, self.cache, self.clock)
        self.assertEqual((client.revalidated, client.fetched), (1, 0))

    def test_offline_the_last_answer_is_given_with_its_age(self):
        self.fake.runs_for("me/thing", [run("push", self.pushed)])
        self.look()
        self.fake.offline = True
        self.clock.now += 7200
        checks = self.look()["checks"]
        self.assertEqual((checks["state"], checks["stale"], checks["asOf"]), ("passed", True, NOW))

    def test_offline_with_no_answer_says_why(self):
        self.fake.offline = True
        checks = self.look()["checks"]
        self.assertEqual(checks["state"], "unknown")
        self.assertIn("could not be reached", checks["why"])

    def test_an_automatic_look_leaves_the_last_calls_for_a_press(self):
        self.fake.runs_for("me/thing", [run("push", self.pushed)])
        self.fake.remaining = AUTOMATIC_FLOOR + 1      # the first answer reports AUTOMATIC_FLOOR left
        self.look(automatic=True)
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        client = self.client(automatic=True)
        found = repos.status([self.repo], client, True, self.cache, self.clock)[0]
        self.assertEqual(len(self.fake.calls), 1, "kept for a press")
        self.assertTrue(found["checks"]["stale"])
        self.assertIn("kept for a press", client.limited)
        self.clock.now += repos.PRESS_FRESH_SECONDS + 1
        self.look(automatic=False)
        self.assertEqual(len(self.fake.calls), 2, "a press still asks")

    def test_no_call_is_made_once_none_are_left_this_hour(self):
        client = self.client()
        self.fake.runs_for("me/thing", [run("push", self.pushed)])
        self.fake.remaining = 1
        repos.status([self.repo], client, False, self.cache, self.clock)
        with self.assertRaises(RateLimited):
            self.client().runs("me/other", "main")
        self.assertEqual(len(self.fake.calls), 1)
        self.clock.now = HOUR_TURNS + 1
        self.assertEqual(self.client().allowance()["turned"], True)

    def test_a_repository_not_on_github_is_said_so_without_a_call(self):
        git(self.repo, "remote", "set-url", "origin", "https://example.org/me/thing.git")
        self.assertEqual(self.look()["checks"]["state"], "not-on-github")
        self.assertEqual(self.fake.calls, [])


class NightlyTests(unittest.TestCase):
    def test_only_a_repository_with_a_schedule_asks_for_its_nightly_runs_and_an_old_one_is_late(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pushed = repository(root / "night", "me/night", schedule=True)
            fake = FakeGitHub()
            fake.runs_for("me/night", [run("push", pushed)])
            old = "2026-12-01T16:17:00Z"
            fake.nightly_for("me/night", [run("schedule", pushed, name="Upstream watch", when=old)])
            client = Client(root / "cache", get=fake, sleep=lambda s: None, clock=Clock(), keep_last=True)
            found = repos.status([root / "night"], client, False, root / "cache", Clock())[0]
            self.assertTrue(found["scheduled"])
            self.assertEqual([(n["workflow"], n["late"]) for n in found["nightly"]], [("Upstream watch", True)])
            self.assertEqual(len(fake.calls), 2)


if __name__ == "__main__":
    unittest.main()
