"""Store-backed bead resolution for pager links."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.artifact_ref_models import ArtifactRef
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager.link_context import LinkResolutionContext, default_link_context
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _LocalStore:
    view: Any
    workspace: Path | None


def bead_link_resolution(
    reference: ArtifactRef,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    """Resolve a parsed ``bead:`` artifact ref to a live detail document."""
    bead_id = reference.payload.id
    if bead_id is None or not bead_id.strip():
        return LinkResolution(
            unresolved_message=f"{reference.rendered} could not be resolved."
        )
    return _bead_id_link_resolution(bead_id, context=context)


def bead_entry_target_resolution(
    target: ArtifactEntryTarget,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    """Resolve an indexed bead pane target through the same live adapter."""
    project_ref, bead_id = _bead_entry_project_and_id(target)
    if bead_id is None:
        return LinkResolution(unresolved_message="indexed bead target is malformed.")
    return _bead_id_link_resolution(
        bead_id,
        context=context,
        project_ref=project_ref,
    )


def _bead_id_link_resolution(
    bead_id: str,
    *,
    context: LinkResolutionContext | None = None,
    project_ref: str | None = None,
) -> LinkResolution:
    """Resolve one bead ID or shorthand without requiring a generated page."""
    clean_id = bead_id.strip()
    if not clean_id:
        return LinkResolution(unresolved_message="bead id cannot be empty.")

    from sase.agent.names._registry import name_registry_load_session
    from sase.bead.cli_detail_style import DetailStyle
    from sase.bead.cli_show_batch import (
        build_show_batch_document,
        default_show_render_context_resolver,
        enrich_with_artifact_link_neighborhood,
        resolve_show_batch,
    )
    from sase.bead.cli_show_router import ShowStoreRouter

    resolved_context = _resolved_link_context(context)
    try:
        with ExitStack() as stack:
            stack.enter_context(name_registry_load_session())
            local = _open_contextual_store(stack, resolved_context)
            with ShowStoreRouter(
                None if local is None else local.view,
                project_ref=project_ref,
            ) as router:
                batch = resolve_show_batch(
                    None if local is None else local.view,
                    [clean_id],
                    format_name="full",
                    include_links=True,
                    # `sase bead show`'s own enricher exits the process when the
                    # link store cannot be read; a keypress handler cannot.
                    detail_enricher=enrich_with_artifact_link_neighborhood,
                    project_ref=project_ref,
                    router=router,
                )
                if batch.failures or not batch.entries:
                    return _failure_resolution(clean_id, batch.failures)
                return LinkResolution(
                    target=LinkTarget(
                        kind=LinkTargetKind.DOCUMENT,
                        document=build_show_batch_document(
                            batch,
                            style=DetailStyle.RICH,
                            wrap=None,
                            render_context_for=(
                                default_show_render_context_resolver(
                                    default_workspace=(
                                        None if local is None else local.workspace
                                    )
                                )
                            ),
                        ),
                    )
                )
    except Exception as exc:  # noqa: BLE001 - a keypress must not crash the pager
        log.exception("pager: could not resolve bead id %r", clean_id)
        return LinkResolution(
            unresolved_message=f"bead:{clean_id} could not be resolved - {exc}",
            retryable=True,
        )


def _resolved_link_context(
    context: LinkResolutionContext | None,
) -> LinkResolutionContext:
    if context is not None and (context.anchors or context.owner is not None):
        return context
    return default_link_context()


def _open_contextual_store(
    stack: ExitStack,
    context: LinkResolutionContext,
) -> _LocalStore | None:
    from sase.bead.cli_location import resolve_beads_location
    from sase.bead.store_locator import open_bead_project_for_beads_dir

    for directory in _context_directories(context):
        try:
            location = resolve_beads_location(
                cwd=directory,
                require_existing=True,
                materialize=False,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            log.debug(
                "pager: could not resolve bead store from %s",
                directory,
                exc_info=True,
            )
            continue
        if location is None:
            continue
        return _LocalStore(
            view=stack.enter_context(
                open_bead_project_for_beads_dir(location.beads_dir)
            ),
            workspace=_workspace_for_location(location, directory),
        )
    return None


def _context_directories(context: LinkResolutionContext) -> Iterator[Path]:
    seen: set[Path] = set()

    def add(path: str | Path | None) -> Iterator[Path]:
        if path is None:
            return
        try:
            resolved = Path(path).expanduser().resolve(strict=False)
        except OSError:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        yield resolved

    owner = context.owner
    if owner is not None:
        yield from add(owner.source_directory)
        for checkout in owner.checkout_candidates:
            yield from add(checkout)
    for anchor in context.anchors:
        yield from add(anchor.directory)


def _workspace_for_location(location: object, directory: Path) -> Path | None:
    marker_workspace = _marker_primary_workspace(directory)
    if marker_workspace is not None:
        return marker_workspace

    root = getattr(location, "root", None)
    beads_dirname = getattr(location, "beads_dirname", None)
    if not isinstance(root, Path):
        return None
    if beads_dirname == "sdd/beads":
        return root
    if root.parts[-2:] == (".sase", "sdd"):
        return root.parents[1]
    return directory if directory.is_dir() else directory.parent


def _marker_primary_workspace(directory: Path) -> Path | None:
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(directory))
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if found is None:
        return None
    raw = found[1].primary_workspace_dir.strip()
    if not raw:
        return None
    return Path(raw.rstrip("/")).expanduser().resolve(strict=False)


def _failure_resolution(bead_id: str, failures: tuple[object, ...]) -> LinkResolution:
    message = _failure_message(bead_id, failures)
    return LinkResolution(
        unresolved_message=message,
        retryable=_failure_is_retryable(message),
    )


def _failure_message(bead_id: str, failures: tuple[object, ...]) -> str:
    messages = [str(getattr(failure, "message", "")) for failure in failures]
    messages = [message for message in messages if message]
    if not messages:
        return f"issue not found: {bead_id}"
    return "; ".join(dict.fromkeys(messages))


def _failure_is_retryable(message: str) -> bool:
    lowered = message.lower()
    if "ambiguous" in lowered:
        return False
    return any(
        phrase in lowered
        for phrase in (
            "not materialized",
            "not readable",
            "not available",
            "no local bead store",
            "missing checkout",
            "temporar",
            "unavailable",
        )
    )


def _bead_entry_project_and_id(
    target: ArtifactEntryTarget,
) -> tuple[str | None, str | None]:
    if target.pane_id != "beads" or not target.parts:
        return None, None
    if len(target.parts) >= 3:
        project_ref = target.parts[0].strip() or None
        bead_id = target.parts[-1].strip() or None
        return project_ref, bead_id
    return None, target.parts[-1].strip() or None


__all__ = [
    "bead_entry_target_resolution",
    "bead_link_resolution",
]
