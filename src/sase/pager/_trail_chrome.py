"""Pure renderers for the pager's visit-history breadcrumb chrome.

The trail data model, path-token layout, band rendering, and help-sheet
rendering live in sibling modules. This module keeps snapshot construction
and re-exports the public rendering entry points.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

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
) -> PagerTrailSnapshot:
    """Build the display snapshot from retained stacks and live current metadata."""

    entries: list[_PagerTrailDisplayEntry] = [
        _display_entry_from_history(entry, "back") for entry in back
    ]
    entries.append(
        _display_entry_from_current(
            document,
            document_identity=document_identity,
            current_section=current_section,
        )
    )
    entries.extend(
        _display_entry_from_history(entry, "forward") for entry in reversed(forward)
    )
    return PagerTrailSnapshot(entries=tuple(entries), current_index=len(back))


def _display_entry_from_history(
    entry: PagerTrailEntry,
    state: Literal["back", "forward"],
) -> _PagerTrailDisplayEntry:
    return _PagerTrailDisplayEntry(
        document_identity=entry.document_identity,
        document_title=entry.document_title,
        section_identity=entry.section_identity,
        section_title=entry.section_title,
        section_kind=entry.section_kind,
        state=state,
    )


def _display_entry_from_current(
    document: PagerDocument,
    *,
    document_identity: str,
    current_section: PagerSection | None,
) -> _PagerTrailDisplayEntry:
    if current_section is None:
        return _PagerTrailDisplayEntry(
            document_identity=document_identity,
            document_title=document.title,
            section_identity=document_identity,
            section_title=document.title,
            section_kind="",
            state="current",
        )
    return _PagerTrailDisplayEntry(
        document_identity=document_identity,
        document_title=document.title,
        section_identity=current_section.identity,
        section_title=current_section.title,
        section_kind=current_section.kind,
        state="current",
    )


__all__ = [
    "TrailEntryState",
    "build_pager_help_content",
    "build_pager_trail_snapshot",
    "render_pager_help_footer",
    "render_pager_help_header",
    "render_trail_band",
    "trail_band_row_count",
]
