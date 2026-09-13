"""Resolve a followed ref into a target the pager can land on.

D6's single narrow interface (``resolve_ref``), backed by the same CLI
reference resolution ``sase artifact read``/``sase bead show`` already use.
This module preserves the public import surface while the implementation is
split by resolver responsibility.
"""

from __future__ import annotations

from dataclasses import replace

from sase.artifact_ref_models import LinkLocation
from sase.artifact_ref_operations import parse_artifact_ref, split_link_location
from sase.pager._resolve_artifact_refs import (
    link_target_for_artifact_entry_target,
    resolve_artifact_ref_link,
    resolve_artifact_ref_target,
)
from sase.pager._resolve_file_paths import (
    copy_text_for_target,
    resolve_file_path_link,
    resolve_file_path_target,
)
from sase.pager._resolve_location import apply_link_location
from sase.pager.beads import bead_link_resolution
from sase.pager.link_context import LinkResolutionContext
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind


def resolve_ref(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    """Resolve *ref* to a followable target, or ``None`` if it dead-ends.

    ``ref`` is a normalized ref string: a typed artifact reference
    (``bead:sase-uk.5``), or a plain filesystem path. Never called for URL
    spans - the press table copies those directly (D6) without resolving.
    ``context`` is computed lazily for file paths and live bead detail refs;
    other typed refs with ``None`` or empty anchors keep today's
    ``resolve_cli_reference(ref)`` call.
    """
    return resolve_link(ref, context=context).target


def resolve_link(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    """Resolve *ref* and return any file-path dead-end diagnostics.

    This is the pager's one background attempt. Callers that only need the
    target should use :func:`resolve_ref`.
    """
    stripped = ref.strip()
    if not stripped:
        return LinkResolution()
    split = split_link_location(stripped)
    base = split.base
    try:
        parsed = parse_artifact_ref(base)
    except (ImportError, RuntimeError, ValueError):
        return resolve_file_path_link(stripped, context=context)
    if parsed.kind_type == "bead":
        return _apply_location(
            bead_link_resolution(parsed, context=context),
            split.location,
        )
    resolution = resolve_artifact_ref_link(base, context=context)
    if split.location is not None and resolution.target is None:
        retry = resolve_artifact_ref_link(stripped, context=context)
        if retry.target is not None:
            return retry
    return _apply_location(resolution, split.location)


def _apply_location(
    resolution: LinkResolution,
    location: LinkLocation | None,
) -> LinkResolution:
    target = apply_link_location(resolution.target, location)
    if target is resolution.target:
        return resolution
    return replace(resolution, target=target)


__all__ = [
    "LinkResolution",
    "LinkTarget",
    "LinkTargetKind",
    "copy_text_for_target",
    "link_target_for_artifact_entry_target",
    "resolve_artifact_ref_link",
    "resolve_artifact_ref_target",
    "resolve_file_path_link",
    "resolve_file_path_target",
    "resolve_link",
    "resolve_ref",
]
