"""Steam's BBCode: a small, deliberate Markdown subset turned into it, and a check of what a page may hold.

The subset: paragraphs, "- " bullets, "### " headings, **bold** and [label](https://...) links. Anything else
(images, tables, backticks, nested lists, raw tags) is refused rather than silently lost. ASCII double quotes become
typographic ones, because Workshop text travels inside a SteamCMD VDF string whose escapes Valve does not document.
"""
from __future__ import annotations

import re

TAGS = frozenset({"h1", "h2", "h3", "b", "i", "u", "list", "url"})
URL = re.compile(r"https?://[^\s\[\]<>]+")


class BBCodeError(ValueError):
    pass


def typographic_quotes(text):
    """An opening " after a space or bracket becomes a left quote; every other " a right quote."""
    return re.sub(r'(^|[\s(\[])"', "\\1\u201c", text).replace('"', "\u201d")


def inline(text):
    """One line of the Markdown subset as BBCode."""
    if "![" in text or any(ord(c) < 32 for c in text):
        raise BBCodeError("Images and control characters are unsupported in release text")
    if "\\" in text:
        raise BBCodeError("Backslashes are unsupported in release text")
    text = typographic_quotes(text)
    tokens = []

    def keep(value):
        tokens.append(value)
        return f"\x01{len(tokens) - 1}\x02"

    def link(match):
        label, url = match.groups()
        if not URL.fullmatch(url) or any(c in label for c in "[]<>"):
            raise BBCodeError("Changelog links need an absolute HTTP(S) URL and a plain label")
        return keep(f"[url={url}]{label}[/url]")

    def bold(match):
        if any(c in match[1] for c in "[]<>`\x01"):
            raise BBCodeError("Use plain text inside bold emphasis")
        return keep(f"[b]{match[1]}[/b]")

    text = re.sub(r"\[([^\]\n]+)\]\(([^)\n]+)\)", link, text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", bold, text)
    if any(c in text for c in "[]<>`*|#") or re.match(r"\d+\.\s", text):
        raise BBCodeError(f"Unsupported changelog formatting: {text}")
    for index, token in enumerate(tokens):
        text = text.replace(f"\x01{index}\x02", token)
    return text


def unwrap(body):
    """Lines as Markdown reads them: a hard-wrapped paragraph is one line, and an indented line straight after a
    bullet continues that bullet. An indented line anywhere else would be nesting, which stays unsupported."""
    lines = []
    for line in body.splitlines():
        previous = lines[-1] if lines else ""
        plain = previous and not previous.startswith(("- ", "### ")) and not previous.startswith((" ", "\t"))
        if line.startswith((" ", "\t")) and line.strip() and previous.startswith("- "):
            lines[-1] = previous + " " + line.strip()
        elif line and not line.startswith((" ", "\t", "- ", "### ")) and plain:
            lines[-1] = previous + " " + line
        else:
            lines.append(line)
    return lines


def render(body):
    """A changelog entry's body as BBCode."""
    output, in_list = [], False
    for line in unwrap(body):
        if line.startswith((" ", "\t")):
            raise BBCodeError(f"Indented or nested changelog content is unsupported: {line.strip()[:60]}")
        bullet = line.startswith("- ")
        if in_list and not bullet:
            output.append("[/list]")
            in_list = False
        if bullet:
            if not in_list:
                output.append("[list]")
                in_list = True
            output.append("[*]" + inline(line[2:]))
        elif line.startswith("### "):
            output.append("[h2]" + inline(line[4:]) + "[/h2]")
        else:
            output.append(inline(line) if line else "")
    if in_list:
        output.append("[/list]")
    return "\n".join(output).strip()


def validate(text):
    """Refuse unknown or unbalanced tags, attributes other than a url's, stray brackets and leftover Markdown."""
    stack = []
    for match in re.finditer(r"\[([^\]]*)\]", text):
        tag = match[1]
        if tag == "*":
            if not stack or stack[-1] != "list":
                raise BBCodeError("List item outside a list")
            continue
        closing = tag.startswith("/")
        name = tag.lstrip("/").split("=", 1)[0]
        if name not in TAGS:
            raise BBCodeError(f"Unsupported Steam tag: {tag}")
        if name == "url" and not closing:
            if not re.fullmatch(r"url=https?://[^\s\[\]<>]+", tag):
                raise BBCodeError("Steam links must use absolute HTTP(S) URLs")
        elif "=" in tag:
            raise BBCodeError(f"Unexpected tag attribute: {tag}")
        if closing:
            if not stack or stack.pop() != name:
                raise BBCodeError(f"Unbalanced Steam tag: {tag}")
        else:
            stack.append(name)
    if stack:
        raise BBCodeError("Unclosed Steam tags")
    bare = re.sub(r"\[[^\]]*\]", "", text)
    if "[" in bare or "]" in bare:
        raise BBCodeError("Unmatched Steam bracket")
    if re.search(r"(?m)^#{1,6} |\*\*|```", text):
        raise BBCodeError("Markdown found in a Steam page; use BBCode")
