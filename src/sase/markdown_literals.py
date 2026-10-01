"""Preserve inline ``_`` and ``*`` literals across prettier formatting.

Prettier's Markdown parser treats runs of ``_`` and ``*`` as emphasis
delimiters, including inside words, and then normalizes the emphasis it found
(``__x__`` becomes ``**x**``, ``*x*`` becomes ``_x_``). Agent prompts routinely
carry such characters literally (dunders, globs, Jinja, ``__<suffix>.md``
labels), so formatting them with raw prettier corrupts paths and identifiers.

This module protects those literals with width-preserving Unicode private-use
sentinels before prettier runs and restores them afterwards. Prettier still
reflows prose and normalizes block structure; it can no longer see or rewrite
inline emphasis characters.

This module intentionally imports nothing from ``sase`` at module scope.

Invariants:

- ``restore_emphasis_literals(protect_emphasis_literals(x)[0], sentinels) == x``
  for every string.
- The protected text contains no ``_`` or ``*`` outside bullet prefixes and
  thematic-break lines.
- Protection is bijective inside code spans, fences, URLs, HTML, YAML front
  matter, and the ``\\x00XPF_n\\x00`` placeholders, so those regions also
  round-trip exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})\r?$")
_BULLET_RE = re.compile(r"^([ \t]*(?:>[ \t]*)*)\*(?=[ \t\r]|$)")
_GLUE_RE = re.compile(r"(?<=\S) (?=\*+(?:[ \t\r]|$))")

_PUA_START = 0xE000
_PUA_END = 0xF8FF


@dataclass(frozen=True, slots=True)
class EmphasisSentinels:
    """Private-use placeholders for literal emphasis characters."""

    underscore: str
    star: str
    glue: str


def _choose_sentinels(text: str) -> EmphasisSentinels:
    """Pick three PUA code points absent from *text*.

    Each sentinel is one code point. Prettier measures PUA characters as
    width 1, so wrapping width is unchanged.
    """
    used = set(text)
    chosen: list[str] = []
    code = _PUA_START
    while len(chosen) < 3:
        if code > _PUA_END:
            raise ValueError("no free private-use code points for sentinels")
        candidate = chr(code)
        if candidate not in used:
            chosen.append(candidate)
        code += 1
    return EmphasisSentinels(underscore=chosen[0], star=chosen[1], glue=chosen[2])


def protect_emphasis_literals(text: str) -> tuple[str, EmphasisSentinels]:
    """Replace inline ``_`` / ``*`` with sentinels line by line.

    The transform is line-based over ``text.split("\\n")`` and order-sensitive:

    1. Thematic-break lines (``***``, ``___``, ``* * *``) are left untouched.
    2. A leading ``*`` bullet marker stays real; only the remainder is
       protected, so prettier may still normalize ``*`` bullets to ``-``.
    3. The single space before a standalone ``*`` run is glued, so prettier
       cannot wrap the run onto the start of a line where restoring it would
       create a list item.
    4. Every remaining ``_`` and ``*`` becomes its sentinel.
    """
    sentinels = _choose_sentinels(text)
    protected_lines: list[str] = []
    for line in text.split("\n"):
        if _THEMATIC_BREAK_RE.match(line):
            protected_lines.append(line)
            continue
        bullet = _BULLET_RE.match(line)
        if bullet is not None:
            prefix = line[: bullet.end()]
            remainder = line[bullet.end() :]
        else:
            prefix = ""
            remainder = line
        remainder = _GLUE_RE.sub(sentinels.glue, remainder)
        remainder = remainder.replace("_", sentinels.underscore).replace(
            "*", sentinels.star
        )
        protected_lines.append(prefix + remainder)
    return "\n".join(protected_lines), sentinels


def restore_emphasis_literals(text: str, sentinels: EmphasisSentinels) -> str:
    """Map sentinels back to the literal characters they replaced."""
    return (
        text.replace(sentinels.glue, " ")
        .replace(sentinels.underscore, "_")
        .replace(sentinels.star, "*")
    )


__all__ = [
    "EmphasisSentinels",
    "protect_emphasis_literals",
    "restore_emphasis_literals",
]
