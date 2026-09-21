"""Shared verb-to-glyph vocabulary for agent bead touches.

Both ``sase bead touched`` and the Agents-tab ``Beads:`` sub-section render
one glyph per bead: the single strongest verb by precedence. This module owns
that precedence so the two surfaces read as one feature. Rendered output is
unchanged: values match the lane glyphs in
:mod:`sase.ace.tui.widgets.prompt_panel._agent_context_common`.
"""

from __future__ import annotations

from collections.abc import Mapping

CREATED_GLYPH = "✚"
CLOSED_GLYPH = "✓"
REOPENED_GLYPH = "↻"
EDITED_GLYPH = "✎"
READ_GLYPH = "←"
VIEWED_GLYPH = "◇"
REMOVED_GLYPH = "⌫"
EMPTY_GLYPH = "◇"

#: Durable verbs sharing the ``✎`` edited glyph.
EDITED_VERBS = frozenset(
    {
        "updated",
        "noted",
        "ready",
        "snoozed",
        "dep",
        "linked",
        "ref",
        "+1",
    }
)

#: Fixed chip order for the CLI: durable verbs first, then ``read``, then
#: ``viewed``. The panel orders durable chips by merge order but keeps the
#: same ``read``-then-``viewed`` tail.
TOUCH_VERB_ORDER = (
    "created",
    "updated",
    "noted",
    "closed",
    "reopened",
    "+1",
    "ready",
    "snoozed",
    "dep",
    "linked",
    "ref",
    "removed",
    "read",
    "viewed",
)


def touch_glyph(verbs: Mapping[str, int]) -> str:
    """Return the row's single strongest verb glyph.

    Precedence: created > closed > reopened > edited group > read >
    viewed > removed, with ``◇`` for no verbs. ``own`` is a mark, not a
    verb, so it never selects the glyph.
    """
    if "created" in verbs:
        return CREATED_GLYPH
    if "closed" in verbs:
        return CLOSED_GLYPH
    if "reopened" in verbs:
        return REOPENED_GLYPH
    if any(verb in verbs for verb in EDITED_VERBS):
        return EDITED_GLYPH
    if "read" in verbs:
        return READ_GLYPH
    if "viewed" in verbs:
        return VIEWED_GLYPH
    if "removed" in verbs:
        return REMOVED_GLYPH
    return EMPTY_GLYPH


__all__ = [
    "CLOSED_GLYPH",
    "CREATED_GLYPH",
    "EDITED_GLYPH",
    "EDITED_VERBS",
    "EMPTY_GLYPH",
    "READ_GLYPH",
    "REMOVED_GLYPH",
    "REOPENED_GLYPH",
    "TOUCH_VERB_ORDER",
    "VIEWED_GLYPH",
    "touch_glyph",
]
