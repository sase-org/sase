"""Workspace ownership and store-mutation contract.

Classifies a checkout as user-directed, read-only canonical, leased
operational, or opt-in primary-sidecar sync. Identity comes from the
checkout marker, workspace registry, and live RUNNING claims — never
from numbered-directory suffixes such as ``proj_10``.

This module is the public entry point for the contract: it builds the four
operation contexts and re-exports the types, authorization gate, and
writable-path helpers implemented in the ``_ownership_*`` modules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.running_field import WorkspaceClaim
from sase.workspace_provider._ownership_authorize import authorize_store_mutation
from sase.workspace_provider._ownership_claims import live_claim_for_workspace
from sase.workspace_provider._ownership_identity import (
    coerce_project_file,
    context_from_identity,
    identify_checkout,
    marker_for_checkout,
    primary_identity,
    store_for_project,
)
from sase.workspace_provider._ownership_paths import (
    writable_beads_dir,
    writable_checkout_dir,
    writable_kind_root,
    writable_plans_dir,
    writable_sidecar_root,
)
from sase.workspace_provider._ownership_types import (
    MACHINE_OWNED_MIN_WORKSPACE,
    AccessKind,
    MutationOrigin,
    OperationContext,
    ProcessRunningProbe,
    WorkspaceOwnershipError,
    normalize_path,
    normalize_workspace_num,
)
from sase.workspace_provider.registry import load_or_init_registry
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM


def user_directed_context(
    *,
    cwd: str | Path | None = None,
    project: str | None = None,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> OperationContext:
    """Derive a foreground user context from *cwd* without treating primary as an error."""

    start = normalize_path(cwd if cwd is not None else Path.cwd())
    identity = identify_checkout(
        start,
        project=project,
        project_file=project_file,
        config=config,
        env=env,
    )
    if identity is None:
        raise WorkspaceOwnershipError(
            f"cannot derive a user-directed context from {start}: "
            "no checkout marker or workspace-registry entry identifies this path"
        )
    return context_from_identity(
        identity,
        access_kind=AccessKind.USER_DIRECTED,
        mutation_origin=MutationOrigin.USER,
    )


def read_only_canonical_context(
    project: str,
    *,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> OperationContext:
    """Return the project's primary checkout as a read-only canonical snapshot."""

    identity = primary_identity(
        project,
        project_file=project_file,
        config=config,
        env=env,
    )
    return context_from_identity(
        identity,
        access_kind=AccessKind.READ_ONLY_CANONICAL,
        mutation_origin=MutationOrigin.USER,
    )


def leased_operational_context(
    project: str,
    workspace_num: int,
    *,
    checkout_dir: str | Path | None = None,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    claims: Sequence[WorkspaceClaim] | None = None,
    process_running: ProcessRunningProbe | None = None,
) -> OperationContext:
    """Build a machine-owned context for a claimed numbered workspace.

    Requires a matching registry entry, checkout marker, and live RUNNING
    claim. Missing evidence fails closed instead of guessing from a
    ``_<num>`` path suffix.
    """

    normalized = normalize_workspace_num(workspace_num)
    if normalized == PRIMARY_WORKSPACE_NUM:
        raise WorkspaceOwnershipError(
            "cannot lease primary workspace #0 "
            "(legacy #1 normalizes to the user-owned primary checkout)"
        )
    if normalized < MACHINE_OWNED_MIN_WORKSPACE:
        raise WorkspaceOwnershipError(
            f"cannot lease reserved workspace #{normalized}; "
            f"machine-owned leases start at #{MACHINE_OWNED_MIN_WORKSPACE}"
        )

    store = store_for_project(
        project,
        project_file=project_file,
        config=config,
        env=env,
    )
    resolved = store.resolve(normalized)
    expected = normalize_path(resolved.checkout_dir)
    checkout = expected if checkout_dir is None else normalize_path(checkout_dir)
    if checkout != expected:
        raise WorkspaceOwnershipError(
            f"checkout {checkout} does not match registry/store path "
            f"{expected} for workspace #{normalized}"
        )

    registry = load_or_init_registry(store)
    entry = registry.workspaces.get(str(normalized))
    if entry is None:
        raise WorkspaceOwnershipError(
            f"workspace #{normalized} has no registry entry; "
            "refusing to infer ownership from the checkout path"
        )
    if normalize_path(entry.checkout_dir) != checkout:
        raise WorkspaceOwnershipError(
            f"registry path for workspace #{normalized} is "
            f"{entry.checkout_dir}, not {checkout}"
        )

    marker = marker_for_checkout(checkout)
    if marker is None:
        raise WorkspaceOwnershipError(
            f"workspace #{normalized} at {checkout} has no checkout marker; "
            "refusing leased operational access"
        )
    if normalize_workspace_num(marker.workspace_num) != normalized:
        raise WorkspaceOwnershipError(
            f"checkout marker at {checkout} names workspace "
            f"#{marker.workspace_num}, not #{normalized}"
        )

    claim = live_claim_for_workspace(
        normalized,
        project_file=coerce_project_file(project, project_file),
        claims=claims,
        process_running=process_running,
    )
    if claim is None:
        raise WorkspaceOwnershipError(
            f"workspace #{normalized} at {checkout} has no matching live "
            "RUNNING claim; refusing leased operational access"
        )

    return OperationContext(
        project=project,
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=normalized,
        checkout_dir=checkout,
        primary_checkout_dir=normalize_path(store.primary_workspace_dir),
        project_file=coerce_project_file(project, project_file),
        claim_pid=claim.pid,
        claim_workflow=claim.workflow,
    )


def primary_sidecar_sync_context(
    project: str,
    role: str,
    *,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> OperationContext:
    """Allow conservative writes to one opted-in primary sidecar clone."""

    if not role or role == "agents":
        raise WorkspaceOwnershipError(
            f"sidecar role {role!r} cannot be used for primary-sidecar sync"
        )
    identity = primary_identity(
        project,
        project_file=project_file,
        config=config,
        env=env,
    )
    return OperationContext(
        project=identity.project,
        access_kind=AccessKind.PRIMARY_SIDECAR_SYNC,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=PRIMARY_WORKSPACE_NUM,
        checkout_dir=identity.checkout_dir,
        primary_checkout_dir=identity.primary_checkout_dir,
        project_file=identity.project_file,
        sidecar_role=role,
    )


__all__ = [
    "AccessKind",
    "MACHINE_OWNED_MIN_WORKSPACE",
    "MutationOrigin",
    "OperationContext",
    "ProcessRunningProbe",
    "WorkspaceOwnershipError",
    "authorize_store_mutation",
    "leased_operational_context",
    "normalize_workspace_num",
    "primary_sidecar_sync_context",
    "read_only_canonical_context",
    "user_directed_context",
    "writable_beads_dir",
    "writable_checkout_dir",
    "writable_kind_root",
    "writable_plans_dir",
    "writable_sidecar_root",
]
