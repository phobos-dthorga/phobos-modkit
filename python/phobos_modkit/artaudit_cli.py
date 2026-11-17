"""art-audit: every shipped image paired with its record and classed by how it was made, and every borrowed picture.

    art-audit report --root REPO                 images drawn in code, without a record or unclassed; borrowed pictures
    art-audit report --root REPO --mod "X*"      one mod or folder (wildcards)
    art-audit report --root REPO --kind code-drawn --all    every image of one kind, accepted ones too
    art-audit check --root REPO                  fails when an image has no record (for a gate)

The repository's config/art-audit.json names where its images are, the record suffixes, the kinds and the patterns that tell
them apart, what calls an image a stand-in, the game whose adapter reads Defs and code, and accepted images and borrowings
with their reasons. It reads only; nothing is cached.
"""
from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
from pathlib import Path
import sys

from . import artaudit
from .manifest import READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="art-audit", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("report", "images drawn in code, without a record or unclassed, and borrowed pictures"),
                           ("check", "fail when an image has no record of its own or shared")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--root", help="the repository (default: the current folder)")
        s.add_argument("--mod", help="only images and uses in this mod or folder (wildcards * and ?)")
        if name == "report":
            s.add_argument("--kind", help="list every image of this kind (a kind the config names, no-record or unclassified)")
            s.add_argument("--all", action="store_true", help="list accepted images and borrowings beside the open ones")
            s.add_argument("--top", type=int, default=40, help="rows per table (default 40)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _short(image):
    """The image's path below its group's folder, which is what a person looks for."""
    marker = f"/{image.group}/" if image.group else ""
    at = image.path.find(marker) if marker else -1
    return image.path[at + len(marker):] if at >= 0 else image.path


def _count(items, noun):
    return f"{len(items):,} {noun}" + ("" if len(items) == 1 else "s")


def _in_group(value, pattern):
    return pattern is None or fnmatchcase(value.lower(), pattern.lower())


def _image_rows(images, top, with_reason=False):
    rows = []
    for image in images[:top]:
        row = [image.group, _short(image), image.evidence or image.stand_in]
        if with_reason:
            row.append(image.accepted)
        rows.append(row)
    return rows


def _use_owner(use):
    owner = f"{use.owner_type} {use.owner}"
    if use.part:
        owner += f" ({use.part})"
    if use.inherited_from:
        owner += f", from {use.inherited_from}"
    return owner


def _use_rows(uses, top, with_reason=False):
    rows = []
    for use in uses[:top]:
        source = ", ".join(use.owners) if use.status == artaudit.BORROWED else "not one of ours"
        row = [_use_owner(use), use.texture, source, use.file]
        if with_reason:
            row[3] = use.accepted
        rows.append(row)
    return rows


def _dedupe(uses):
    """One row per owner, picture and file: a Def that names one picture in several fields is one borrowing."""
    seen, found = set(), []
    for use in uses:
        key = (use.owner_type, use.owner, use.part, use.texture.lower(), use.file, use.inherited_from)
        if key not in seen:
            seen.add(key)
            found.append(use)
    return found


def build_report(result, mod=None, kind=None, everything=False, top=40):
    images = [i for i in result.images if _in_group(i.group, mod)]
    uses = [u for u in result.uses if _in_group(u.group, mod)]
    labels = {artaudit.UNCLASSIFIED: "Unclassified", artaudit.NO_RECORD: "No record", **{k.kind: k.label for k in result.kinds}}
    open_images = [i for i in images if not i.accepted]
    listed_kinds = [k for k in result.kinds if k.listed]
    listed = {k.kind: [i for i in open_images if i.kind == k.kind] for k in listed_kinds}
    in_listed = sum(len(v) for v in listed.values())
    no_record = [i for i in images if i.kind == artaudit.NO_RECORD and not i.accepted]
    unclassed = [i for i in open_images if i.kind == artaudit.UNCLASSIFIED]
    called = [i for i in open_images if i.stand_in and i.kind not in listed and i.kind != artaudit.NO_RECORD]
    borrowed = _dedupe(u for u in uses if u.status in (artaudit.BORROWED, artaudit.NOT_OURS))
    open_borrowed = [u for u in borrowed if not u.accepted]
    accepted_borrowed = [u for u in borrowed if u.accepted]
    accepted_images = [i for i in images if i.accepted]

    report = Report(f"Art audit: {len(images):,} images; {in_listed:,} " + " or ".join(k.label.lower() for k in listed_kinds)
                    + f", {len(no_record):,} without a record, {len(open_borrowed):,} borrowed pictures open")
    counts = {}
    for image in images:
        counts[image.kind] = counts.get(image.kind, 0) + 1
    order = [k.kind for k in result.kinds] + [artaudit.UNCLASSIFIED, artaudit.NO_RECORD]
    report.lines.append("; ".join(f"{labels.get(k, k)}: {counts[k]:,}" for k in order if counts.get(k)) + ".")
    paired = {}
    for image in images:
        if image.paired_by:
            paired[image.paired_by] = paired.get(image.paired_by, 0) + 1
    if paired:
        report.lines.append(f"Records: {paired.get('own', 0):,} of their own, {paired.get('prefix', 0):,} shared by the name "
                            f"before an underscore, {paired.get('folder', 0):,} named after the folder.")
    if result.game:
        report.lines.append(f"{len(uses):,} uses of pictures read from Defs and code; {_count(accepted_borrowed, 'borrowing')} "
                            f"and {_count(accepted_images, 'image')} accepted as they are, with reasons.")
    if mod:
        report.lines.append(f"Only {mod}.")

    if kind:
        chosen = [i for i in images if i.kind == kind and (everything or not i.accepted)]
        report.section(f"Every image of kind {labels.get(kind, kind)}", Table(
            ["Mod", "Image", "Record says", "Accepted"], _image_rows(chosen, top, True), total=len(chosen)))
    else:
        for k in listed_kinds:
            report.section(k.label, Table(["Mod", "Image", "Record says"], _image_rows(listed[k.kind], top),
                                          total=len(listed[k.kind])))
        if called:
            report.section("Called a stand-in, made another way", Table(
                ["Mod", "Image", "Record says"], [[i.group, _short(i), i.stand_in] for i in called[:top]], total=len(called)))
        report.section("No record", Table(["Mod", "Image", "Record says"], _image_rows(no_record, top), total=len(no_record)))
        if unclassed:
            report.section("A record no rule recognises", Table(
                ["Mod", "Image", "Record"], [[i.group, _short(i), ", ".join(i.records)] for i in unclassed[:top]],
                total=len(unclassed)))
    if result.game:
        report.section("Borrowed pictures, open", Table(
            ["Used by", "Picture", "Belongs to", "File"], _use_rows(open_borrowed, top), total=len(open_borrowed)))
        if everything and accepted_borrowed:
            report.section("Borrowed pictures, accepted", Table(
                ["Used by", "Picture", "Belongs to", "Why"], _use_rows(accepted_borrowed, top, True), total=len(accepted_borrowed)))
    if everything and accepted_images and not kind:
        report.section("Images accepted as they are", Table(
            ["Mod", "Image", "Record says", "Why"], _image_rows(accepted_images, top, True), total=len(accepted_images)))
    by_group = {}
    for image in images:
        row = by_group.setdefault(image.group or "(none)", {})
        row[image.kind] = row.get(image.kind, 0) + 1
    columns = [k for k in order if counts.get(k)]
    report.section("By mod", Table(["Mod", "Images"] + [labels.get(k, k) for k in columns],
                                   [[g, sum(c.values())] + [c.get(k, 0) for k in columns] for g, c in sorted(by_group.items())]))
    notes = list(result.limits)
    if result.unreadable:
        notes.append(f"{_count(result.unreadable, 'file')} could not be read: " + "; ".join(result.unreadable[:5]) + ".")
    if not everything and (accepted_borrowed or accepted_images):
        notes.append("Accepted images and borrowings are left out; --all lists them with their reasons.")
    if notes:
        report.section("Limits", Bullets(notes))
    return report


def check_report(result, mod=None):
    images = [i for i in result.images if _in_group(i.group, mod) and i.kind == artaudit.NO_RECORD and not i.accepted]
    report = Report(f"Art records: {len(images):,} images without a record" if images else "Art records: every image has a record")
    if images:
        report.lines.append("Write a record beside each (how it was made, from what, and its hash), or accept it in "
                            "config/art-audit.json with a reason.")
        report.section("No record", Table(["Mod", "Image"], [[i.group, _short(i)] for i in images]))
    return report, bool(images)


def _image_data(image):
    return {"path": image.path, "group": image.group, "names": image.names, "records": image.records,
            "paired_by": image.paired_by, "kind": image.kind, "evidence": image.evidence, "stand_in": image.stand_in,
            "accepted": image.accepted}


def _use_data(use):
    return {"owner_type": use.owner_type, "owner": use.owner, "part": use.part, "field": use.field, "texture": use.texture,
            "file": use.file, "inherited_from": use.inherited_from, "images": use.images, "status": use.status,
            "owners": use.owners, "accepted": use.accepted}


def main(argv=None, out=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    root = Path(args.root or ".").resolve()
    try:
        config = artaudit.load_config(root)
        result = artaudit.audit(root, config)
    except artaudit.ArtAuditError as error:
        print(redact(str(error)), file=sys.stderr)
        return EXIT_USAGE
    failed = False
    if args.report == "check":
        report, failed = check_report(result, args.mod)
    else:
        known = {k.kind for k in result.kinds} | {artaudit.UNCLASSIFIED, artaudit.NO_RECORD}
        if args.kind and args.kind not in known:
            print(f"Unknown kind {args.kind}; the config names: {', '.join(sorted(known))}.", file=sys.stderr)
            return EXIT_USAGE
        report = build_report(result, args.mod, args.kind, args.all, args.top)
    data = {"game": result.game, "images": [_image_data(i) for i in result.images if _in_group(i.group, args.mod)],
            "uses": [_use_data(u) for u in result.uses if _in_group(u.group, args.mod)]}
    out.write((envelope_text("art-audit", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_FAILED if failed else EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"report": {"question": "Which shipped pictures are drawn in code, unrecorded or borrowed?"},
                        "check": {"question": "Does every shipped picture have a record?"}}}
