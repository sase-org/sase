"""Shared Timeline-lens rows and rail constants (``@`` timeline lens).

This module is private; the names it defines are public so the
``memory_pane_timeline_lens_*`` sibling modules can share them without
importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

from typing import Any, cast

#: Rail row id prefix for lens rows (never collides with note identities,
#: which are repo-relative paths or ``web:strand`` selectors).
TIMELINE_ROW_PREFIX = "timeline:"

#: Trailing rail row id for the hidden-versions summary line.
HIDDEN_SUMMARY_ID = f"{TIMELINE_ROW_PREFIX}hidden-summary"


def newest_first(timeline: dict[str, Any]) -> dict[str, Any]:
    """Return *timeline* with versions in the pager picker's order.

    The card's memoized summary keeps versions oldest-first for the
    strip; the picker lists pseudo rows, then committed versions
    newest-first, exactly as the core wire reaches the pager.
    """
    versions = timeline.get("versions", ())
    if not isinstance(versions, (list, tuple)):
        return timeline

    def _key(version: Any) -> tuple[bool, int]:
        try:
            ordinal = int(version.get("ordinal", 0) or 0)
        except (AttributeError, TypeError, ValueError):
            ordinal = 0
        return (ordinal > 0, -ordinal)

    return {**timeline, "versions": sorted(versions, key=_key)}


def timeline_lens_rows(
    timeline: dict[str, Any] | None,
    *,
    now_epoch: int,
    show_hidden: bool,
) -> tuple[tuple[dict[str, Any], ...], int, int]:
    """Return ``(listed, hidden_count, total_committed)`` for the rail.

    Rows come from the kit's :func:`build_picker_rows` (the pager
    picker's exact cells). *listed* excludes hidden rows unless
    *show_hidden*; *hidden_count* counts the rows ``.`` would reveal;
    *total_committed* counts non-pseudo rows. Never raises: ``None``
    or malformed timelines list nothing.
    """
    try:
        from sase.pager.history_kit import (
            build_picker_rows,
            hidden_picker_rows,
            visible_picker_rows,
        )
    except Exception:
        return ((), 0, 0)
    if not isinstance(timeline, dict):
        return ((), 0, 0)
    try:
        newest = 0
        versions = timeline.get("versions", ())
        if isinstance(versions, (list, tuple)):
            for version in versions:
                if isinstance(version, dict):
                    try:
                        ordinal = int(version.get("ordinal", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    newest = max(newest, ordinal)
        now_matches = newest > 0 and not bool(timeline.get("dirty", False))
        rows = build_picker_rows(
            newest_first(timeline),
            now_epoch=int(now_epoch),
            now_matches_newest=now_matches,
        )
    except Exception:
        return ((), 0, 0)
    try:
        hidden = hidden_picker_rows(tuple(rows))
        hidden_count = len(hidden)
    except Exception:
        hidden_count = 0
    try:
        if show_hidden:
            listed = cast(tuple[dict[str, Any], ...], tuple(rows))
        else:
            listed = cast(
                tuple[dict[str, Any], ...],
                tuple(visible_picker_rows(tuple(rows), show_hidden=False)),
            )
    except Exception:
        listed = cast(tuple[dict[str, Any], ...], tuple(rows))
    try:
        total = sum(1 for row in rows if not bool(row.get("pseudo", False)))
    except Exception:
        total = 0
    return (listed, hidden_count, total)


__all__ = [
    "HIDDEN_SUMMARY_ID",
    "TIMELINE_ROW_PREFIX",
    "newest_first",
    "timeline_lens_rows",
]
