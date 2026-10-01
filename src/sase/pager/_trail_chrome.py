"""Pure renderers for the pager's visit-history breadcrumb chrome.

The trail data model, path-token layout, band rendering, and help-sheet
rendering live in sibling modules. This module keeps snapshot construction
and re-exports the public rendering entry points.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from sase.pager._line_mark import LineMark
from sase.pager._trail_chrome_band import render_trail_band, trail_band_row_count
from sase.pager._trail_chrome_help import (
    build_pager_help_content,
    render_pager_help_footer,
    render_pager_help_header,
)
from sase.pager._trail_chrome_model import (
    PagerTrailDisplayEntry as _PagerTrailDisplayEntry,
)
from sase.pager._trail_chrome_model import PagerTrailSnapshot, TrailEntryState
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.trail import PagerTrailEntry


def build_pager_trail_snapshot(
    *,
    back: Sequence[PagerTrailEntry],
    document: PagerDocument,
    document_identity: str,
    current_section: PagerSection | None,
    forward: Sequence[PagerTrailEntry],
    current_line_mark: LineMark | None = None,
    version_pins: Mapping[str, object] | Sequence[tuple[str, object]] | None = None,
    current_suffix: str = "",
) -> PagerTrailSnapshot:
    """Build the display snapshot from retained stacks and live current metadata.

    ``version_pins`` maps section identities to their version pins for
    back/forward entries; ``current_suffix`` is the live moment's suffix
    for the current entry. Both fail open to no suffix.
    """

    pins = _pins_by_identity(version_pins)
    entries: list[_PagerTrailDisplayEntry] = [
        _display_entry_from_history(
            entry, "back", _suffix_for_pin(pins.get(entry.section_identity))
        )
        for entry in back
    ]
    entries.append(
        _display_entry_from_current(
            document,
            document_identity=document_identity,
            current_section=current_section,
            line_mark=current_line_mark,
            version_suffix=current_suffix,
        )
    )
    entries.extend(
        _display_entry_from_history(
            entry, "forward", _suffix_for_pin(pins.get(entry.section_identity))
        )
        for entry in reversed(forward)
    )
    return PagerTrailSnapshot(entries=tuple(entries), current_index=len(back))


def _pins_by_identity(
    version_pins: Mapping[str, object] | Sequence[tuple[str, object]] | None,
) -> dict[str, object]:
    if version_pins is None:
        return {}
    if isinstance(version_pins, Mapping):
        return dict(version_pins)
    try:
        return dict(version_pins)
    except (TypeError, ValueError):
        return {}


def _version_label(ordinal: int, *, empty_base: bool = False) -> str:
    """Return the trail suffix label for one endpoint (``0`` means now)."""
    if ordinal == 0:
        return "now" if not empty_base else "start"
    return f"v{ordinal}"


def _suffix_for_pin(pin: object | None) -> str:
    """Return the trail version suffix for a retained version pin.

    Read views read ``@vK``, diff views read ``@vA→vB`` (older first,
    ``0`` meaning now), and now reads nothing. A diff without a known
    base degrades to the target alone.
    """
    if pin is None:
        return ""
    try:
        ordinal = int(getattr(pin, "ordinal", 0) or 0)
        view = str(getattr(pin, "view", "read") or "read")
    except (TypeError, ValueError):
        return ""
    if view == "diff":
        raw_base = getattr(pin, "compare_base", None)
        try:
            base = int(raw_base) if raw_base is not None else None
        except (TypeError, ValueError):
            base = None
        if base is not None and base != ordinal:
            if ordinal == 0 or 0 < base < ordinal:
                return f"@{_version_label(base)}→{_version_label(ordinal)}"
            return f"@{_version_label(ordinal)}→{_version_label(base)}"
        return f"@{_version_label(ordinal)}" if ordinal else ""
    if ordinal > 0:
        return f"@v{ordinal}"
    return ""


def suffix_for_moment(moment: object | None) -> str:
    """Return the trail version suffix for the live version moment."""
    if moment is None:
        return ""
    kind = str(getattr(moment, "kind", "") or "")
    if kind == "deleted":
        return "@✖"
    if kind in ("", "loading", "now", "now_dirty"):
        view = str(getattr(moment, "view", "read") or "read")
        if view != "diff":
            return ""
        diff = getattr(moment, "diff", None)
        if diff is None:
            return ""
        try:
            base, target = int(diff[0]), int(diff[1])
        except (TypeError, ValueError, IndexError):
            return ""
        if target == 0:
            return f"@{_version_label(base)}→now"
        if base == 0:
            return f"@start→v{target}"
        if base == target:
            return f"@v{target}"
        lo, hi = (base, target) if base < target else (target, base)
        return f"@v{lo}→v{hi}"
    if kind == "past":
        try:
            ordinal = int(getattr(moment, "ordinal", 0) or 0)
        except (TypeError, ValueError):
            return ""
        view = str(getattr(moment, "view", "read") or "read")
        if view == "diff":
            return _suffix_for_moment_diff(moment, ordinal)
        return f"@v{ordinal}" if ordinal > 0 else ""
    return ""


def _suffix_for_moment_diff(moment: object, ordinal: int) -> str:
    """Return the diff-view suffix for a past moment from its endpoints."""
    diff = getattr(moment, "diff", None)
    if diff is None:
        return f"@v{ordinal}" if ordinal > 0 else ""
    try:
        base, target = int(diff[0]), int(diff[1])
    except (TypeError, ValueError, IndexError):
        return f"@v{ordinal}" if ordinal > 0 else ""
    if base == target:
        return f"@v{target}" if target > 0 else ""
    if target == 0:
        return f"@{_version_label(base)}→now"
    if base <= 0:
        return f"@start→v{target}"
    lo, hi = (base, target) if base < target else (target, base)
    return f"@v{lo}→v{hi}"


def _display_entry_from_history(
    entry: PagerTrailEntry,
    state: Literal["back", "forward"],
    version_suffix: str = "",
) -> _PagerTrailDisplayEntry:
    return _PagerTrailDisplayEntry(
        document_identity=entry.document_identity,
        document_title=entry.document_title,
        section_identity=entry.section_identity,
        section_title=entry.section_title,
        section_kind=entry.section_kind,
        state=state,
        line_mark=entry.line_mark,
        version_suffix=version_suffix,
    )


def _display_entry_from_current(
    document: PagerDocument,
    *,
    document_identity: str,
    current_section: PagerSection | None,
    line_mark: LineMark | None = None,
    version_suffix: str = "",
) -> _PagerTrailDisplayEntry:
    if current_section is None:
        return _PagerTrailDisplayEntry(
            document_identity=document_identity,
            document_title=document.title,
            section_identity=document_identity,
            section_title=document.title,
            section_kind="",
            state="current",
            line_mark=line_mark,
            version_suffix=version_suffix,
        )
    return _PagerTrailDisplayEntry(
        document_identity=document_identity,
        document_title=document.title,
        section_identity=current_section.identity,
        section_title=current_section.title,
        section_kind=current_section.kind,
        state="current",
        line_mark=line_mark,
        version_suffix=version_suffix,
    )


__all__ = [
    "TrailEntryState",
    "build_pager_help_content",
    "build_pager_trail_snapshot",
    "render_pager_help_footer",
    "render_pager_help_header",
    "render_trail_band",
    "suffix_for_moment",
    "trail_band_row_count",
]
