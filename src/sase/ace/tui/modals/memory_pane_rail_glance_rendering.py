"""Rail-glance presentation: glyph/age suffixes and tombstone rows.

Pure row-text helpers behind the phase rail-glance Notes rail: the
right-aligned newest-change glyph and age on every row, and the
read-only tombstone cards of the trailing ``DELETED`` group. History
presentation comes only through ``sase.pager.history_kit`` (the
import-guard door). Never raises.
"""

from __future__ import annotations

import time as _time
from pathlib import Path
from typing import Any

from rich.text import Text

from sase.ace.tui.memory_panel_catalog import MemoryRailNode
from sase.memory.notes import AGENTS_PARENT, MemoryNote

from ._memory_pane_rail_glance_shared import DeletedSubject

#: Style for DELETED rail rows (the tombstone role is red in the kit).
_DELETED_ROW_STYLE = "red"

#: Classes whose glance glyph keeps a bold highlight (promotions only).
_PROMOTION_CLASSES = frozenset({"promoted", "demoted"})

#: Toast when a mutation or source key hits a history-only row.
_HISTORY_ONLY_REFUSAL = "deleted subjects are read-only"


def glance_suffix(class_name: str, committer_time: int, *, now_epoch: int = 0) -> str:
    """Return the ``glyph age`` suffix (``⇧ 8d``) for one newest change."""
    try:
        from sase.pager.history_kit import format_age, glyph_for
    except Exception:
        return ""
    try:
        now = int(now_epoch) if now_epoch else int(_time.time())
        age = format_age(int(now), int(committer_time))
        glyph = glyph_for(str(class_name))
    except Exception:
        return ""
    if not age or not glyph:
        return ""
    return f"{glyph} {age}"


def glance_glyph_only(class_name: str) -> str:
    """Return just the vocabulary glyph for a change class."""
    try:
        from sase.pager.history_kit import glyph_for

        return str(glyph_for(str(class_name)) or "")
    except Exception:
        return ""


def node_glance_path(node: Any) -> str:
    """Return the feed path a rail row matches on (strands: strand file)."""
    try:
        strand = getattr(node, "strand", None)
        if strand is not None:
            relative = getattr(strand, "relative_path", "") or ""
            if relative:
                return str(relative)
        note = getattr(node, "note", None)
        if note is not None:
            return str(getattr(note, "relative_path", "") or "")
    except Exception:
        pass
    return ""


def _deleted_age_text(committer_time: int, *, now_epoch: int = 0) -> str:
    """Return the compact age for a DELETED row (``3w``)."""
    try:
        from sase.pager.history_kit import format_age
    except Exception:
        return ""
    try:
        now = int(now_epoch) if now_epoch else int(_time.time())
        return str(format_age(int(now), int(committer_time)) or "")
    except Exception:
        return ""


def build_deleted_row_text(
    display: str, committer_time: int, *, now_epoch: int = 0
) -> Text:
    """Return one DELETED rail row: ``✖ name   deleted 3w``.

    Pure: the deleted style is fixed here so every caller paints the
    group identically. Never raises.
    """
    try:
        age = _deleted_age_text(int(committer_time), now_epoch=int(now_epoch))
    except Exception:
        age = ""
    text = Text(style=_DELETED_ROW_STYLE)
    try:
        text.append(f"✖ {display}")
        text.append("   deleted")
        if age:
            text.append(f" {age}")
    except Exception:
        return Text(f"✖ {display}", style=_DELETED_ROW_STYLE)
    return text


def history_only_node(subject: DeletedSubject) -> MemoryRailNode:
    """Return the history-only rail node for one deleted subject.

    The synthetic note carries the deleted path so history selectors,
    filters, and pins resolve exactly like a live row; ``history_only``
    marks the kind so note-only paths skip or refuse it. Never raises.
    """
    note = MemoryNote(
        path=Path(subject.path),
        type="reference",
        parent=AGENTS_PARENT,
        description=None,
        body="",
        frontmatter={},
        type_source="missing",
        parent_source="missing",
        source_path=Path(subject.path),
    )
    return MemoryRailNode(
        note=note,
        depth=0,
        history_only=True,
        deleted_ordinal=int(subject.ordinal),
    )


def is_promotion_class(class_name: str) -> bool:
    """Return whether a glance class keeps its highlight (``⇧``/``⇩``)."""
    try:
        return str(class_name) in _PROMOTION_CLASSES
    except Exception:
        return False


def history_only_refusal() -> str:
    """Return the toast for mutation/source keys on history-only rows."""
    return _HISTORY_ONLY_REFUSAL


__all__ = [
    "build_deleted_row_text",
    "glance_glyph_only",
    "glance_suffix",
    "history_only_node",
    "history_only_refusal",
    "is_promotion_class",
    "node_glance_path",
]
