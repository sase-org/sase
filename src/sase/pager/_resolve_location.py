"""Apply Rust-parsed line locations to pager link targets."""

from __future__ import annotations

from dataclasses import replace

from sase.artifact_ref_models import LinkLocation
from sase.pager.targets import LinkTarget, LinkTargetKind


def apply_link_location(
    target: LinkTarget | None,
    location: LinkLocation | None,
) -> LinkTarget | None:
    """Return *target* with *location* plumbed into scroll/edit fields."""
    if target is None or location is None:
        return target
    if target.kind is LinkTargetKind.MEDIA:
        return replace(
            target,
            edit_line=location.line,
            edit_column=location.column,
        )
    if (
        target.kind is LinkTargetKind.DOCUMENT
        and target.edit_path is not None
        and target.document is not None
        and any(section.raw_source is not None for section in target.document.sections)
    ):
        return replace(
            target,
            scroll_line=location.line,
            scroll_end_line=location.end_line,
            edit_line=location.line,
            edit_column=location.column,
        )
    return target


__all__ = ["apply_link_location"]
