"""Card moment views and footer verbs for the Memory pane time travel.

Pure view helpers built on the shared :func:`moment_for_card` builder
from :mod:`sase.ace.tui.modals._memory_pane_time_shared`; this module
imports no ``_``-prefixed names from its sibling pane modules.
"""

from __future__ import annotations

from typing import Any

from ._memory_pane_time_shared import moment_for_card


def card_moment_for_view(
    timeline: dict[str, Any] | None,
    *,
    subject_id: str,
    pin_ordinal: int,
    view: str = "read",
) -> Any | None:
    """Return the kit moment for *pin_ordinal* in the *view* ("read"/"diff").

    Public wrapper over the shared moment builder for sibling pane
    modules (which never import ``_``-prefixed names): a ``"diff"``
    moment carries the pager's own ``(base, target)`` endpoints on
    ``moment.diff``, so diff callers never re-derive them. Never raises.
    """
    try:
        return moment_for_card(
            timeline, subject_id=subject_id, pin_ordinal=pin_ordinal, view=view
        )
    except Exception:
        return None


def step_footer_verbs(moment: Any, *, keymaps: Any) -> tuple[str, ...]:
    """Return the footer step verbs for *moment* with configured keys.

    The stepping verbs (``(`` ``)`` ``}``), the diff toggle (``=``),
    and the Timeline lens (``@``).
    """
    try:
        from sase.pager.history_kit import time_verbs_for_moment
        from sase.ace.tui.keymaps import key_display_name

        verbs = time_verbs_for_moment(moment)
    except Exception:
        return ()
    try:
        key_for = {
            "(": key_display_name(keymaps.history_older),
            ")": key_display_name(keymaps.history_newer),
            "}": key_display_name(keymaps.history_now),
            "=": key_display_name(keymaps.history_toggle_diff),
            "@": key_display_name(keymaps.history_timeline),
        }
    except Exception:
        key_for = {"(": "(", ")": ")", "}": "}", "=": "=", "@": "@"}
    shown: list[str] = []
    for text, label in verbs:
        glyph = str(text or "")[:1]
        if glyph not in key_for:
            continue
        if glyph == "=" and label:
            # The kit carries the toggle direction as the label, so the
            # card footer reads `= diff` / `= read` like the pager.
            shown.append(f"{key_for[glyph]} {label}")
            continue
        rest = str(text or "")[1:]
        shown.append(f"{key_for[glyph]}{rest}")
    return tuple(shown)


__all__ = ["card_moment_for_view", "step_footer_verbs"]
