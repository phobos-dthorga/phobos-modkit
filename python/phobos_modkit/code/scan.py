"""Find the namespaces, types and members in C# text, with the lines each one spans.

Two passes over a file. blank() replaces every comment, and the inside of every string and character literal, with
spaces, keeping newlines and quotes, so braces and semicolons left in the text are real ones. declarations() then walks
the braces and semicolons line by line. At file, namespace and type level, the text between them is a declaration's
header: a "{" opens its body (a type, or a member's block), a ";" ends a declaration without one (a field, an
expression-bodied member, a file-scoped namespace). A header holding "=>" or an assignment waits for its ";", so the
braces of an initialiser or a lambda are not taken for a body. Inside a member nothing is read.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

MODIFIERS = (r"(?:(?:public|private|protected|internal|static|abstract|sealed|partial|readonly|unsafe|new|virtual|"
             r"override|extern|async|const|volatile|required|file|ref|implicit|explicit)\s+)*")
ATTRIBUTES = re.compile(r"^\s*(?:\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]\s*)+")
NAMESPACE = re.compile(r"^namespace\s+(?P<name>[\w.]+)")
TYPE = re.compile(r"^" + MODIFIERS + r"(?P<kind>class|struct|interface|enum|record(?:\s+(?:class|struct))?)\s+"
                  r"(?P<name>@?\w+)")
DELEGATE = re.compile(r"^" + MODIFIERS + r"delegate\s+.+?\b(?P<name>\w+)\s*(?:<[^()]*>)?\s*\(")
OPERATOR = re.compile(r"\boperator\s*(?P<op>[^\s(]+)\s*\(")
INDEXER = re.compile(r"\bthis\s*\[")
EVENT = re.compile(r"\bevent\b")
CALLABLE = re.compile(r"(?P<name>~?@?\w+)\s*(?:<[^()]*>)?\s*\(")
IDENTIFIER = re.compile(r"@?\w+")
TOKENS = re.compile(r"[{};]")
MODIFIER_WORDS = frozenset({"public", "private", "protected", "internal", "static", "abstract", "sealed", "partial",
                            "readonly", "unsafe", "virtual", "override", "extern", "async", "const", "volatile",
                            "required", "file", "ref", "implicit", "explicit", "delegate", "event", "out", "in",
                            "params"})
ASSIGNMENT = re.compile(r"(?<![=!<>])=(?![=>])")
NOT_A_NAME = MODIFIER_WORDS | frozenset({"if", "for", "foreach", "while", "switch", "using", "lock", "return", "new", "typeof",
                        "sizeof", "nameof", "default", "catch", "fixed", "checked", "unchecked", "base", "this", "get",
                        "set", "init", "add", "remove", "where", "case", "else"})
HARD_KEYWORDS = frozenset({"if", "for", "foreach", "while", "switch", "using", "lock", "return", "new", "typeof",
                           "sizeof", "nameof", "default", "catch", "fixed", "checked", "unchecked", "base", "this",
                           "case", "else", "public", "private", "protected", "internal", "static", "abstract", "sealed",
                           "readonly", "virtual", "override", "extern", "const", "volatile", "ref", "out", "in", "params",
                           "event", "delegate", "implicit", "explicit", "unsafe", "class", "struct", "interface", "enum"})
SIGNATURE_LIMIT = 240
DECOMPILER_NOTE = re.compile(r"^\s*//IL_[0-9A-Fa-f]+:")


def _open_brackets(text):
    """Whether a ( or [ is still open in text: a { then is inside an expression (an attribute's new[] { }), not a body."""
    depth = 0
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
    return depth > 0


@dataclass
class Declaration:
    kind: str           # namespace, class, struct, interface, enum, record, delegate, method, constructor, property, field,
                        # event, indexer, operator
    name: str
    owner: str          # the enclosing type's full name, or the namespace
    signature: str
    start: int          # first line, attributes included
    end: int

    @property
    def full(self):
        return f"{self.owner}.{self.name}" if self.owner else self.name


def _is_string_start(text, i):
    """Whether a string literal starts at i: a quote, or $ and @ prefixes (in either order) before one."""
    j = i
    while j < len(text) and j - i < 3 and text[j] in "$@":
        j += 1
    return j < len(text) and text[j] == '"' and (j == i or text[i] in "$@")


def _char_end(text, i):
    """The index after a character literal starting at the ' at i, or None when it is not one (a stray quote)."""
    j = i + 1
    if j < len(text) and text[j] == "\\":
        k = text.find("'", j + 2)
    else:
        k = j + 1 if j + 1 < len(text) and text[j + 1] == "'" else -1
    if k < 0 or k - i > 12 or "\n" in text[i:k]:
        return None
    return k + 1


def _hole_end(text, j):
    """The index after the } closing an interpolation hole whose code starts at j; strings inside it are skipped."""
    depth, n = 1, len(text)
    while j < n:
        c = text[j]
        if _is_string_start(text, j):
            j = _string_end(text, j)
            continue
        if c == "'":
            end = _char_end(text, j)
            if end is not None:
                j = end
                continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def _string_end(text, i):
    """The index after a string literal starting at i (its prefixes included): regular, verbatim (@), interpolated ($),
    either combined, and raw (three or more quotes). An interpolation hole's code is read as code, so quotes inside it,
    "{(a ? "x" : "y")}", do not end the string."""
    n = len(text)
    j = i
    while text[j] in "$@":
        j += 1
    prefix = text[i:j]
    verbatim, interpolated = "@" in prefix, "$" in prefix
    run = 0
    while j + run < n and text[j + run] == '"':
        run += 1
    if run >= 3:                                   # raw string: ends at the same run of quotes
        end = text.find('"' * run, j + run)
        return n if end < 0 else end + run
    j += 1
    while j < n:
        c = text[j]
        if verbatim and c == '"' and j + 1 < n and text[j + 1] == '"':
            j += 2
            continue
        if not verbatim and c == "\\":
            j += 2
            continue
        if interpolated and c == "{":
            if j + 1 < n and text[j + 1] == "{":
                j += 2
                continue
            j = _hole_end(text, j + 1)
            continue
        if c == '"':
            return j + 1
        if c == "\n" and not verbatim:
            return j                               # unterminated: stop at the line's end
        j += 1
    return n


def _blanked(span):
    """A literal's text as spaces, keeping its newlines and its first and last quote characters."""
    inner = "".join("\n" if ch == "\n" else " " for ch in span[1:-1])
    return span[:1] + inner + span[-1:] if len(span) > 1 else span


def blank(text):
    """text with comments and every string and character literal turned to spaces; newlines stay, so line numbers
    hold, and so do the literals' outer quotes."""
    return _without_comments(text, _blanked)


def uncommented(text):
    """text with only its comments turned to spaces: literals stay as written, and newlines stay, so lines match blank's."""
    return _without_comments(text, str)


def _without_comments(text, literal):
    """text with comments turned to spaces and each string or character literal passed through literal."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif _is_string_start(text, i):
            j = _string_end(text, i)
            out.append(literal(text[i:j]))
            i = j
        elif c == "'" and (end := _char_end(text, i)) is not None:
            out.append(literal(text[i:end]))
            i = end
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _single_spaced(text):
    return re.sub(r"\s+", " ", text).strip()


def outside_brackets(text):
    """text with every (), [] and <> group removed, innermost first, so a default parameter value (even one holding a
    cast, "= (Sense)1") or a generic argument is not read as an assignment or a name."""
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\([^()]*\)", "", text)
        text = re.sub(r"\[[^\[\]]*\]", "", text)
        text = re.sub(r"<[^<>()=;{}]*>", "", text)
    return text


def classify(header, owner_type, opens=False):
    """(kind, name) for a declaration header, or None when it is not one (a stray initialiser's tail, say). opens: the
    header is followed by "{", so a member that is not a method is a property with a body."""
    text = _single_spaced(ATTRIBUTES.sub("", header))
    if not text or not (text[0].isalpha() or text[0] in "@_~"):
        return None
    found = NAMESPACE.match(text)
    if found:
        return "namespace", found["name"]
    found = TYPE.match(text)
    if found:
        return found["kind"].split()[0], found["name"].lstrip("@")
    found = DELEGATE.match(text)
    if found:
        return "delegate", found["name"]
    if owner_type is None:
        return None
    found = OPERATOR.search(text)
    if found:
        return "operator", "operator " + found["op"]
    arrow = "=>" in outside_brackets(text)
    head = text.split("=>")[0]
    if INDEXER.search(ASSIGNMENT.split(head)[0]):
        return "indexer", "this[]"
    if EVENT.search(head):
        names = [n for n in IDENTIFIER.findall(ASSIGNMENT.split(head)[0].split("{")[0]) if n not in NOT_A_NAME]
        return ("event", names[-1].lstrip("@")) if names else None
    # Split at the first assignment outside brackets: a default parameter value is not an initialiser.
    before_assign = head
    if ASSIGNMENT.search(outside_brackets(head)):
        depth = 0
        for index, char in enumerate(head):
            if char in "([<":
                depth += 1
            elif char in ")]>":
                depth = max(0, depth - 1)
            elif char == "=" and depth == 0 and ASSIGNMENT.match(head, index):
                before_assign = head[:index]
                break
    for found in CALLABLE.finditer(before_assign):
        if found["name"] in NOT_A_NAME:
            continue
        name = found["name"].lstrip("@")
        simple = owner_type.rsplit(".", 1)[-1]
        if name.lstrip("~") == simple:
            return "constructor", name
        return "method", name
    # The last identifier is the name, even one spelt like a contextual keyword ("public bool required;"); before it a
    # type is needed, which a tuple, "(int a, float b) Name", leaves as brackets rather than a word.
    declared = before_assign.split("{")[0].rstrip()
    tokens = IDENTIFIER.findall(outside_brackets(declared))
    if not tokens or tokens[-1] in HARD_KEYWORDS:
        return None
    name = tokens[-1]
    typed = [t for t in tokens[:-1] if t not in NOT_A_NAME]
    tuple_typed = re.search(r"[)\]>]\s*@?\w+$", declared) is not None     # (int, string)[] Name, too
    if not (typed or tuple_typed or opens):
        return None
    is_property = opens or arrow or "{" in head
    return ("property" if is_property else "field"), name.lstrip("@")


@dataclass
class _Frame:
    kind: str                 # root, namespace, type, member, block
    name: str = ""            # a type's full name, a namespace's name
    decl: Declaration = None


def declarations(text):
    """Every namespace, type and member in C# text, with its lines, in the order they open."""
    lines = blank(text).split("\n")
    found = []
    stack = [_Frame("root")]
    header, header_start, waiting = "", 0, False      # waiting: an initialiser or => body, ends at ";" at this depth
    wait_depth = 0
    file_namespace = ""

    def top():
        """The innermost frame that is not a brace inside a header (an attribute's new[] { })."""
        return next(f for f in reversed(stack) if f.kind != "inline")

    def level():
        return top().kind in ("root", "namespace", "type")

    def owner_names():
        frame = next((f for f in reversed(stack) if f.kind in ("type", "namespace")), None)
        if frame is None:
            return file_namespace, None
        return frame.name, frame.name if frame.kind == "type" else None

    def close_header(line_no, opens):
        nonlocal header, header_start
        owner, owner_type = owner_names()
        if top().kind == "type" and top().decl and top().decl.kind == "enum":
            result = None
        else:
            result = classify(header, owner_type, opens)
        decl = None
        if result:
            kind, name = result
            sig = _single_spaced(ATTRIBUTES.sub("", header))[:SIGNATURE_LIMIT]
            decl = Declaration(kind, name, owner, sig, header_start, line_no)
            found.append(decl)
        header, header_start = "", 0
        return decl

    depth = 0
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):      # #if, #region, #define: not part of any declaration
            continue
        position = 0
        for token in TOKENS.finditer(line):
            segment = line[position:token.start()]
            position = token.end()
            if level() and not waiting:
                if segment.strip() and not header.strip():
                    header_start = number
                header += segment + " "
            char = token.group()
            if char == "{":
                if level() and not waiting and _open_brackets(header):
                    header += "{ "
                    stack.append(_Frame("inline"))
                elif level() and not waiting:
                    head = outside_brackets(_single_spaced(ATTRIBUTES.sub("", header)))
                    initialiser = "=>" in head or ASSIGNMENT.search(head)
                    if initialiser and not TYPE.match(head) and not NAMESPACE.match(head):
                        waiting, wait_depth = True, depth
                        stack.append(_Frame("block"))
                    else:
                        decl = close_header(number, True)
                        if decl is None:
                            stack.append(_Frame("block"))
                        elif decl.kind == "namespace":
                            stack.append(_Frame("namespace", decl.full if decl.owner else decl.name, decl))
                        elif decl.kind in ("class", "struct", "interface", "enum", "record"):
                            stack.append(_Frame("type", decl.full, decl))
                        else:
                            stack.append(_Frame("member", decl.full, decl))
                else:
                    stack.append(_Frame("block"))
                depth += 1
            elif char == "}":
                depth -= 1
                frame = stack.pop() if len(stack) > 1 else stack[0]
                if frame.kind == "inline":
                    header += "} "
                else:
                    if frame.decl is not None:
                        frame.decl.end = number
                    if level() and not waiting:
                        header, header_start = "", 0
            else:  # ;
                if waiting and depth == wait_depth:
                    waiting = False
                    close_header(number, False)
                elif level() and not waiting:
                    decl = close_header(number, False)
                    if decl is not None and decl.kind == "namespace":
                        file_namespace = decl.name
        rest = line[position:]
        if level() and not waiting:
            if rest.strip() and not header.strip():
                header_start = number
            header += rest + " "
    return found
