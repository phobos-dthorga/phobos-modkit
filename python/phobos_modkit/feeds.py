"""feeds: small files of data a repository publishes for D'thorga Companion to read: an index, and files each checked by kind (1.90.0).

    feeds index --folder DIR --name NAME [--title TEXT] [--write]   the index of a feed folder (written with --write)
    feeds check --folder DIR                                         whether the index still matches its files, and each file its kind
    feeds read --source OWNER/REPO[@REF][:PATH] [...]                each feed from GitHub's raw files, checked, with the last good kept

phobos-companion docs/online.md, S3. A feed is a folder: `index.json` (format 1: the feed's name and title, when it changed, and
for each file its kind, path, size and SHA-256) beside its files. People write theirs in a repository's `feeds/` folder on its
default branch; a nightly run writes its own at the top of a results branch (`companion-results`). Game-free: what a game knows
reaches a feed through the kind of file it writes.

Kinds of file in format 1, and who checks them: `upstream-watch` (a nightly watch's findings, checked here), `theme` (in a
`theme` folder) and `guide` (Markdown, in a `guide` folder), checked by the program that uses them. A file of a kind this kit
does not know is skipped and said, never used. `known-problems` and `sort-rules` come with their own checks in a later version.

Reading is keyless, from raw.githubusercontent.com (outside GitHub's hourly API count), cached for six hours. Each file's size and
hash must match its index, and its kind's check must pass, **or the last good copy is kept** and the report says what failed. When
GitHub cannot be reached, the last good copies are given with their age. Reads, except that `index --write` writes the folder's
index.json, and `read` keeps its copies in the kit's cache.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from . import cache as derived
from . import github
from .manifest import ONLINE, READS, WRITES
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
FORMAT = 1
INDEX = "index.json"
MAX_INDEX_BYTES = 64 * 1024       # agent defaults (docs/online.md)
MAX_FILE_BYTES = 1024 * 1024
FRESH_HOURS = 6
CACHE_FOLDER = "feeds"
FOLDER_KINDS = {"theme": "theme", "guide": "guide"}     # a file in a folder of this name is of this kind
PROGRAM_KINDS = {"theme", "guide"}                        # checked by the program that uses them
SOURCE = re.compile(r"^(?P<repo>[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100})"
                    r"(?:@(?P<ref>[A-Za-z0-9._/-]{1,100}))?(?::(?P<path>[A-Za-z0-9._/-]{0,200}))?$")
SAFE_PATH = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9._/-]{1,200}$")
FINDING_FIELDS = ("mod", "commit", "member")


class FeedError(ValueError):
    """A feed or a request this command refuses, with the reason in words."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---- Kinds ----

def kind_of(relative, data):
    """A file's kind: from the folder it is in (theme, guide), else the `kind` a JSON file names; None when it has none."""
    first = relative.split("/", 1)[0]
    if first in FOLDER_KINDS and "/" in relative:
        return FOLDER_KINDS[first]
    if relative.endswith(".json"):
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        kind = value.get("kind") if isinstance(value, dict) else None
        return kind if isinstance(kind, str) else None
    return None


def _check_upstream_watch(value):
    if not isinstance(value, dict) or value.get("format") != FORMAT:
        raise FeedError("an upstream watch must be an object of format 1")
    for field in ("game", "checked"):
        if not isinstance(value.get(field), str):
            raise FeedError(f"an upstream watch needs its {field} as text")
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise FeedError("an upstream watch needs its findings as a list")
    for finding in findings:
        if not isinstance(finding, dict) or not all(isinstance(finding.get(f), str) for f in FINDING_FIELDS):
            raise FeedError(f"each finding needs {', '.join(FINDING_FIELDS)} as text")
        link = finding.get("link")
        if link is not None and not (isinstance(link, str) and link.startswith("https://github.com/")):
            raise FeedError("a finding's link must be a GitHub page")


CHECKS = {"upstream-watch": _check_upstream_watch}


def check_file(kind, data):
    """The file's content, checked for its kind: parsed JSON, or text for a guide entry. Raises FeedError when it fails or the
    kind is not one this kit knows."""
    if len(data) > MAX_FILE_BYTES:
        raise FeedError(f"larger than {MAX_FILE_BYTES // 1024} KB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise FeedError("not UTF-8 text") from None
    if kind == "guide":
        return text
    if kind not in CHECKS and kind not in PROGRAM_KINDS:
        raise FeedError(f"not a kind this kit knows ({kind})")
    try:
        value = json.loads(text)
    except ValueError as error:
        raise FeedError(f"not JSON: {error}") from None
    if kind in CHECKS:
        CHECKS[kind](value)
    return value


def write_file(path, kind, payload, volatile=()):
    """Writes one feed file of a kind this kit checks, checking it first: what a nightly run calls to leave its answer. When the
    file there already says the same, but for the `volatile` fields (a time it was checked), it is left as it is, so a nightly
    run that found nothing new commits nothing. Returns whether it wrote."""
    value = {"kind": kind, "format": FORMAT, **payload}
    data = (json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    check_file(kind, data)
    path = Path(path)
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
        if {k: v for k, v in before.items() if k not in volatile} == {k: v for k, v in value.items() if k not in volatile}:
            return False
    except (OSError, ValueError, AttributeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


# ---- A feed folder ----

def build_index(folder, name, title=None, updated=None):
    """The index of every file in the folder (but the index itself), in a stable order."""
    folder = Path(folder)
    files = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder).as_posix()
        if relative == INDEX or relative.startswith(".") or "/." in relative:
            continue
        data = path.read_bytes()
        files.append({"path": relative, "kind": kind_of(relative, data), "bytes": len(data), "sha256": sha256(data)})
    return {"format": FORMAT, "feed": name, "title": title or name,
            "updated": updated or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "files": files}


def check_folder(folder):
    """Every fault in a feed folder: an index that no longer matches its files, a file of no kind, a file failing its kind."""
    folder = Path(folder)
    try:
        index = json.loads((folder / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"{INDEX} cannot be read: {error}"]
    faults = []
    now = build_index(folder, index.get("feed", ""))
    listed = {f.get("path"): f for f in index.get("files", [])}
    present = {f["path"]: f for f in now["files"]}
    for path in sorted(set(listed) | set(present)):
        if path not in present:
            faults.append(f"{path}: in the index but not in the folder")
        elif path not in listed:
            faults.append(f"{path}: in the folder but not in the index (run feeds index --write)")
        elif (listed[path].get("sha256"), listed[path].get("bytes")) != (present[path]["sha256"], present[path]["bytes"]):
            faults.append(f"{path}: changed since the index was written (run feeds index --write)")
    for path, entry in present.items():
        if entry["kind"] is None:
            faults.append(f"{path}: of no kind (a JSON file names its kind; themes and guide entries go in their folders)")
            continue
        try:
            check_file(entry["kind"], (folder / path).read_bytes())
        except FeedError as error:
            faults.append(f"{path}: {error}")
    return faults


# ---- Reading a feed from GitHub ----

def parse_source(text):
    """(owner/repo, ref, path) from OWNER/REPO[@REF][:PATH]; ref defaults to HEAD and path to feeds."""
    found = SOURCE.match(text or "")
    if not found:
        raise FeedError(f"\"{text}\" is not a feed's address: OWNER/REPO, then @BRANCH and :FOLDER if needed")
    path = ("feeds" if found.group("path") is None else found.group("path")).strip("/")
    ref = found.group("ref") or "HEAD"
    if ".." in path.split("/") or ".." in ref.split("/"):
        raise FeedError(f"\"{text}\" names a folder outside the repository")
    return found.group("repo"), ref, path


def _kept_folder(cache, repo, ref, path):
    return Path(cache) / "kept" / repo.replace("/", "--") / ref.replace("/", "--") / (path.replace("/", "--") or "_")


def _join(path, name):
    return f"{path}/{name}" if path else name


def read_feed(client, source, cache, clock=time.time):
    """One feed: each file new and checked, the same as before, or failing with the last good copy kept; and its content."""
    repo, ref, path = parse_source(source)
    kept = _kept_folder(cache, repo, ref, path)
    stale_before = len(client.stale)
    found = {"source": source, "repository": repo, "ref": ref, "path": path, "files": [], "stale": False, "asOf": None}
    try:
        text = client.raw(repo, ref, _join(path, INDEX))
    except github.GitHubError as error:
        text, found["why"] = None, str(error)
    if text is None:
        found["state"] = "missing" if "why" not in found else "unreachable"
        return _from_kept(found, kept)
    if len(text.encode("utf-8")) > MAX_INDEX_BYTES:
        found["state"], found["why"] = "refused", f"its index is larger than {MAX_INDEX_BYTES // 1024} KB"
        return _from_kept(found, kept)
    try:
        index = json.loads(text)
        if index.get("format") != FORMAT or not isinstance(index.get("files"), list):
            raise ValueError("not an index of format 1")
    except (ValueError, AttributeError) as error:
        found["state"], found["why"] = "refused", f"its index cannot be read: {error}"
        return _from_kept(found, kept)
    found.update({"state": "read", "feed": index.get("feed"), "title": index.get("title"), "updated": index.get("updated")})
    for entry in index["files"]:
        found["files"].append(_read_file(client, repo, ref, path, entry, kept))
    if len(client.stale) > stale_before:
        found["stale"], found["asOf"] = True, min(client.stale[stale_before:])
    return found


def _read_file(client, repo, ref, path, entry, kept):
    relative, kind = str(entry.get("path", "")), entry.get("kind")
    item = {"path": relative, "kind": kind}
    if not SAFE_PATH.match(relative):
        return {**item, "state": "refused", "why": "its path is not a plain path inside the feed"}
    last = _last_good(kept, relative)
    try:
        status, data = client.fetch(f"{github.RAW}/{repo}/{ref}/{_join(path, relative)}", "raw")
        if status != 200:
            raise FeedError(f"GitHub answered {status}")
        if len(data) != entry.get("bytes") or sha256(data) != entry.get("sha256"):
            raise FeedError("its size or hash does not match the index (the feed may be changing just now)")
        content = check_file(kind, data)
    except (FeedError, github.GitHubError) as error:
        if last:
            return {**item, "state": "kept", "why": str(error), "content": last["content"], "keptAt": last["at"]}
        return {**item, "state": "failed", "why": str(error)}
    same = bool(last) and last["sha256"] == entry.get("sha256")
    if not same:
        _keep(kept, relative, data, entry.get("sha256"))
    return {**item, "state": "same" if same else "new", "content": content}


def _keep(kept, relative, data, digest):
    target = kept / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    Path(f"{target}.kept.json").write_text(json.dumps({"sha256": digest, "at": int(time.time())}), encoding="utf-8")


def _last_good(kept, relative):
    target = kept / relative
    try:
        meta = json.loads(Path(f"{target}.kept.json").read_text(encoding="utf-8"))
        data = target.read_bytes()
        kind = kind_of(relative, data)
        return {"sha256": meta.get("sha256"), "at": meta.get("at"), "content": check_file(kind, data)}
    except (OSError, ValueError, FeedError):
        return None


def _from_kept(found, kept):
    """When the index itself can't be read: the last good copy of every file this feed gave before, as kept."""
    if not kept.is_dir():
        return found
    for marker in sorted(kept.rglob("*.kept.json")):
        relative = marker.relative_to(kept).as_posix()[: -len(".kept.json")]
        last = _last_good(kept, relative)
        if last:
            found["files"].append({"path": relative, "kind": kind_of(relative, (kept / relative).read_bytes()),
                                   "state": "kept", "content": last["content"], "keptAt": last["at"]})
    return found


# ---- The command ----

def _parser():
    p = argparse.ArgumentParser(prog="feeds", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    i = sub.add_parser("index", help="the index of a feed folder; written with --write")
    i.add_argument("--folder", required=True, help="the feed folder")
    i.add_argument("--name", required=True, help="the feed's short name (the repository's, usually)")
    i.add_argument("--title", help="the feed's title for people (default: its name)")
    i.add_argument("--write", action="store_true", help="write index.json into the folder")
    c = sub.add_parser("check", help="whether a feed folder's index matches its files, and each file its kind")
    c.add_argument("--folder", required=True, help="the feed folder")
    r = sub.add_parser("read", help="each feed from GitHub's raw files, checked, with the last good copy kept")
    r.add_argument("--source", action="append", required=True, help="OWNER/REPO[@REF][:PATH] (repeatable)")
    r.add_argument("--refresh", action="store_true", help="ask GitHub again even when the last answer is under six hours old")
    r.add_argument("--cache", help="the kit's cache folder (default: the setting, then the temporary folder)")
    for sub_parser in (i, c, r):
        sub_parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        sub_parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _emit(out, args, report, redact, data):
    out.write((envelope_text("feeds", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")


def main(argv=None, out=None, environ=None, get=None, clock=time.time, settings_file=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.report == "index":
        index = build_index(args.folder, args.name, args.title)
        try:   # nothing changed: keep the index as it was, so a nightly run that found nothing new commits nothing
            before = json.loads((Path(args.folder) / INDEX).read_text(encoding="utf-8"))
            if {k: v for k, v in before.items() if k != "updated"} == {k: v for k, v in index.items() if k != "updated"}:
                index["updated"] = before.get("updated", index["updated"])
        except (OSError, ValueError, AttributeError):
            pass
        if args.write:
            (Path(args.folder) / INDEX).write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        report = Report(f"Feed {args.name}: {len(index['files'])} files" + (", index written" if args.write else ""))
        report.section("Files", Table(["Path", "Kind", "Bytes"], [[f["path"], f["kind"] or "none", str(f["bytes"])]
                                                                   for f in index["files"]]))
        _emit(out, args, report, redact, index)
        return EXIT_OK
    if args.report == "check":
        faults = check_folder(args.folder)
        report = Report("Feed folder: " + ("matches its index" if not faults else f"{len(faults)} faults"))
        if faults:
            report.section("Faults", Bullets(faults))
        _emit(out, args, report, redact, {"faults": faults})
        return EXIT_FAILED if faults else EXIT_OK
    try:
        sources = [parse_source(s) and s for s in args.source]
    except FeedError as error:
        _emit(out, args, Report("feeds read: refused", [str(error)]), redact, {"feeds": []})
        return EXIT_USAGE
    folder = derived.folder(github.CACHE_FOLDER, args.cache, environ, settings_file)
    client = github.Client(folder, get=get or github.http_get, clock=clock, max_age_hours=FRESH_HOURS, refresh=args.refresh,
                           keep_last=True)
    feeds = [read_feed(client, source, derived.folder(CACHE_FOLDER, args.cache, environ, settings_file), clock)
             for source in sources]
    report = Report(f"Feeds: {len(feeds)}")
    report.section("Files", Table(["Feed", "File", "Kind", "Now", "Why"],
                                  [[f["source"], x["path"], x.get("kind") or "", x["state"], x.get("why", "")]
                                   for f in feeds for x in f["files"]] or [[f["source"], "", "", f.get("state", ""),
                                                                           f.get("why", "")] for f in feeds]))
    _emit(out, args, report, redact, {"feeds": feeds})
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS, "surface": "feeds",
            "reports": {"index": {"effect": WRITES, "when": "--write"},
                        "read": {"effect": ONLINE, "note": "GitHub's raw files, keyless; keeps checked copies in the kit's cache"}}}
