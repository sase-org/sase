"""Pure renderer for the sase ace startup-stopwatch big-digit readout.

Renders digits ``0``-``9``, ``.``, and ``:`` as 5-row block-character glyphs.
Digit glyphs are 6 columns wide; ``.`` and ``:`` are 2 columns wide. Adjacent
glyphs are joined with a single blank-column gap.

The function is a pure ``str -> str`` transform so it is trivially testable
without Textual, Rich, or a running event loop.
"""

from __future__ import annotations

from typing import Final

GLYPH_ROWS: Final[int] = 5
DIGIT_COLS: Final[int] = 6
PUNCT_COLS: Final[int] = 2
GAP: Final[str] = " "  # single blank column between glyphs

# Each glyph is 5 rows. Rows are expressed as strings using "█" (full block).
# Digit glyphs are 6 visual columns wide. Punctuation is 2 visual columns wide.
_GLYPHS: Final[dict[str, tuple[str, ...]]] = {
    "0": (
        "██████",
        "██  ██",
        "██  ██",
        "██  ██",
        "██████",
    ),
    "1": (
        "    ██",
        "    ██",
        "    ██",
        "    ██",
        "    ██",
    ),
    "2": (
        "██████",
        "    ██",
        "██████",
        "██    ",
        "██████",
    ),
    "3": (
        "██████",
        "    ██",
        "██████",
        "    ██",
        "██████",
    ),
    "4": (
        "██  ██",
        "██  ██",
        "██████",
        "    ██",
        "    ██",
    ),
    "5": (
        "██████",
        "██    ",
        "██████",
        "    ██",
        "██████",
    ),
    "6": (
        "██████",
        "██    ",
        "██████",
        "██  ██",
        "██████",
    ),
    "7": (
        "██████",
        "    ██",
        "    ██",
        "    ██",
        "    ██",
    ),
    "8": (
        "██████",
        "██  ██",
        "██████",
        "██  ██",
        "██████",
    ),
    "9": (
        "██████",
        "██  ██",
        "██████",
        "    ██",
        "██████",
    ),
    ".": (
        "  ",
        "  ",
        "  ",
        "  ",
        "██",
    ),
    ":": (
        "  ",
        "██",
        "  ",
        "██",
        "  ",
    ),
}


# pyvision: tests/ace/tui/test_big_digits.py
def glyph(char: str) -> tuple[str, ...]:
    """Return the 5-row glyph for ``char``.

    Raises ``ValueError`` for unsupported characters so the caller can fail
    loudly rather than silently producing blank output.
    """
    try:
        return _GLYPHS[char]
    except KeyError as exc:
        raise ValueError(f"unsupported big-digit character: {char!r}") from exc


def render_big_digits(text: str) -> str:
    """Render ``text`` as a multi-line big-digit block.

    ``text`` must contain only characters supported by :data:`_GLYPHS`
    (``0``-``9``, ``.``, ``:``). Glyphs are joined left-to-right with a
    one-column blank gap and separated vertically by ``\n``.
    """
    if not text:
        return ""
    glyphs = [glyph(ch) for ch in text]
    rendered_rows: list[str] = []
    for row_idx in range(GLYPH_ROWS):
        row = GAP.join(g[row_idx] for g in glyphs)
        rendered_rows.append(row)
    return "\n".join(rendered_rows)
