"""picks: the pictures and sounds waiting for the owner to pick one, each with its tries, and the owner's picks (1.83.0).

    picks list --root REPO [--root REPO ...]                          every pick, waiting ones first, with any answer
    picks answer --root REPO --id ID --pick TRY [--words W]           records the owner's pick (TRY is a try's id, or "none")
    picks offer --root REPO --file PICK.json                          adds or replaces one waiting pick (for a repository's art tools)
    picks settle --root REPO --id ID                                  removes a pick once its answer is applied
    picks settle --root REPO --applied                                removes every answered pick whose try is in the game

Round two (1.125.0; the owner's answers of 23 Nov 2026 on D'thorga Companion's Decisions page): cards that ship as the same file
carry the same `slot` (that file, relative to the repository) and are **one pick**, so answering one answers them all; a pick
whose picked try is the file in use, byte for byte, is **in the game** and is settled by itself (`--applied`); `list` with no
`--root` reads **every repository on the games list**, and says which; `settle` says what it settled and with which answer.

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
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from . import file_lock, games_list
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
    slot = _text(item.get("slot"), 400) or None
    if slot is not None and (Path(slot).is_absolute() or ".." in Path(slot).parts or ":" in slot):
        raise PickError(f"{pick_id}: its slot is the file it ships as, inside the repository, not {slot!r}")
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
    picked = {"id": pick_id, "title": _text(item.get("title"), 200) or pick_id, "kind": kind,
              "inUse": _text(item.get("inUse"), 1000) or None, "tries": tries, "context": _text(item.get("context")),
              "from": _text(item.get("from"), 400), "asked": _text(item.get("asked"), 40)}
    if slot is not None:
        picked["slot"] = slot.replace("\\", "/")
    return picked


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
    # Retried while another program holds the file a moment (1.103.1: the Companion or a sync reading it refused the swap, and an
    # art tool's offers stopped part-way).
    file_lock.patiently(lambda: partial.replace(path))


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


def _digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def in_game(root, pick, answer):
    """Whether a pick's answer is applied: its picked try's file is the file in use, byte for byte (1.125.0)."""
    if not answer or answer.get("pick") in (None, NONE):
        return False
    in_use = _path(root, pick.get("inUse"))
    chosen = next((t for t in pick["tries"] if t["id"] == answer["pick"]), None)
    tried = _path(root, chosen["path"]) if chosen else None
    if not (in_use and tried and in_use.is_file() and tried.is_file()):
        return False
    try:
        return in_use.stat().st_size == tried.stat().st_size and _digest(in_use) == _digest(tried)
    except OSError:
        return False


def listed(root, environ=None):
    """The repository's grounds and picks, waiting ones first; each file made absolute with whether it is there, any answer, and
    whether that answer is already in the game."""
    grounds, picks = read_file(root)
    answers = read_answers(answers_file(root, environ))
    found = []
    for pick in picks:
        in_use = _path(root, pick["inUse"])
        tries = []
        for item in pick["tries"]:
            path = _path(root, item["path"])
            tries.append({**item, "path": str(path), "there": path.is_file()})
        given = answers.get(pick["id"])
        found.append({**pick, "inUse": str(in_use) if in_use else None, "inUseThere": bool(in_use and in_use.is_file()),
                      "tries": tries, "answer": given, "inGame": in_game(root, pick, given)})
    return grounds, sorted(found, key=lambda p: p["answer"] is not None)


def answer(root, pick_id, pick, words=None, environ=None, now=None):
    """Appends the owner's pick; refuses an unknown pick or try. Returns the answer."""
    found = next((p for p in read_file(root)[1] if p["id"] == pick_id), None)
    if found is None:
        raise PickError(f"{Path(root).resolve().name} has no waiting pick {pick_id!r}")
    if pick != NONE and pick not in [t["id"] for t in found["tries"]]:
        raise PickError(f"{pick!r} is not one of {pick_id}'s tries")
    time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    line = {"format": ANSWER_FORMAT, "id": pick_id, "pick": pick, "words": _text(words, MAX_WORDS), "time": time}
    lines = [line]
    # One pick per file (1.125.0): the other cards of the same slot are answered with it, as not the one shipped.
    if found.get("slot"):
        line["slot"] = found["slot"]
        for other in read_file(root)[1]:
            if other["id"] != pick_id and other.get("slot") == found["slot"]:
                said = (f"The same file was picked in {pick_id}: {pick}" if pick != NONE else (_text(words, MAX_WORDS) or
                        f"None of the tries for {found['slot']}"))
                lines.append({"format": ANSWER_FORMAT, "id": other["id"], "pick": NONE, "words": said, "time": time,
                              "slot": found["slot"], "by": pick_id})
    path = answers_file(root, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        for written in lines:
            handle.write(json.dumps(written, ensure_ascii=False) + "\n")
    line["alsoAnswered"] = [written["id"] for written in lines[1:]]
    return line


def offer(root, item, grounds=None):
    """Adds one waiting pick, or replaces the one with its id (tries made again); grounds, when given, replace the file's. For a
    repository's art tools. Refuses to replace a pick of the other kind (a sound under a picture's id). Returns the pick as kept."""
    pick = check_pick(item)
    pick["asked"] = pick["asked"] or datetime.now(timezone.utc).date().isoformat()
    kept_grounds, picks = read_file(root)
    other = next((p for p in picks if p["id"] == pick["id"] and p["kind"] != pick["kind"]), None)
    if other is not None:
        # 1.103.1: a sound offered under a picture's id replaced the picture, which then never reached the owner.
        raise PickError(f"{pick['id']} is already waiting as a {other['kind']}; a {pick['kind']} needs an id of its own")
    if grounds is not None:
        kept_grounds = [g for g in grounds if isinstance(g, dict) and COLOUR.match(str(g.get("colour", "")))][:MAX_GROUNDS]
    picks = [p for p in picks if p["id"] != pick["id"]] + [pick]
    write_file(root, kept_grounds, picks)
    return pick


def settle(root, pick_id, environ=None):
    """Removes a pick once its answer is applied; refuses one not waiting, saying so. Returns the answer it was settled with, or
    None when none was recorded (1.125.0: a settle used to say nothing)."""
    grounds, picks = read_file(root)
    if not any(p["id"] == pick_id for p in picks):
        raise PickError(f"{Path(root).resolve().name} has no waiting pick {pick_id!r}: it is settled already, or was never offered")
    write_file(root, grounds, [p for p in picks if p["id"] != pick_id])
    return read_answers(answers_file(root, environ)).get(pick_id)


def settle_applied(root, environ=None):
    """Settles every answered pick that is in the game (1.125.0; the owner's choice: "Settle it by itself"), and the other cards
    of its slot. Returns [(id, answer)] for each settled."""
    grounds, picks = read_file(root)
    answers = read_answers(answers_file(root, environ))
    applied = {p["id"] for p in picks if in_game(root, p, answers.get(p["id"]))}
    slots = {p["slot"] for p in picks if p["id"] in applied and p.get("slot")}
    gone = {p["id"] for p in picks if p["id"] in applied or (p.get("slot") in slots and answers.get(p["id"]))}
    if gone:
        write_file(root, grounds, [p for p in picks if p["id"] not in gone])
    return [(pick_id, answers.get(pick_id)) for pick_id in sorted(gone)]


def roots_to_read(given, environ=None):
    """The repositories `list` reads: those named; else every one on the games list (1.125.0), else the current folder. Returns
    (roots, where they came from)."""
    if given:
        return list(given), "named"
    try:
        listed_roots = [entry.folder for entry in games_list.entries(games_list.games_file(None, environ))]
    except games_list.GamesListError:
        listed_roots = []
    return (listed_roots, "games list") if listed_roots else (["."], "this folder")


def _parser():
    p = argparse.ArgumentParser(prog="picks", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("list", help="every pick, waiting ones first, with any answer")
    s.add_argument("--root", action="append", default=[],
                   help="a repository (repeatable; default: every repository on the games list, else the current folder)")
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
    t.add_argument("--id", help="the pick (or --applied)")
    t.add_argument("--applied", action="store_true", help="every answered pick whose try is in the game, byte for byte")
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
            report = Report(f"Picked: {args.id}, {line['pick']}")
            if line["alsoAnswered"]:
                report.lines.append(f"The same file's other cards are answered with it: {', '.join(line['alsoAnswered'])}.")
            write(report, {"ok": True, "answer": line})
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
            if args.applied:
                settled = settle_applied(args.root, environ)
                report = Report(f"Settled {len(settled)} picks already in the game" if settled else "Nothing to settle: no "
                                "answered pick is in the game yet")
                report.lines.extend(f"Settled {pick_id} ({_answer_words(given)})" for pick_id, given in settled)
                write(report, {"ok": True, "settled": [pick_id for pick_id, _ in settled]})
                return EXIT_OK
            if not args.id:
                raise PickError("name the pick with --id, or settle every one in the game with --applied")
            given = settle(args.root, args.id, environ)
            write(Report(f"Settled {args.id} ({_answer_words(given)})"), {"ok": True, "id": args.id, "answer": given})
            return EXIT_OK
        roots, came_from = roots_to_read(args.root, environ)
        repositories = []
        for root in roots:
            grounds, picks = listed(root, environ)
            repositories.append({"repository": Path(root).resolve().name, "root": str(Path(root).resolve()), "grounds": grounds,
                                 "picks": picks, "hasFile": (Path(root) / CONFIG).is_file()})
    except PickError as refused:
        # 1.125.0: the reason in the title too, so a refused settle never says only "Refused".
        write(Report(f"Refused: {refused}"), {"ok": False, "refusal": str(refused)})
        return EXIT_REFUSED
    waiting = sum(1 for r in repositories for p in r["picks"] if p["answer"] is None)
    report = Report(f"Picks: {waiting} waiting")
    report.lines.append(f"Read from {came_from}: " + ", ".join(
        r["repository"] + ("" if r["hasFile"] else " (no config/picks.json)") for r in repositories) + ".")
    for repository in repositories:
        if repository["picks"]:
            # The owner's words with the pick (1.123.1): a "none" with a reason, or a wish beside a pick, was read by nobody.
            report.section(repository["repository"], Bullets([
                f"{p['id']}: {p['title']} ({p['kind']}, {len(p['tries'])} tries)"
                + (f" [slot {p['slot']}]" if p.get("slot") else "")
                + (f" PICKED {p['answer']['pick']}" if p["answer"] else " waiting")
                + (" IN THE GAME" if p.get("inGame") else "")
                + (f': "{p["answer"]["words"]}"' if p["answer"] and p["answer"].get("words") else "") for p in repository["picks"]]))
    write(report, {"waiting": waiting, "readFrom": came_from, "repositories": repositories})
    return EXIT_OK


def _answer_words(given):
    if not given:
        return "no answer was recorded"
    return "none of the tries" if given["pick"] == NONE else f"picked {given['pick']}"


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "Which pictures and sounds are waiting for the owner to pick one?",
                                 "surface": "picks"},
                        "answer": {"effect": WRITES, "surface": "picks", "note": "appends the owner's pick to the Companion's picks file"},
                        "offer": {"effect": WRITES, "note": "adds a waiting pick to the repository's config/picks.json"},
                        "settle": {"effect": WRITES, "surface": "picks",
                                   "note": "removes an applied pick, or with --applied every one in the game, from the repository's "
                                           "config/picks.json"}}}
