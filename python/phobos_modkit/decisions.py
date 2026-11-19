"""decisions: the questions waiting for the owner, each with its options and the agent's lean, and the owner's answers (1.45.0).

    decisions list --root REPO [--root REPO ...]                    every decision, open ones first, with any answer
    decisions answer --root REPO --id ID --option OPTION [--words W]   records the owner's answer

A repository lists its open decisions in config/decisions.json; an agent adds one whenever it makes a choice the owner should be
able to revise, or needs the owner's word to go on. The owner answers on D'thorga Companion's Decisions page (or in conversation,
and an agent records it with `answer`). Answers are appended, one JSON line each, to a file per repository in the Companion's folder
(companionDecisionsPath, PHOBOS_DECISIONS); the last line for a decision decides, so an answer can be changed. **An agent acts on an
answer and removes the decision from config/decisions.json in the same commit**, so the list holds only what still waits.

config/decisions.json:

    {"schemaVersion": 1, "decisions": [
      {"id": "page-keys", "question": "Renumber the page keys to follow the grouped bar?",
       "context": "The bar is now grouped; the keys still follow the old order.",
       "options": [{"id": "renumber", "label": "Renumber them", "detail": "1 to 9 in the bar's order"},
                   {"id": "keep", "label": "Keep them", "detail": "No key changes"}],
       "lean": "renumber", "why": "The number keys would match what you see", "from": "docs/design-record.md", "asked": "2026-11-19"}]}

Every decision may also be answered "other", with words.
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
ANSWERS = ("companionDecisionsPath", "PHOBOS_DECISIONS")
CONFIG = Path("config") / "decisions.json"
SCHEMA_VERSION = 1
ANSWER_FORMAT = 1
OTHER = "other"
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
MAX_TEXT = 2000
MAX_WORDS = 4000


class DecisionError(ValueError):
    """A request or a config this command refuses, with the reason in words."""


def answers_file(root, environ=None):
    """The owner's answers for a repository: companionDecisionsPath (a folder), else decisions/<repository>.jsonl in the Companion's
    folder."""
    folder = resolve(*ANSWERS, companion_data(environ) / "decisions", None, environ)
    return Path(folder) / f"{Path(root).resolve().name}.jsonl"


def _text(value, limit=MAX_TEXT):
    return value.strip()[:limit] if isinstance(value, str) else ""


def read_config(root):
    """The repository's decisions, checked; [] without config/decisions.json. Raises on a malformed one."""
    path = Path(root) / CONFIG
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise DecisionError(f"{path} could not be read: {error}") from None
    found, seen = [], set()
    for item in data.get("decisions", []) if isinstance(data, dict) else []:
        decision_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(decision_id, str) or not ID.match(decision_id) or decision_id in seen:
            raise DecisionError(f"{path}: a decision needs a unique id of lower-case letters, digits and hyphens: {item}")
        options = item.get("options") or []
        option_ids = [o.get("id") for o in options if isinstance(o, dict)]
        if len(option_ids) < 2 or len(set(option_ids)) != len(option_ids) or not all(
                isinstance(o, str) and ID.match(o) and o != OTHER for o in option_ids):
            raise DecisionError(f"{path}: {decision_id} needs two or more options with unique ids (not 'other')")
        lean = item.get("lean")
        if lean is not None and lean not in option_ids:
            raise DecisionError(f"{path}: {decision_id}'s lean {lean!r} is not one of its options")
        if not _text(item.get("question")):
            raise DecisionError(f"{path}: {decision_id} has no question")
        seen.add(decision_id)
        found.append({"id": decision_id, "question": _text(item.get("question")), "context": _text(item.get("context")),
                      "options": [{"id": o["id"], "label": _text(o.get("label"), 200) or o["id"],
                                   "detail": _text(o.get("detail"))} for o in options],
                      "lean": lean, "why": _text(item.get("why")), "from": _text(item.get("from"), 400),
                      "asked": _text(item.get("asked"), 40)})
    return found


def read_answers(path):
    """{decision id: the last answer for it}; lines that cannot be read are skipped."""
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
        if isinstance(answer, dict) and isinstance(answer.get("id"), str) and isinstance(answer.get("option"), str):
            found[answer["id"]] = {"option": answer["option"], "words": _text(answer.get("words"), MAX_WORDS),
                                   "time": _text(answer.get("time"), 40)}
    return found


def listed(root, environ=None):
    """The repository's decisions, open ones first, each with the owner's answer or None."""
    answers = read_answers(answers_file(root, environ))
    found = [{**d, "answer": answers.get(d["id"])} for d in read_config(root)]
    return sorted(found, key=lambda d: d["answer"] is not None)


def answer(root, decision_id, option, words=None, environ=None, now=None):
    """Appends the owner's answer; refuses an unknown decision or option, and "other" without words. Returns the answer."""
    decision = next((d for d in read_config(root) if d["id"] == decision_id), None)
    if decision is None:
        raise DecisionError(f"{Path(root).resolve().name} has no open decision {decision_id!r}")
    words = _text(words, MAX_WORDS)
    if option != OTHER and option not in [o["id"] for o in decision["options"]]:
        raise DecisionError(f"{option!r} is not one of {decision_id}'s options")
    if option == OTHER and not words:
        raise DecisionError("say what you would like instead (--words)")
    line = {"format": ANSWER_FORMAT, "id": decision_id, "option": option, "words": words,
            "time": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")}
    path = answers_file(root, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def _parser():
    p = argparse.ArgumentParser(prog="decisions", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("list", help="every decision, open ones first, with any answer")
    s.add_argument("--root", action="append", default=[], help="a repository (repeatable; default: the current folder)")
    a = sub.add_parser("answer", help="records the owner's answer")
    a.add_argument("--root", required=True, help="the repository the decision belongs to")
    a.add_argument("--id", required=True, help="the decision")
    a.add_argument("--option", required=True, help="the chosen option's id, or 'other' with --words")
    a.add_argument("--words", help="anything the owner added")
    for parser in (s, a):
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
        out.write((envelope_text("decisions", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")

    try:
        if args.report == "answer":
            line = answer(args.root, args.id, args.option, args.words, environ)
            write(Report(f"Answered: {args.id}, {line['option']}"), {"ok": True, "answer": line})
            return EXIT_OK
        repositories = []
        for root in args.root or ["."]:
            repositories.append({"repository": Path(root).resolve().name, "root": str(Path(root).resolve()),
                                 "decisions": listed(root, environ)})
    except DecisionError as refused:
        write(Report("Refused"), {"ok": False, "refusal": str(refused)})
        return EXIT_REFUSED
    waiting = sum(1 for r in repositories for d in r["decisions"] if d["answer"] is None)
    report = Report(f"Decisions: {waiting} waiting")
    for repository in repositories:
        if not repository["decisions"]:
            continue
        lines = []
        for d in repository["decisions"]:
            chosen = d["answer"]
            if chosen is None:
                lean = next((o["label"] for o in d["options"] if o["id"] == d["lean"]), None)
                lines.append(f"{d['id']}: {d['question']} (waiting" + (f"; lean: {lean})" if lean else ")"))
            else:
                label = next((o["label"] for o in d["options"] if o["id"] == chosen["option"]), chosen["option"])
                lines.append(f"{d['id']}: {d['question']} ANSWERED {label}" + (f": {chosen['words']}" if chosen["words"] else ""))
        report.section(repository["repository"], Bullets(lines))
    write(report, {"waiting": waiting, "repositories": repositories})
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "Which decisions are waiting for the owner?"},
                        "answer": {"effect": WRITES, "note": "appends the owner's answer to the Companion's decisions file"}}}
