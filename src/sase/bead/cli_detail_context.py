"""Resolve workspace context used by bead detail commands."""

from __future__ import annotations

from pathlib import Path

from sase.artifact_ref_models import ArtifactRefContext


def design_paths_are_relative(workspace: Path | None = None) -> bool:
    """Return whether human-readable design paths should be cwd-relative."""
    from sase.sdd.store import resolve_sdd_store

    return resolve_sdd_store(_workspace_path(workspace), 1).is_in_tree


def plan_reference_roots(workspace: Path | None = None) -> tuple[Path, ...]:
    """Resolve the active plan roots once per command, never failing a read."""
    from sase.sdd.plan_refs import (
        resolve_plan_roots,
        workspace_context_for_plan_resolution,
    )

    try:
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(
            _workspace_path(workspace)
        )
        return resolve_plan_roots(workspace_dir, workspace_num)
    except Exception:
        return ()


def artifact_reference_context(
    workspace: Path | None = None,
) -> ArtifactRefContext | None:
    """Build the current workspace's reference context without failing a read."""

    from sase.artifact_ref_context import artifact_ref_context
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution

    try:
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(
            _workspace_path(workspace)
        )
        return artifact_ref_context(workspace_dir, workspace_num)
    except Exception:
        return None


def resolve_bead_page_url(bead_id: str, workspace: Path | None = None) -> str | None:
    """Resolve a hosted bead page URL for ``sase bead show`` when available."""
    from sase.sdd.hosted_links import hosted_link_resolver
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    try:
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(
            _workspace_path(workspace)
        )
        store = resolve_sdd_store(workspace_dir, workspace_num)
        return hosted_link_resolver(store, primary_root=workspace_dir).bead_url(bead_id)
    except Exception:
        return None


def resolve_bead_creator_url(
    created_by: str,
    workspace: Path | None = None,
) -> str | None:
    """Resolve a hosted agent page URL for ``sase bead show`` when available."""
    from sase.sdd.hosted_links import hosted_link_resolver
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    try:
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(
            _workspace_path(workspace)
        )
        store = resolve_sdd_store(workspace_dir, workspace_num)
        return hosted_link_resolver(store, primary_root=workspace_dir).agent_url(
            created_by
        )
    except Exception:
        return None


def _workspace_path(workspace: Path | None) -> Path:
    return Path.cwd() if workspace is None else workspace


__all__ = [
    "artifact_reference_context",
    "design_paths_are_relative",
    "plan_reference_roots",
    "resolve_bead_creator_url",
    "resolve_bead_page_url",
]
