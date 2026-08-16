"""Store-mutation authorization for the workspace ownership contract.

Split out of :mod:`sase.workspace_provider.ownership`; this is the gate every
SASE-initiated store write passes through before staging.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.running_field import WorkspaceClaim
from sase.workspace_provider._ownership_identity import (
    context_from_identity,
    identify_checkout,
)
from sase.workspace_provider._ownership_paths import (
    kind_root_for_context,
    require_separate_sidecar_clone,
)
from sase.workspace_provider._ownership_types import (
    AccessKind,
    MutationOrigin,
    OperationContext,
    ProcessRunningProbe,
    WorkspaceOwnershipError,
    normalize_path,
    path_is_within,
)
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM


def authorize_store_mutation(
    repo_root: str | Path,
    *,
    mutation_origin: str | MutationOrigin = MutationOrigin.USER,
    context: OperationContext | None = None,
    project: str | None = None,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    claims: Sequence[WorkspaceClaim] | None = None,
    process_running: ProcessRunningProbe | None = None,
) -> None:
    """Refuse a store mutation that the ownership contract does not allow.

    A user origin with no context preserves foreground CLI and test
    behavior. Machine origin, or any explicit context, is fail-closed:
    primary ``#0``, an unclaimed checkout, a read-only canonical location,
    and missing marker/claim evidence are rejected before staging.
    """

    origin = _parse_mutation_origin(mutation_origin)
    target = normalize_path(repo_root)
    if context is None and origin is MutationOrigin.USER:
        return
    if context is None:
        context = _infer_machine_context(
            target,
            project=project,
            project_file=project_file,
            config=config,
            env=env,
            claims=claims,
            process_running=process_running,
        )
    _authorize_context(context, target, origin=origin)


def _parse_mutation_origin(value: str | MutationOrigin) -> MutationOrigin:
    """Parse a mutation origin, failing closed on unknown values."""

    if isinstance(value, MutationOrigin):
        return value
    try:
        return MutationOrigin(value)
    except ValueError as exc:
        raise WorkspaceOwnershipError(
            f"unknown mutation origin {value!r}; expected 'user' or 'machine'"
        ) from exc


def _authorize_context(
    context: OperationContext,
    target: Path,
    *,
    origin: MutationOrigin,
) -> None:
    if context.access_kind is AccessKind.READ_ONLY_CANONICAL:
        raise WorkspaceOwnershipError(
            f"refusing mutation of read-only canonical location {target}"
        )
    if origin is MutationOrigin.MACHINE:
        if _is_foreign_canonical_store(target, context):
            raise WorkspaceOwnershipError(
                f"machine mutation refused at {target}: "
                "path is a read-only canonical location"
            )
        if context.access_kind is AccessKind.USER_DIRECTED:
            raise WorkspaceOwnershipError(
                f"machine mutation refused at {target}: "
                "user-directed access is not a machine-writable context"
            )
        if context.access_kind is AccessKind.LEASED_OPERATIONAL and context.is_primary:
            raise WorkspaceOwnershipError(
                f"machine mutation refused at {target}: "
                "path resolves to primary workspace #0"
            )
        if context.access_kind is AccessKind.LEASED_OPERATIONAL and (
            context.claim_pid is None
        ):
            raise WorkspaceOwnershipError(
                f"machine mutation refused at {target}: "
                "checkout has no matching live workspace claim"
            )
    if context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC:
        if context.sidecar_role is None:
            raise WorkspaceOwnershipError(
                f"machine mutation refused at {target}: "
                "primary-sidecar sync context is missing a role"
            )
        sidecar = kind_root_for_context(context, context.sidecar_role)
        require_separate_sidecar_clone(context, sidecar, context.sidecar_role)
        if not path_is_within(target, sidecar):
            raise WorkspaceOwnershipError(
                f"primary-sidecar sync may only mutate {sidecar}, not {target}"
            )
        return
    if not path_is_within(target, context.checkout_dir):
        raise WorkspaceOwnershipError(
            f"path {target} is outside writable checkout {context.checkout_dir}"
        )


def _infer_machine_context(
    target: Path,
    *,
    project: str | None,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
    claims: Sequence[WorkspaceClaim] | None,
    process_running: ProcessRunningProbe | None,
) -> OperationContext:
    identity = identify_checkout(
        target,
        project=project,
        project_file=project_file,
        config=config,
        env=env,
        claims=claims,
        process_running=process_running,
    )
    if identity is None:
        raise WorkspaceOwnershipError(
            f"machine mutation refused at {target}: "
            "missing checkout marker or registry evidence"
        )
    if identity.workspace_num == PRIMARY_WORKSPACE_NUM:
        raise WorkspaceOwnershipError(
            f"machine mutation refused at {target}: "
            "path resolves to primary workspace #0"
        )
    if identity.marker is None:
        raise WorkspaceOwnershipError(
            f"machine mutation refused at {target}: "
            "missing checkout marker; refusing to infer ownership from the path"
        )
    if identity.claim is None or not identity.claim_alive:
        raise WorkspaceOwnershipError(
            f"machine mutation refused at {target}: "
            "checkout has no matching live workspace claim"
        )
    return context_from_identity(
        identity,
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
    )


def _is_foreign_canonical_store(
    target: Path,
    context: OperationContext,
) -> bool:
    """Return whether *target* is a canonical primary store outside *context*."""

    if not context.project:
        return False
    from sase.bead.store_locator import (
        canonical_beads_dir_for_project,
        canonical_plans_dir_for_project,
        canonical_sidecar_dir_for_project,
    )

    roots = (
        canonical_beads_dir_for_project(context.project),
        canonical_plans_dir_for_project(context.project),
        canonical_sidecar_dir_for_project(context.project, "research"),
    )
    for root in roots:
        if root is None:
            continue
        canonical = normalize_path(root)
        if not path_is_within(target, canonical):
            continue
        if path_is_within(canonical, context.checkout_dir):
            continue
        if (
            context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC
            and context.sidecar_role is not None
        ):
            allowed = kind_root_for_context(context, context.sidecar_role)
            if path_is_within(target, allowed):
                continue
        return True
    return False


__all__ = ["authorize_store_mutation"]
