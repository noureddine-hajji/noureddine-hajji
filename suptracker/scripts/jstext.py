"""The text a student can read in a page script: string literals and the fixed parts of template literals.

A small JavaScript tokenizer (no dependency, so it runs in CI): comments are skipped, regular-expression literals are
recognised by the usual rule (a "/" where an expression may start), template literals are split into their fixed parts and
their ${...} expressions, which are tokenized in turn (they hold strings too). Used by scripts/redteam_langage.py; checked
against a full JavaScript parser (acorn) when one is installed (LA8).
"""
from __future__ import annotations

import re

_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^") | {""}
_REGEX_WORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "instanceof", "yield", "await"}
_ID = re.compile(r"[A-Za-z_$][\w$]*")


def strings(src: str) -> list[tuple[int, str]]:
    """[(offset, text)] for every string literal and every fixed part of a template literal, in source order."""
    out: list[tuple[int, str]] = []
    _scan(src, 0, len(src), out, top=True)
    return out


def _scan(src: str, i: int, end: int, out: list, top: bool = False, stop_brace: bool = False) -> int:
    prev = ""                                  # last significant token (for the regex rule)
    depth = 0
    while i < end:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = end if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = end if j < 0 else j + 2
            continue
        if c in "'\"":
            j, text = _quoted(src, i, c)
            out.append((i, text))
            i, prev = j, "str"
            continue
        if c == "`":
            i = _template(src, i, out)
            prev = "str"
            continue
        if c == "/" and (prev in _REGEX_BEFORE or prev in _REGEX_WORDS):
            i = _regex(src, i)
            prev = "re"
            continue
        if stop_brace:
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    return i + 1
                depth -= 1
        m = _ID.match(src, i)
        if m:
            prev = m.group(0)
            i = m.end()
            continue
        if c.isdigit():
            m = re.compile(r"[\d.xXa-fA-F_eEn]+").match(src, i)
            prev = "num"
            i = m.end()
            continue
        prev = c if c not in ")]" else ")"
        i += 1
    return i


def _quoted(src: str, i: int, q: str) -> tuple[int, str]:
    j, buf = i + 1, []
    while j < len(src) and src[j] != q:
        if src[j] == "\\":
            buf.append(src[j:j + 2])
            j += 2
            continue
        if src[j] == "\n":
            break
        buf.append(src[j])
        j += 1
    return j + 1, _unescape("".join(buf))


def _template(src: str, i: int, out: list) -> int:
    j, buf, start = i + 1, [], i + 1
    while j < len(src):
        c = src[j]
        if c == "\\":
            buf.append(src[j:j + 2])
            j += 2
            continue
        if c == "`":
            out.append((start, _unescape("".join(buf))))
            return j + 1
        if src.startswith("${", j):
            out.append((start, _unescape("".join(buf))))
            buf = []
            j = _scan(src, j + 2, len(src), out, stop_brace=True)
            start = j
            continue
        buf.append(c)
        j += 1
    return j


def _regex(src: str, i: int) -> int:
    j, cls = i + 1, False
    while j < len(src):
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            cls = True
        elif c == "]":
            cls = False
        elif c == "/" and not cls:
            j += 1
            while j < len(src) and (src[j].isalpha()):
                j += 1
            return j
        elif c == "\n":
            return j
        j += 1
    return j


def _unescape(s: str) -> str:
    s = re.sub(r"\\u\{([0-9a-fA-F]+)\}|\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1) or m.group(2), 16)), s)
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


TAG = re.compile(r"<[^>]*>")
ATTR_ANY = re.compile(r'[\w-]+="[^"]*"?|[\w-]+=\'[^\']*\'?')
ATTR_TEXT = re.compile(r'\b(?:aria-label|title|data-tip|data-label|placeholder|alt)="([^"$]*)')


def visible(piece: str) -> str:
    """What of a piece reaches the screen: the text between tags plus the attributes a person reads (labels, titles)."""
    attrs = " ".join(ATTR_TEXT.findall(piece))
    text = ATTR_ANY.sub(" ", TAG.sub(" ", piece))
    return f"{text} {attrs}".strip()


def q4_defs(js: str, rules: bool = False, present: str = "") -> str:
    """Sprint Q4: the page helpers every card now calls (the estimation label, the zone texts, "Et maintenant ?"), for the red
    teams that run parts of the page in Node. `rules`: also ZONE_RULES. `present`: the harness so far (a definition it already
    holds is not repeated)."""
    pats = {"ESTIM_DEF": r"^const ESTIM_DEF = .*?$", "estimTag": r"^function estimTag\(.*?^\}", "zoneHelp": r"^function zoneHelp\(.*?^\}",
            "ZONE_NOT_CHANCE": r"^const ZONE_NOT_CHANCE = .*?$", "zoneLegend": r"^function zoneLegend\(.*?^\}",
            "AIDE_STEP": r"^const AIDE_STEP = .*?$", "NEXT_STEPS": r"^const NEXT_STEPS = \{.*?^\};", "nextSteps": r"^function nextSteps\(.*?^\}"}
    if rules:
        pats["ZONE_RULES"] = r"^const ZONE_RULES = .*?$"
    out = [re.search(p, js, re.M | re.S).group(0) for n, p in pats.items()
           if not re.search(rf"^(?:const|let|function) {n}\b", present, re.M)]
    return "\n" + "\n".join(out) + "\n"
