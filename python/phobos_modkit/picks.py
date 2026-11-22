"""picks: the pictures and sounds waiting for the owner to pick one, each with its tries, and the owner's picks (1.83.0).

    picks list --root REPO [--root REPO ...]                          every pick, waiting ones first, with any answer
    picks answer --root REPO --id ID --pick TRY [--words W]           records the owner's pick (TRY is a try's id, or "none")
    picks offer --root REPO --file PICK.json                          adds or replaces one waiting pick (for a repository's art tools)
    picks settle --root REPO --id ID                                  removes a pick once its answer is applied

A repository lists what waits in config/picks.json; its art tools offer a pick whenever they make tries for the owner to choose
from, so the owner picks on D'thorga Companion's Picks page instead of from cards in a conversation (the owner's choices of 23 Nov
2026: a file each repository keeps; a pick kept as an answer). Answers are appended, one JSON line each, to a file per repository in
the Companion's folder (companionPicksPath, PHOBOS_PICKS), as decisions' are; the last line for a pick decides, so a pick can be
changed. **An agent session or an art tool applies an answer** (exports the try, records it) **and settles the pick in the same
commit**, so the file holds only what still waits.

config/picks.json:

    {"schemaVersion": 1,
     "grounds": [{"name": "Soil", "colour": "#5C4C3A"}, {"name": "Dark stone", "colour": "#303034"}],
     "picks": [
       {"id": "billy-kettle", "title": "The billy kettle", "kind": "picture",
        "inUse": "mods/Thing/Textures/Kettle.png",
        "tries": [{"id": "3", "label": "Try 3", "path": "K:/art/cards/kettle/export/billy-kettle-3.png", "note": "4 loose specks"}],
        "context": "A redraw: the old one's spout was hidden.", "from": "assets/thing/requests/redraw.json", "asked": "2026-11-23"}]}

A path is the repository's own (relative) or anywhere on this PC (absolute); the list says whether each file is there. `kind` is
"picture" or "sound". Grounds are colours a game's pictures are seen on, offered beside the Companion's own. No game in it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

from .manifest import READS, WRITES
from .paths import companion_data, resolve
from .report import Bullets, Report, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
ANSWERS = ("companionPicksPath", "PHOBOS_PICKS")
CONFIG = Path("config") / "picks.json"
SCHEMA_VERSION = 1
ANSWER_FORMAT = 1
NONE = "none"
KINDS = ("picture", "sound")
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_TEXT = 2000
MAX_WORDS = 4000
MAX_TRIES = 40
MAX_GROUNDS = 6


class PickError(ValueError):
    """A request or a file this command refuses, with the reason in words."""


def answers_file(root, environ=None):
    """The owner's picks for a repository: companionPicksPath (a folder), else picks/<repository>.jsonl in the Companion's folder."""
    folder = resolve(*ANSWERS, companion_data(environ) / "picks", None, environ)
    return Path(folder) / f"{Path(root).resolve().name}.jsonl"


def _text(value, limit=MAX_TEXT):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _path(root, value):
    """A try's or the picture in use's file, made absolute: the repository's own when relative."""
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    return path if path.is_absolute() else Path(root).resolve() / path


def check_pick(item, where="a pick"):
    """One pick, checked and tidied; raises PickError in words. Paths stay as written."""
    pick_id = item.get("id") if isinstance(item, dict) else None
    if not isinstance(pick_id, str) or not ID.match(pick_id):
        raise PickError(f"{where} needs an id of lower-case letters, digits, dots, hyphens and underscores: {item}")
    kind = item.get("kind")
    if kind not in KINDS:
        raise PickError(f"{pick_id}: kind is 'picture' or 'sound', not {kind!r}")
    tries, seen = [], set()
    for found in item.get("tries") or []:
        try_id = found.get("id") if isinstance(found, dict) else None
        if not isinstance(try_id, str) or not ID.match(try_id) or try_id == NONE or try_id in seen:
            raise PickError(f"{pick_id}: each try needs a unique id (not 'none'): {found}")
        if not _text(found.get("path"), 1000):
            raise PickError(f"{pick_id}: try {try_id} has no path")
        seen.add(try_id)
        tries.append({"id": try_id, "label": _text(found.get("label"), 120) or f"Try {try_id}",
                      "path": _text(found.get("path"), 1000), "note": _text(found.get("note"), 400)})
    if not tries:
        raise PickError(f"{pick_id} has no tries to pick from")
    if len(tries) > MAX_TRIES:
        raise PickError(f"{pick_id} has more than {MAX_TRIES} tries")
    return {"id": pick_id, "title": _text(item.get("title"), 200) or pick_id, "kind": kind,
            "inUse": _text(item.get("inUse"), 1000) or None, "tries": tries, "context": _text(item.get("context")),
            "from": _text(item.get("from"), 400), "asked": _text(item.get("asked"), 40)}


def read_file(root):
    """(grounds, picks) from config/picks.json, checked; ([], []) without one. Raises on a malformed one."""
    path = Path(root) / CONFIG
    if not path.is_file():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise PickError(f"{path} could not be read: {error}") from None
    if not isinstance(data, dict):
        raise PickError(f"{path} is not a picks file")
    grounds = []
    for ground in (data.get("grounds") or [])[:MAX_GROUNDS]:
        if isinstance(ground, dict) and _text(ground.get("name"), 60) and COLOUR.match(str(ground.get("colour", ""))):
            grounds.append({"name": _text(ground["name"], 60), "colour": ground["colour"].upper()})
    picks, seen = [], set()
    for item in data.get("picks") or []:
        pick = check_pick(item, f"{path}: a pick")
        if pick["id"] in seen:
            raise PickError(f"{path}: {pick['id']} is offered twice")
        seen.add(pick["id"])
        picks.append(pick)
    return grounds, picks


def write_file(root, grounds, picks):
    path = Path(root) / CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schemaVersion": SCHEMA_VERSION, "grounds": grounds, "picks": picks}
    partial = path.with_suffix(".json.partial")
    partial.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    partial.replace(path)


def read_answers(path):
    """{pick id: the last answer for it}; lines that cannot be read are skipped."""
    found = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            answer = json.loads(line)
        except ValueError:
            continue
        if isinstance(answer, dict) and isinstance(answer.get("id"), str) and isinstance(answer.get("pick"), str):
            found[answer["id"]] = {"pick": answer["pick"], "words": _text(answer.get("words"), MAX_WORDS),
                                   "time": _text(answer.get("time"), 40)}
    return found


def listed(root, environ=None):
    """The repository's grounds and picks, waiting ones first; each file made absolute with whether it is there, and any answer."""
    grounds, picks = read_file(root)
    answers = read_answers(answers_file(root, environ))
    found = []
    for pick in picks:
        in_use = _path(root, pick["inUse"])
        tries = []
        for item in pick["tries"]:
            path = _path(root, item["path"])
            tries.append({**item, "path": str(path), "there": path.is_file()})
        found.append({**pick, "inUse": str(in_use) if in_use else None, "inUseThere": bool(in_use and in_use.is_file()),
                      "tries": tries, "answer": answers.get(pick["id"])})
    return grounds, sorted(found, key=lambda p: p["answer"] is not None)


def answer(root, pick_id, pick, words=None, environ=None, now=None):
    """Appends the owner's pick; refuses an unknown pick or try. Returns the answer."""
    found = next((p for p in read_file(root)[1] if p["id"] == pick_id), None)
    if found is None:
        raise PickError(f"{Path(root).resolve().name} has no waiting pick {pick_id!r}")
    if pick != NONE and pick not in [t["id"] for t in found["tries"]]:
        raise PickError(f"{pick!r} is not one of {pick_id}'s tries")
    line = {"format": ANSWER_FORMAT, "id": pick_id, "pick": pick, "words": _text(words, MAX_WORDS),
            "time": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")}
    path = answers_file(root, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def offer(root, item, grounds=None):
    """Adds one waiting pick, or replaces the one with its id (tries made again); grounds, when given, replace the file's. For a
    repository's art tools. Returns the pick as kept."""
    pick = check_pick(item)
    pick["asked"] = pick["asked"] or datetime.now(timezone.utc).date().isoformat()
    kept_grounds, picks = read_file(root)
    if grounds is not None:
        kept_grounds = [g for g in grounds if isinstance(g, dict) and COLOUR.match(str(g.get("colour", "")))][:MAX_GROUNDS]
    picks = [p for p in picks if p["id"] != pick["id"]] + [pick]
    write_file(root, kept_grounds, picks)
    return pick


def settle(root, pick_id):
    """Removes a pick once its answer is applied; refuses one not waiting."""
    grounds, picks = read_file(root)
    if not any(p["id"] == pick_id for p in picks):
        raise PickError(f"{Path(root).resolve().name} has no waiting pick {pick_id!r}")
    write_file(root, grounds, [p for p in picks if p["id"] != pick_id])


def _parser():
    p = argparse.ArgumentParser(prog="picks", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("list", help="every pick, waiting ones first, with any answer")
    s.add_argument("--root", action="append", default=[], help="a repository (repeatable; default: the current folder)")
    a = sub.add_parser("answer", help="records the owner's pick")
    a.add_argument("--root", required=True, help="the repository the pick belongs to")
    a.add_argument("--id", required=True, help="the pick")
    a.add_argument("--pick", required=True, help="the chosen try's id, or 'none' (say why with --words)")
    a.add_argument("--words", help="anything the owner added")
    o = sub.add_parser("offer", help="adds or replaces one waiting pick")
    o.add_argument("--root", required=True, help="the repository")
    o.add_argument("--file", required=True, help="a JSON file holding one pick, as config/picks.json holds them")
    t = sub.add_parser("settle", help="removes a pick once its answer is applied")
    t.add_argument("--root", required=True, help="the repository")
    t.add_argument("--id", required=True, help="the pick")
    for parser in (s, a, o, t):
        parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()

    def write(report, data):
        out.write((envelope_text("picks", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")

    try:
        if args.report == "answer":
            line = answer(args.root, args.id, args.pick, args.words, environ)
            write(Report(f"Picked: {args.id}, {line['pick']}"), {"ok": True, "answer": line})
            return EXIT_OK
        if args.report == "offer":
            try:
                item = json.loads(Path(args.file).read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise PickError(f"{args.file} could not be read: {error}") from None
            pick = offer(args.root, item)
            write(Report(f"Offered: {pick['id']}, {len(pick['tries'])} tries"), {"ok": True, "pick": pick})
            return EXIT_OK
        if args.report == "settle":
            settle(args.root, args.id)
            write(Report(f"Settled: {args.id}"), {"ok": True, "id": args.id})
            return EXIT_OK
        repositories = []
        for root in args.root or ["."]:
            grounds, picks = listed(root, environ)
            repositories.append({"repository": Path(root).resolve().name, "root": str(Path(root).resolve()), "grounds": grounds,
                                 "picks": picks})
    except PickError as refused:
        write(Report("Refused"), {"ok": False, "refusal": str(refused)})
        return EXIT_REFUSED
    waiting = sum(1 for r in repositories for p in r["picks"] if p["answer"] is None)
    report = Report(f"Picks: {waiting} waiting")
    for repository in repositories:
        if repository["picks"]:
            report.section(repository["repository"], Bullets([
                f"{p['id']}: {p['title']} ({p['kind']}, {len(p['tries'])} tries)"
                + (f" PICKED {p['answer']['pick']}" if p["answer"] else " waiting") for p in repository["picks"]]))
    write(report, {"waiting": waiting, "repositories": repositories})
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "Which pictures and sounds are waiting for the owner to pick one?",
                                 "surface": "picks"},
                        "answer": {"effect": WRITES, "surface": "picks", "note": "appends the owner's pick to the Companion's picks file"},
                        "offer": {"effect": WRITES, "note": "adds a waiting pick to the repository's config/picks.json"},
                        "settle": {"effect": WRITES, "note": "removes an applied pick from the repository's config/picks.json"}}}
