"""Timeline visibility helpers for the memory history pager.

Split from :mod:`sase.memory.history.pager_provider`; the facade
re-exports these public names so the original import path keeps working.
"""

from __future__ import annotations

from typing import Any

from sase.memory.history.vocabulary import is_hidden_by_default

#: Pseudo-version classes on ordinal-0 timeline rows: the core wire
#: reports dirty worktrees this way, without ``status``/``state`` keys.
_PSEUDO_DIRTY_CLASSES = ("uncommitted", "staged")


def visible_ordinals_for_timeline(timeline: dict[str, Any]) -> tuple[int, ...]:
    """Return committed ordinals visible without ``-a/--all`` (pager/CLI shared)."""
    versions = timeline.get("versions", ())
    visible: list[int] = []
    for row in versions:  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        ordinal = int(row.get("ordinal", 0) or 0)
        if ordinal <= 0:
            continue
        hidden = bool(row.get("hidden", False))
        class_name = str(row.get("class", "") or "")
        if hidden or is_hidden_by_default(class_name):
            continue
        visible.append(ordinal)
    return tuple(sorted(visible))


def newest_committed_row(timeline: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest committed timeline row, if any."""
    best: dict[str, Any] | None = None
    for row in timeline.get("versions", ()):  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        ordinal = int(row.get("ordinal", 0) or 0)
        if ordinal <= 0:
            continue
        if best is None or ordinal > int(best.get("ordinal", 0) or 0):
            best = row
    return best


def is_deleted_row(row: dict[str, Any]) -> bool:
    """Return whether a timeline row is a deletion tombstone."""
    return str(row.get("class", "") or "") == "deleted"


def dirty_now_from_timeline(timeline: dict[str, Any]) -> bool:
    for row in timeline.get("versions", ()):  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        if int(row.get("ordinal", 0) or 0) != 0:
            continue
        if str(row.get("class", "") or "") in _PSEUDO_DIRTY_CLASSES:
            return True
        status = row.get("status", row.get("state", ""))
        if isinstance(status, dict):
            worktree = str(status.get("worktree", "") or "").lower()
            index = str(status.get("index", "") or "").lower()
            head = str(status.get("head", "") or "").lower()
            if any(
                token in ("dirty", "modified", "added", "deleted", "untracked")
                for token in (worktree, index, head)
            ):
                return True
            # Fall back to explicit dirty markers.
            if bool(status.get("dirty", False)):
                return True
            return False
        text = str(status or "").lower()
        return text not in ("", "clean", "tracked", "notracked")
    return False


def history_marks_from_comparison(
    comparison: dict[str, Any] | None,
) -> tuple[dict[int, str], set[int]]:
    """Derive read-view gutter marks from a parent comparison.

    ``line_marks`` (1-based) become ``added`` marks unless the line also
    carries word-deletion ops (then ``changed``); ``removal_anchors``
    become red anchor rows. Old-to-new comparisons anchor steps that skip
    hidden versions; parent comparisons feed this gutter — never confuse
    the two purposes.
    """
    if not comparison:
        return {}, set()
    marks: dict[int, str] = {}
    for line in comparison.get("line_marks", ()):  # type: ignore[union-attr]
        try:
            lineno = (
                int(line)
                if not isinstance(line, dict)
                else int(line.get("target_line", 0) or 0)
            )
        except (TypeError, ValueError):
            continue
        if lineno > 0:
            marks[lineno] = "added"
    for entry in comparison.get("word_ops", ()):  # type: ignore[union-attr]
        if not isinstance(entry, dict):
            continue
        try:
            lineno = int(entry.get("target_line", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lineno <= 0:
            continue
        ops = entry.get("ops", ())
        kinds = {
            str(op.get("kind", "") or "").lower() for op in ops if isinstance(op, dict)
        }  # type: ignore[union-attr]
        if "delete" in kinds or "remove" in kinds or "replace" in kinds:
            marks[lineno] = "changed"
        else:
            marks.setdefault(lineno, "added")
    anchors: set[int] = set()
    for anchor in comparison.get("removal_anchors", ()):  # type: ignore[union-attr]
        if isinstance(anchor, dict):
            try:
                after = int(anchor.get("after_target_line", 0) or 0)
            except (TypeError, ValueError):
                continue
            anchors.add(max(after, 0))
        else:
            try:
                anchors.add(max(int(anchor), 0))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
    return marks, anchors


__all__ = [
    "dirty_now_from_timeline",
    "history_marks_from_comparison",
    "is_deleted_row",
    "newest_committed_row",
    "visible_ordinals_for_timeline",
]
