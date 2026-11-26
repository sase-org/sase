"""Discoverability cues for copyable items on the question pane.

``user_question_modal.py`` is near the ``toobig`` limit, so the pane-cue
presentation helpers live here as pure functions that are unit-tested
without a TUI. The copying mixin applies them to the live modal.

Three cues share the panel's key allocator and copy-progress state:

- **Border subtitle** on ``#user-question-text-scroll``: ``N copyable · y``
  before anything is copied, ``k/N copied · y`` during, and ``✓ N/N copied``
  in green when done, plus a ``· N unavailable`` warning tail.
- **Prose underlines**: every verbatim occurrence of a declared snippet is
  underlined in teal (``#00D7AF``), turning green once copied. Only spans
  are added, so ``Text.plain`` still equals the question string exactly and
  wrapping and mouse selection are unchanged.
- **Also-copyable block**: declared items absent from the prose are listed
  under the question text with their panel key, label, and full verbatim
  value, so no copiable value is hidden.
"""

from __future__ import annotations

from rich.text import Text

from sase.core.question_copy_facade import QuestionCopyItem

from .question_copy_items import SNIPPET_KEY_POOL

TEAL = "#00D7AF"

_UNCOPIED_PROSE_STYLE = f"underline {TEAL}"
_COPIED_PROSE_STYLE = "underline green"
_PANE_KEY_STYLE = f"bold {TEAL}"

ALSO_COPYABLE_HEADER = "── also copyable · y then key ──"


def build_question_prose_text(
    question_text: str,
    items: tuple[QuestionCopyItem, ...],
    copied_texts: frozenset[str] | set[str],
) -> Text:
    """Return the question as plain ``Text`` with snippet occurrences underlined.

    Declared texts are matched longest first and already-underlined ranges
    are never re-marked, so overlapping snippets resolve to the longest one.
    Copied snippets underline green, the rest teal. The result's ``plain``
    always equals ``question_text`` exactly.
    """
    text = Text(question_text)
    if not question_text or not items:
        return text
    covered = bytearray(len(question_text))
    for item in sorted(items, key=lambda entry: len(entry.text), reverse=True):
        needle = item.text
        if not needle:
            continue
        style = _COPIED_PROSE_STYLE if needle in copied_texts else _UNCOPIED_PROSE_STYLE
        start = 0
        while True:
            idx = question_text.find(needle, start)
            if idx < 0:
                break
            end = idx + len(needle)
            if not any(covered[idx:end]):
                text.stylize(style, idx, end)
                for pos in range(idx, end):
                    covered[pos] = 1
            start = idx + 1
    return text


def missing_copy_items(
    question_text: str,
    items: tuple[QuestionCopyItem, ...],
) -> tuple[QuestionCopyItem, ...]:
    """Return declared items with no verbatim occurrence in the prose."""
    return tuple(item for item in items if item.text not in question_text)


def pane_keys_for_items(count: int) -> tuple[str, ...]:
    """Return the stable panel keys for ``count`` declared snippets."""
    return SNIPPET_KEY_POOL[:count]


def build_copy_border_subtitle(
    total: int,
    copied_count: int,
    unavailable: int,
) -> Text | str:
    """Return the question-pane border subtitle for the copy progress.

    Questions without copy metadata get an empty subtitle so their border
    renders exactly as before.
    """
    if total == 0 and unavailable == 0:
        return ""
    if total == 0:
        return Text.assemble(
            Text(f"{unavailable} unavailable", style="$warning"),
            Text(" · y", style="dim"),
        )
    if copied_count >= total:
        base = Text(f"✓ {copied_count}/{total} copied", style="green")
    elif copied_count == 0:
        base = Text(f"{total} copyable · y", style="dim")
    else:
        base = Text(f"{copied_count}/{total} copied · y", style="dim")
    if unavailable > 0:
        return Text.assemble(
            base,
            Text(" · ", style="dim"),
            Text(f"{unavailable} unavailable", style="$warning"),
        )
    return base


def build_also_copyable_text(
    keys_and_items: tuple[tuple[str, QuestionCopyItem], ...],
) -> Text:
    """Return the muted block listing declared items missing from the prose.

    Each row shows the item's panel key in teal, its label when present,
    and its full verbatim value (multi-line values are kept as-is).
    """
    text = Text()
    text.append(ALSO_COPYABLE_HEADER, style="dim")
    for key, item in keys_and_items:
        text.append("\n")
        text.append(f" {key}  ", style=_PANE_KEY_STYLE)
        if item.label:
            text.append(item.label, style="bold")
            text.append("  ")
        text.append(item.text)
    return text


__all__ = [
    "ALSO_COPYABLE_HEADER",
    "TEAL",
    "build_also_copyable_text",
    "build_copy_border_subtitle",
    "build_question_prose_text",
    "missing_copy_items",
    "pane_keys_for_items",
]
