"""Artifact-reference resolution for pager links."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.ace.tui.graphics import ArtifactFileViewSpec, artifact_file_view_mode
from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    resolve_cli_reference,
    resolved_file_path,
)
from sase.artifact_ref_context import artifact_ref_context
from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefFragment,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.source_language_facade import logical_source_filename
from sase.pager._resolve_common import (
    _MEDIA_MODES,
    directory_link_target,
    file_link_target,
    is_probably_text,
)
from sase.pager._resolve_file_paths import resolve_file_path_target
from sase.pager.beads import bead_entry_target_resolution, bead_link_resolution
from sase.pager.landings import card_link_target, commit_link_target
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.syntax_policy import artifact_syntax_category
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind

log = logging.getLogger(__name__)

_RESOLVED_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})


def link_target_for_artifact_entry_target(
    ref: str,
    target: ArtifactEntryTarget,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    """Resolve an already-indexed ACE artifact target into a pager landing.

    The ACE link rail's ``LinkIndex`` has already paid the graph lookup cost
    and synthesized the destination ``ArtifactEntryTarget``.  This adapter
    skips the artifact-reference discovery path for common concrete panes and
    falls back to the canonical ref resolver only when the target has no direct
    pager document shape. *context* is retained on the fast path so materialized
    reports do not land as contextless temporary files.
    """

    if target.pane_id == "files" and target.parts:
        return resolve_file_path_target(str(target.parts[-1]), context=context)
    if target.pane_id == "beads" and target.parts:
        return bead_entry_target_resolution(target, context=context).target
    canonical_ref = _ref_for_artifact_entry_target(target) or ref
    return resolve_artifact_ref_target(canonical_ref, context=context)


def resolve_artifact_ref_target(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkTarget | None:
    return resolve_artifact_ref_link(ref, context=context).target


def resolve_artifact_ref_link(
    ref: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    if context is None or not context.anchors:
        return _resolve_artifact_result(
            ref,
            artifact_context=None,
            link_context=context,
        )
    last = LinkResolution()
    for anchor in context.anchors:
        artifact_context = _artifact_ref_context_for_anchor(anchor)
        if artifact_context is None:
            continue
        resolution = _resolve_artifact_result(
            ref,
            artifact_context=artifact_context,
            link_context=context,
        )
        if resolution.target is not None:
            return resolution
        last = resolution
    return last


def _artifact_ref_context_for_anchor(anchor: LinkAnchor) -> ArtifactRefContext | None:
    try:
        return artifact_ref_context(anchor.directory, anchor.workspace_num or 1)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return None


def _resolve_artifact_result(
    ref: str,
    *,
    artifact_context: ArtifactRefContext | None,
    link_context: LinkResolutionContext | None,
) -> LinkResolution:
    try:
        result = (
            resolve_cli_reference(ref)
            if artifact_context is None
            else resolve_cli_reference(ref, context=artifact_context)
        )
    except (ImportError, RuntimeError, ValueError) as exc:
        return LinkResolution(unresolved_message=f"{ref} could not be resolved - {exc}")
    if result.resolution.status not in _RESOLVED_STATUSES:
        diagnostic = (
            getattr(result.resolution, "diagnostic", None)
            or f"{ref} could not be resolved."
        )
        retryable = (
            result.resolution.status
            in {
                "missing",
                "unknown_repo",
            }
            and "ambiguous" not in diagnostic.lower()
        )
        return LinkResolution(unresolved_message=diagnostic, retryable=retryable)

    kind_type = result.parsed.kind_type
    if kind_type == "bead":
        return bead_link_resolution(result.parsed, context=link_context)
    if kind_type in {"stitch", "commit"}:
        return LinkResolution(target=commit_link_target(result, context=link_context))

    try:
        path = resolved_file_path(result)
    except (ImportError, OSError, RuntimeError, ValueError):
        path = result.resolution.resolved_path
    if path is None:
        return LinkResolution(
            target=card_link_target(result, path=None, context=link_context)
        )
    if path.is_dir():
        return LinkResolution(target=directory_link_target(path, context=link_context))

    line = _fragment_line(result.parsed.fragment)
    mode = artifact_file_view_mode(
        path,
        kind=(result.file.kind if result.file is not None else result.parsed.kind),
    )
    if mode in _MEDIA_MODES:
        return LinkResolution(
            target=LinkTarget(
                kind=LinkTargetKind.MEDIA,
                media_specs=(ArtifactFileViewSpec(path, kind=mode),),
                edit_path=path,
                edit_line=line,
            )
        )
    logical = _artifact_logical_filename(result, path)
    file_kind = result.file.kind if result.file is not None else result.parsed.kind
    if is_probably_text(path, logical_filename=logical):
        return LinkResolution(
            target=file_link_target(
                path,
                requested_line=line,
                context=link_context,
                logical_filename=logical,
                category=artifact_syntax_category(kind_type=kind_type, kind=file_kind),
                subject_ref=result.canonical_reference,
            )
        )
    return LinkResolution(
        target=card_link_target(result, path=path, context=link_context)
    )


def _fragment_line(fragment: ArtifactRefFragment | None) -> int | None:
    if fragment is not None and fragment.type == "lines" and fragment.start is not None:
        return fragment.start
    return None


def _artifact_logical_filename(
    result: ResolvedArtifactReference,
    path: Path | None,
) -> str | None:
    artifact_file = result.file
    return logical_source_filename(
        source_path=None if artifact_file is None else artifact_file.source_path,
        vcs_relpath=None if artifact_file is None else artifact_file.vcs_relpath,
        resolved_path=None if path is None else str(path),
    )


def _ref_for_artifact_entry_target(target: ArtifactEntryTarget) -> str | None:
    try:
        from sase.ace.tui.relations.link_subject import ref_for_target

        return ref_for_target(target)
    except Exception:
        log.exception("pager: could not convert artifact target %r to ref", target)
        return None


__all__ = [
    "link_target_for_artifact_entry_target",
    "resolve_artifact_ref_link",
    "resolve_artifact_ref_target",
]
