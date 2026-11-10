"""Managed workspace checkout materialization and recovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.workspace_provider._utils_checkout_clone import ensure_git_clone_at
from sase.workspace_provider.store import WorkspacePath, WorkspaceStore


def recreate_managed_workspace(
    workspace_dir: str,
    workspace_num: int,
    *,
    project_file: str | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Rescue and re-materialize a numbered managed checkout from the primary.

    Last-resort recovery when in-place healing fails: the main checkout
    (local branches, stashes, detached HEAD, worktree) and every
    ``sase/repos/<role>`` sidecar clone are rescued to the durable rescue
    store outside the workspace, the checkout is moved aside for background
    deletion, and it is re-materialized through
    :func:`ensure_workspace_checkout` so the store path policy, object
    sharing, origin rewrite, registry record, checkout marker, and SDD clone
    all follow the normal path.

    A verified snapshot is required before the original is moved aside; an
    unsupported or corrupt source that cannot be saved stays intact instead
    of being deleted.

    Refuses ``workspace_num <= 1``: the primary checkout may hold the user's
    own work and is never re-created.
    """
    from sase.workspace_provider.rescue import rescue_git_repo
    from sase.workspace_provider.snapshot import (
        NestedPreservationError,
        PreservationError,
        format_preservation_locations,
        preserve_nested_repositories,
        snapshot_git_repo,
    )

    if workspace_num <= 1:
        raise RuntimeError(
            "refusing to re-create the primary workspace checkout "
            f"({workspace_dir}); numbered workspaces only"
        )
    checkout = workspace_dir.rstrip("/") or workspace_dir
    locations: list[str] = []
    try:
        snapshot_record = snapshot_git_repo(
            checkout,
            workspace_dir=checkout,
            workspace_num=workspace_num,
            label="checkout",
            reason="last-resort workspace re-creation: verified preservation",
        )
    except PreservationError as exc:
        raise RuntimeError(
            "refusing to re-create workspace checkout without complete "
            f"verified preservation ({checkout}): {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            "refusing to re-create workspace checkout without complete "
            f"verified preservation ({checkout}): {exc}"
        ) from exc
    if snapshot_record is not None:
        locations.append(str(snapshot_record.manifest_path))
        print(f"Verified preservation: {snapshot_record.manifest_path}")
    try:
        nested = preserve_nested_repositories(
            checkout,
            workspace_dir=checkout,
            workspace_num=workspace_num,
            reason="last-resort workspace re-creation: nested repository preservation",
        )
    except NestedPreservationError as exc:
        loc = format_preservation_locations([*locations, *exc.locations])
        raise RuntimeError(
            "refusing to re-create workspace checkout without complete "
            f"verified nested preservation ({checkout}): {exc}{loc}"
        ) from exc
    except PreservationError as exc:
        loc = format_preservation_locations(locations)
        raise RuntimeError(
            "refusing to re-create workspace checkout without complete "
            f"verified nested preservation ({checkout}): {exc}{loc}"
        ) from exc
    locations.extend(nested.locations)
    if nested.locations:
        print(f"Verified nested preservation: {', '.join(nested.locations)}")
    rescue_git_repo(
        checkout,
        workspace_dir=checkout,
        workspace_num=workspace_num,
        label="checkout",
        reason="last-resort workspace re-creation: rescuing main checkout",
        include_worktree=True,
    )
    from sase.axe.runner_workspace_prepare import rescue_sidecars_before_eviction

    rescue_sidecars_before_eviction(checkout, workspace_num=workspace_num)
    from sase.axe.runner_workspace_protection import (
        rescue_repo_clones_before_eviction,
    )

    rescue_repo_clones_before_eviction(
        checkout,
        workspace_num,
        reason="last-resort workspace re-creation: rescuing linked or external repo clone",
    )
    from sase._linked_repo_workspaces import move_aside_for_background_delete

    try:
        move_aside_for_background_delete(checkout, tag="sase-reclone-trash")
    except OSError as exc:
        raise RuntimeError(
            "could not move workspace checkout aside for re-creation: "
            f"{checkout}: {exc}"
        ) from exc
    from sase.sdd._paths import get_primary_workspace_dir

    primary = get_primary_workspace_dir(checkout, workspace_num)
    return ensure_workspace_checkout(
        primary, workspace_num, config=config, env=env, project_file=project_file
    )


def ensure_workspace_checkout(
    primary_workspace_dir: str,
    workspace_num: int,
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    project_file: str | None = None,
) -> str:
    """Resolve and materialize the checkout for *workspace_num*.

    Direct callers (git setup, CRS workflow runner, generic workspace
    fallback) use this helper so the path selection rules live in one
    place rather than being re-derived as ``primary_<num>`` string
    concatenations.

    Phase 4 reserved workspace numbers ``1-9``; legacy ``workspace_num
    == 1`` callers that still mean "primary" are normalized to ``#0`` so
    the store routes them through every root policy consistently.

    When the resolved checkout lives under a managed root (xdg-state or
    an absolute ``workspace.root``), this helper also records the
    materialized workspace in the registry and writes a checkout marker
    so ``sase workspace`` and managed-CWD inference can find it later.
    """
    if workspace_num == 1:
        workspace_num = 0
    if config is None:
        from sase.config.core import load_merged_config

        config = load_merged_config()
    store = WorkspaceStore(primary_workspace_dir, config=config, env=env)
    path = store.resolve(workspace_num)
    checkout_dir = ensure_git_clone_at(
        primary_workspace_dir,
        workspace_num,
        path.checkout_dir,
        assume_managed_checkout=store.root_policy != "adjacent",
        share_git_objects=store.share_git_objects,
        project_file=project_file,
    )
    _record_managed_workspace(store, path)
    try:
        from sase.sdd.store import ensure_workspace_sdd_clone

        ensure_workspace_sdd_clone(checkout_dir, workspace_num)
    except Exception:
        pass
    return checkout_dir


def _record_managed_workspace(store: WorkspaceStore, path: WorkspacePath) -> None:
    """Best-effort registry + marker write for managed (non-adjacent) roots.

    Adjacent layout keeps its legacy sibling-directory behavior and does
    not need a registry; the operation is intentionally swallowed if the
    write fails so a transient state-root permission error never blocks
    a workspace claim.
    """
    if store.root_policy == "adjacent":
        return
    if path.materialization == "primary":
        return
    try:
        from sase.workspace_provider.marker import write_marker
        from sase.workspace_provider.registry import record_workspace

        record_workspace(store, path)
        write_marker(store, path)
    except Exception:
        return
