"""Workspace-derived render context for ``sase bead show`` batches."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead._cli_show_batch_shared import (
    CreatorUrlResolver,
    PageUrlResolver,
    ReferenceContextFactory,
    ShowRenderContext,
    ShowRenderContextResolver,
    render_context_key,
)
from sase.bead.cli_detail_context import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
    resolve_bead_creator_url,
    resolve_bead_page_url,
)

if TYPE_CHECKING:
    from sase.bead.cross_project import BeadStoreOrigin


def default_show_render_context_resolver(
    *,
    default_workspace: Path | None = None,
    design_paths_are_relative_fn: Callable[..., bool] | None = None,
    plan_reference_roots_fn: Callable[..., tuple[Path, ...]] | None = None,
    artifact_reference_context_fn: Callable[..., ArtifactRefContext | None]
    | None = None,
    resolve_bead_creator_url_fn: Callable[..., str | None] | None = None,
    resolve_bead_page_url_fn: Callable[..., str | None] | None = None,
) -> ShowRenderContextResolver:
    """Return a memoizing resolver for workspace-derived show render context."""
    design_fn = design_paths_are_relative_fn or design_paths_are_relative
    plan_roots_fn = plan_reference_roots_fn or plan_reference_roots
    reference_fn = artifact_reference_context_fn or artifact_reference_context
    creator_url_fn = resolve_bead_creator_url_fn or resolve_bead_creator_url
    page_url_fn = resolve_bead_page_url_fn or resolve_bead_page_url
    cache: dict[object, ShowRenderContext] = {}

    def resolve(origin: BeadStoreOrigin | None) -> ShowRenderContext:
        key = render_context_key(origin)
        if origin is None and default_workspace is not None:
            key = (key, default_workspace)
        if key not in cache:
            workspace = (
                origin.primary_workspace if origin is not None else default_workspace
            )
            cache[key] = ShowRenderContext(
                relativize_design=_call_workspace_fn(design_fn, workspace),
                plan_roots=_call_workspace_fn(plan_roots_fn, workspace),
                design_cwd=workspace,
                reference_context_factory=_reference_context_factory(
                    reference_fn,
                    workspace,
                ),
                creator_url_for=_creator_url_resolver(creator_url_fn, workspace),
                page_url_for=_page_url_resolver(page_url_fn, workspace),
            )
        return cache[key]

    return resolve


def _call_workspace_fn(function: Callable[..., Any], workspace: Path | None) -> Any:
    if workspace is None:
        return function()
    try:
        return function(workspace)
    except TypeError:
        return function()


def _reference_context_factory(
    function: Callable[..., ArtifactRefContext | None],
    workspace: Path | None,
) -> ReferenceContextFactory:
    def factory() -> ArtifactRefContext | None:
        return _call_workspace_fn(function, workspace)

    return factory


def _creator_url_resolver(
    function: Callable[..., str | None],
    workspace: Path | None,
) -> CreatorUrlResolver:
    def resolve(created_by: str) -> str | None:
        if workspace is None:
            return function(created_by)
        try:
            return function(created_by, workspace)
        except TypeError:
            return function(created_by)

    return resolve


def _page_url_resolver(
    function: Callable[..., str | None],
    workspace: Path | None,
) -> PageUrlResolver:
    def resolve(bead_id: str) -> str | None:
        if workspace is None:
            return function(bead_id)
        try:
            return function(bead_id, workspace)
        except TypeError:
            return function(bead_id)

    return resolve


__all__ = [
    "default_show_render_context_resolver",
]
