"""Plain file-path resolution for pager links."""

from __future__ import annotations

from pathlib import Path

from sase.artifact_ref_models import ArtifactRefTargetResolution, LinkLocation
from sase.artifact_ref_operations import split_link_location
from sase.pager._resolve_common import link_target_for_existing_path
from sase.pager._resolve_fragments import fragment_target_line
from sase.pager._resolve_location import apply_link_location
from sase.pager._resolve_path_search import path_candidates, search_existing_path
from sase.pager.landings import ambiguous_source_resolution
from sase.pager.link_context import LinkResolutionContext, default_link_context
from sase.pager.link_scan import LinkSpanKind
from sase.pager.source_resolve import (
    lookup_owned_source_path,
    owned_source_is_retryable,
    owned_source_is_success,
    owned_source_unresolved_message,
)
from sase.pager.targets import LinkResolution, LinkTarget


def resolve_file_path_target(
    text: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    return resolve_file_path_link(text, context=context).target


def resolve_file_path_link(
    text: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    resolved_context = _file_path_context(context)
    split = split_link_location(text)
    owned = _owned_file_path_resolution(split.base, context=resolved_context)
    if owned is not None:
        return LinkResolution(
            target=apply_link_location(owned.target, split.location),
            unresolved_message=owned.unresolved_message,
            retryable=owned.retryable,
        )
    found, fragment, locations = search_existing_path(
        split.base, context=resolved_context
    )
    if found is None:
        return LinkResolution(
            unresolved_message=(
                f"{split.base} not found (searched {locations} locations)"
            ),
        )
    resolution = _link_resolution_for_existing_path(
        found,
        fragment=fragment,
        context=resolved_context,
    )
    return LinkResolution(
        target=apply_link_location(resolution.target, split.location),
        unresolved_message=resolution.unresolved_message,
        retryable=resolution.retryable,
    )


def copy_text_for_target(
    ref: str,
    kind: str,
    *,
    context: LinkResolutionContext | None = None,
) -> str:
    """Return the text ``y`` should copy for a scanned/attached target.

    A file path copies its first existing resolution. Owner-scoped
    outcomes are terminal: a selected path copies that path, and every
    other returned lookup copies the original logical token without a
    second generic search. Unavailable generic paths copy the original
    logical token rather than inventing a cwd-joined path. Every other
    kind copies its ref text verbatim.
    """
    if kind == LinkSpanKind.FILE_PATH.value:
        resolved_context = _file_path_context(context)
        split = split_link_location(ref)
        owned = _owned_file_path_resolution(split.base, context=resolved_context)
        if owned is not None:
            path = None if owned.target is None else owned.target.edit_path
            if path is None:
                return ref
            return _copy_path_with_location(path, split.location)
        found, fragment, _locations = search_existing_path(
            split.base, context=resolved_context
        )
        if found is not None:
            target_line, fragment_message = fragment_target_line(found, fragment)
            if target_line is None and fragment_message is not None:
                return ref
            return _copy_path_with_location(found, split.location)
        return ref
    return ref


def _file_path_context(
    context: LinkResolutionContext | None,
) -> LinkResolutionContext:
    if context is not None:
        return context
    return default_link_context()


def _owned_file_path_resolution(
    text: str,
    *,
    context: LinkResolutionContext,
) -> LinkResolution | None:
    if context.owner is None:
        return None
    last: ArtifactRefTargetResolution | None = None
    last_path = text
    for path_text, fragment in path_candidates(text):
        owned = lookup_owned_source_path(path_text, context=context)
        if owned is None:
            continue
        last = owned
        last_path = path_text
        if owned_source_is_success(owned) and owned.resolved_path is not None:
            return _link_resolution_for_existing_path(
                owned.resolved_path,
                fragment=fragment,
                context=context,
            )
        if owned.status == "ambiguous" or owned.failure_category == "ambiguous":
            return ambiguous_source_resolution(path_text, owned, context)
    if last is None:
        return None
    return LinkResolution(
        unresolved_message=owned_source_unresolved_message(last_path, last),
        retryable=owned_source_is_retryable(last),
    )


def _link_resolution_for_existing_path(
    path: Path,
    *,
    fragment: str | None,
    context: LinkResolutionContext,
) -> LinkResolution:
    fragment_line, fragment_message = fragment_target_line(path, fragment)
    if fragment_message is not None:
        return LinkResolution(unresolved_message=fragment_message)
    return LinkResolution(
        target=link_target_for_existing_path(
            path,
            requested_line=fragment_line,
            context=context,
        )
    )


def _copy_path_with_location(
    path: Path,
    location: LinkLocation | None,
) -> str:
    copied = str(path)
    if location is None or not path.is_file():
        return copied
    if location.column is None:
        return f"{copied}:{location.line}"
    return f"{copied}:{location.line}:{location.column}"


__all__ = [
    "copy_text_for_target",
    "resolve_file_path_link",
    "resolve_file_path_target",
]
