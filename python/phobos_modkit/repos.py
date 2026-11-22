"""repos: where each repository stands with its remote, and whether GitHub's checks passed for its last push (1.87.0).

    repos status --root REPO [--root REPO ...]                  local only: the branch, commits not pushed, files changed
    repos status --root REPO ... --online                       also GitHub's checks for the last push and each nightly run
    repos status --root REPO ... --online --automatic           a look nobody pressed for: asks GitHub only what may have changed

D'thorga Companion's gate lights (phobos-companion docs/online.md, O4). Game-free: any repository whose remote is on GitHub.

Local facts come from git, asked with --no-optional-locks and without the file-system monitor, so a look takes no lock and starts
no background watcher. Asking GitHub is keyless (the kit's GitHub reader, one hourly allowance for every tool): one call for each
repository, its newest runs for pushes on the pushed branch, and one more only for a repository whose own workflow files hold a
schedule (its nightly runs). With --automatic, a repository is asked again only when its pushed commit moved since the last look,
when a run was still going (after 5 minutes), or when the last answer is a day old; otherwise the last answer is used, and none
is asked while 15 or fewer calls are left this hour. When GitHub cannot be reached or asked, the last answer is given with its age.

Reads only: git is asked, never told; GitHub is read, never written to.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from . import cache as derived
from . import github
from .manifest import ONLINE, READS
from .progress import Progress
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE = 0, 2
STATE_FILE = "repos-state.json"
PUSH_RUNS = 10
NIGHTLY_RUNS = 5
PRESS_FRESH_SECONDS = 60           # a press asks again after a minute (agent default)
RUNNING_FRESH_SECONDS = 5 * 60     # a run still going is asked about again after five minutes
SETTLED_FRESH_SECONDS = 24 * 3600  # otherwise once a day
NIGHTLY_LATE_HOURS = 48            # a nightly run older than this has probably been switched off, or keeps failing to start
FAILED = {"failure", "timed_out", "startup_failure", "action_required"}
FINE = {"success", "skipped", "neutral"}
SCHEDULE = re.compile(r"^\s*schedule\s*:", re.M)
WORKFLOWS = Path(".github") / "workflows"

# What each light says, in words; the window has its own words for each state.
STATES = {
    "passed": "passed", "failed": "failed", "running": "running", "cancelled": "cancelled",
    "waiting": "no run yet for the last push", "no-push-checks": "no checks run on a push", "none": "no checks on GitHub",
    "not-on-github": "not on GitHub", "no-upstream": "no branch on a remote", "unknown": "not asked",
}


def _git(root, *args):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), "-c", "core.fsmonitor=false", *args],
                            capture_output=True, check=False)
    return result.stdout.decode("utf-8", "replace").strip() if result.returncode == 0 else None


def scheduled(root):
    """True when one of the repository's own workflow files holds a schedule."""
    folder = Path(root) / WORKFLOWS
    if not folder.is_dir():
        return False
    for path in sorted(folder.glob("*.y*ml")):
        try:
            if SCHEDULE.search(path.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def local(root):
    """{name, root, branch, upstream, remoteBranch, github, pushed, ahead, behind, changed, scheduled} from git alone."""
    root = Path(root).resolve()
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    found = {"name": root.name, "root": str(root), "branch": branch, "upstream": upstream, "remoteBranch": None,
             "github": None, "pushed": None, "ahead": None, "behind": None, "changed": None, "scheduled": scheduled(root)}
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    found["changed"] = len(status.splitlines()) if status is not None else None
    if not upstream:
        return found
    remote, _, remote_branch = upstream.partition("/")
    found["remoteBranch"] = remote_branch
    found["pushed"] = _git(root, "rev-parse", "@{u}")
    counts = (_git(root, "rev-list", "--left-right", "--count", "HEAD...@{u}") or "").split()
    if len(counts) == 2 and all(c.isdigit() for c in counts):
        found["ahead"], found["behind"] = int(counts[0]), int(counts[1])
    names = github.links(_git(root, "remote", "get-url", remote) or "")
    found["github"] = names[0] if names else None
    return found


def _newest_by_workflow(runs):
    newest = {}
    for run in runs:   # GitHub lists newest first
        newest.setdefault(run.get("path") or run.get("name"), run)
    return list(newest.values())


def _run(run):
    return {"workflow": run.get("name") or run.get("path") or "", "event": run.get("event"), "status": run.get("status"),
            "conclusion": run.get("conclusion"), "commit": (run.get("head_sha") or "")[:12], "when": run.get("created_at"),
            "link": run.get("html_url")}


def push_state(runs, pushed):
    """(state, the runs it stands on) for the last push, from the newest runs GitHub lists for pushes on its branch."""
    if not runs:
        return "none", []
    for_push = _newest_by_workflow([r for r in runs if r.get("event") == "push" and r.get("head_sha") == pushed])
    if not [r for r in runs if r.get("event") == "push"]:
        return "no-push-checks", []
    if not for_push:
        return "waiting", []
    if any(r.get("status") != "completed" for r in for_push):
        return "running", for_push
    if any(r.get("conclusion") in FAILED for r in for_push):
        return "failed", for_push
    if all(r.get("conclusion") in FINE for r in for_push):
        return "passed", for_push
    return "cancelled", for_push


def _age_hours(when, now):
    try:
        moment = datetime.datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - moment.timestamp()) / 3600


def nightly(runs, now):
    """The newest scheduled run of each workflow, each marked late when it is older than NIGHTLY_LATE_HOURS."""
    found = []
    for run in _newest_by_workflow(runs):
        age = _age_hours(run.get("created_at"), now)
        found.append({**_run(run), "late": age is not None and age > NIGHTLY_LATE_HOURS})
    return found


def _read_state(folder):
    try:
        return json.loads((Path(folder) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(folder, state):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / STATE_FILE).write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def _fresh_for(remembered, pushed, automatic):
    """How old a cached answer may be for this repository: a press asks after a minute; an automatic look only when the pushed
    commit moved, a run was going, or a day has passed."""
    if not automatic:
        return PRESS_FRESH_SECONDS
    if not remembered or remembered.get("pushed") != pushed:
        return 0
    return RUNNING_FRESH_SECONDS if remembered.get("running") else SETTLED_FRESH_SECONDS


def ask(found, client, state, automatic, now):
    """Adds GitHub's answer to one repository's local facts: its checks and nightly runs, and how old the answer is."""
    if not found["github"]:
        found["checks"] = {"state": "not-on-github" if found["upstream"] else "no-upstream", "runs": []}
        found["nightly"] = []
        return
    remembered = state.get(found["github"], {})
    fresh_for = _fresh_for(remembered, found["pushed"], automatic)
    stale_before = len(client.stale)
    try:
        runs = client.runs(found["github"], found["remoteBranch"], PUSH_RUNS, max_age=fresh_for)
        push_runs = [r for r in runs if r.get("event") == "push"]
        nightly_runs = []
        if found["scheduled"]:
            url = (f"{github.API}/repos/{found['github']}/actions/runs?event=schedule&per_page={NIGHTLY_RUNS}")
            status, body = client.fetch(url, "api", fresh_for if automatic else PRESS_FRESH_SECONDS)
            nightly_runs = json.loads(body.decode("utf-8", "replace")).get("workflow_runs", []) if status == 200 else []
    except github.GitHubError as error:
        found["checks"] = {"state": "unknown", "runs": [], "why": str(error)}
        found["nightly"] = []
        return
    light, standing = push_state(push_runs or runs, found["pushed"])
    found["checks"] = {"state": light, "runs": [_run(r) for r in standing],
                       "stale": len(client.stale) > stale_before,
                       "asOf": min(client.stale[stale_before:]) if len(client.stale) > stale_before else None}
    found["nightly"] = nightly(nightly_runs, now)
    state[found["github"]] = {"pushed": found["pushed"], "running": light == "running"}


def status(roots, client=None, automatic=False, state_folder=None, clock=time.time, progress=None):
    """Every repository's local facts and, with a client, GitHub's answer; and what asking cost."""
    progress = progress or (lambda *a, **k: None)
    state = _read_state(state_folder) if state_folder else {}
    found = []
    for step, root in enumerate(roots, 1):
        progress(f"Reading {Path(root).name}", step, len(roots))
        facts = local(root)
        if client is not None:
            ask(facts, client, state, automatic, clock())
        found.append(facts)
    if client is not None and state_folder:
        _write_state(state_folder, state)
    return found


def _when(seconds):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds)) if seconds else ""


def _light(facts):
    checks = facts.get("checks")
    if not checks:
        return "not asked"
    words = STATES.get(checks["state"], checks["state"])
    failed = [r["workflow"] for r in checks.get("runs", []) if r.get("conclusion") in FAILED]
    if failed:
        words += f" ({', '.join(failed)})"
    if checks.get("stale"):
        words += f", as of {_when(checks['asOf'])}"
    return words


def _night(facts):
    runs = facts.get("nightly") or []
    if not runs:
        return "" if not facts.get("scheduled") else "never ran"
    return "; ".join(f"{r['workflow']}: {r.get('conclusion') or r.get('status')} {str(r.get('when') or '')[:10]}"
                     + (" (late)" if r["late"] else "") for r in runs)


def build_report(found, online, client):
    asked = [f for f in found if f.get("checks")]
    report = Report(f"Repositories: {len(found)}" + (f"; GitHub's checks for {len(asked)}" if online else ""))
    report.section("Where each stands", Table(
        ["Repository", "Not pushed", "Changed files", "Last push on GitHub", "Nightly"],
        [[f["name"], "" if f["ahead"] is None else str(f["ahead"]), "" if f["changed"] is None else str(f["changed"]),
          _light(f) if online else "not asked", _night(f) if online else ""] for f in found]))
    notes = []
    if not online:
        notes.append("GitHub was not asked: add --online for the checks of each last push.")
    if client is not None:
        allowance = client.allowance()
        if allowance and not allowance["turned"]:
            notes.append(f"Keyless GitHub calls left this hour: {allowance['remaining']} of {allowance['size'] or 60}.")
        notes.append(f"Asked GitHub {client.fetched} times; {client.reused} answers were still fresh; "
                     f"{client.revalidated} were confirmed unchanged.")
        if client.limited:
            notes.append(client.limited)
    if notes:
        report.section("Limits", Bullets(notes))
    return report


def _parser():
    p = argparse.ArgumentParser(prog="repos", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("status", help="each repository's commits not pushed, files changed, and GitHub's checks for its last push")
    s.add_argument("--root", action="append", default=[], help="a repository (repeatable; default: the current folder)")
    s.add_argument("--online", action="store_true", help="also ask GitHub for each last push's checks (keyless)")
    s.add_argument("--automatic", action="store_true",
                   help="a look nobody pressed for: ask GitHub only what may have changed, and keep calls for a press")
    s.add_argument("--cache", help="the kit's cache folder (default: the setting, then the temporary folder)")
    s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None, environ=None, get=None, clock=time.time, settings_file=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    client = folder = None
    if args.online:
        folder = derived.folder(github.CACHE_FOLDER, args.cache, environ, settings_file)
        client = github.Client(folder, get=get or github.http_get, clock=clock, automatic=args.automatic, keep_last=True)
    found = status(args.root or ["."], client, args.automatic, folder, clock, Progress(environ))
    report = build_report(found, args.online, client)
    data = {"repositories": found, "online": args.online, "automatic": args.automatic,
            "allowance": client.allowance() if client else None,
            "asked": client.fetched if client else 0, "reused": client.reused if client else 0,
            "revalidated": client.revalidated if client else 0, "limited": client.limited if client else None}
    out.write((envelope_text("repos", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS, "surface": "repo-status",
            "reports": {"status": {"effect": ONLINE, "when": "--online",
                                   "note": "each repository's commits not pushed and files changed; with --online, GitHub's "
                                           "checks for its last push (keyless)"}}}
