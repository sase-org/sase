"""Workspace ownership and store-mutation contract.

Classifies a checkout as user-directed, read-only canonical, leased
operational, or opt-in primary-sidecar sync. Identity comes from the
checkout marker, workspace registry, and live RUNNING claims — never
from numbered-directory suffixes such as ``proj_10``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.workspace_provider.lookup import resolve_workspace_num_for_dir
from sase.workspace_provider.marker import CheckoutMarker, find_marker_from_cwd
from sase.workspace_provider.registry import load_or_init_registry
from sase.workspace_provider.store import (
    LEGACY_PRIMARY_WORKSPACE_NUM,
    PRIMARY_WORKSPACE_NUM,
    WorkspaceStore,
)

ProcessRunningProbe = Callable[[int], bool]

# Numbered checkouts below this are reserved (primary ``#0``, legacy ``#1``,
# and ``#2``-``#9``). Machine-owned leases come from the unified claim pool.
MACHINE_OWNED_MIN_WORKSPACE = 10


class MutationOrigin(StrEnum):
    """Who initiated a repository mutation."""

    USER = "user"
    MACHINE = "machine"


class AccessKind(StrEnum):
    """How an operation is allowed to touch a checkout or sidecar."""

    USER_DIRECTED = "user_directed"
    READ_ONLY_CANONICAL = "read_only_canonical"
    LEASED_OPERATIONAL = "leased_operational"
    PRIMARY_SIDECAR_SYNC = "primary_sidecar_sync"


class WorkspaceOwnershipError(RuntimeError):
    """Raised when a mutation is not allowed for the resolved checkout."""


@dataclass(frozen=True)
class OperationContext:
    """Resolved access rights for one project checkout or sidecar role."""

    project: str
    access_kind: AccessKind
    mutation_origin: MutationOrigin
    workspace_num: int
    checkout_dir: Path
    primary_checkout_dir: Path
    project_file: Path | None = None
    sidecar_role: str | None = None
    claim_pid: int | None = None
    claim_workflow: str | None = None

    @property
    def is_primary(self) -> bool:
        return self.workspace_num == PRIMARY_WORKSPACE_NUM

    @property
    def is_writable(self) -> bool:
        return self.access_kind is not AccessKind.READ_ONLY_CANONICAL


def normalize_workspace_num(workspace_num: int) -> int:
    """Map the legacy primary spelling ``#1`` onto canonical ``#0``."""

    if workspace_num == LEGACY_PRIMARY_WORKSPACE_NUM:
        return PRIMARY_WORKSPACE_NUM
    return workspace_num


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


def user_directed_context(
    *,
    cwd: str | Path | None = None,
    project: str | None = None,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> OperationContext:
    """Derive a foreground user context from *cwd* without treating primary as an error."""

    start = _normalize_path(cwd if cwd is not None else Path.cwd())
    identity = _identify_checkout(
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
    return _context_from_identity(
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

    identity = _primary_identity(
        project,
        project_file=project_file,
        config=config,
        env=env,
    )
    return _context_from_identity(
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

    store = _store_for_project(
        project,
        project_file=project_file,
        config=config,
        env=env,
    )
    resolved = store.resolve(normalized)
    expected = _normalize_path(resolved.checkout_dir)
    checkout = expected if checkout_dir is None else _normalize_path(checkout_dir)
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
    if _normalize_path(entry.checkout_dir) != checkout:
        raise WorkspaceOwnershipError(
            f"registry path for workspace #{normalized} is "
            f"{entry.checkout_dir}, not {checkout}"
        )

    marker = _marker_for_checkout(checkout)
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

    claim = _live_claim_for_workspace(
        normalized,
        project_file=_coerce_project_file(project, project_file),
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
        primary_checkout_dir=_normalize_path(store.primary_workspace_dir),
        project_file=_coerce_project_file(project, project_file),
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
    identity = _primary_identity(
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


def writable_checkout_dir(context: OperationContext) -> Path:
    """Return the checkout a writable context may mutate."""

    _require_writable(context)
    if context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC:
        raise WorkspaceOwnershipError(
            "primary-sidecar sync may not mutate the primary checkout; "
            f"use writable_sidecar_root for role {context.sidecar_role!r}"
        )
    return context.checkout_dir


def writable_kind_root(context: OperationContext, kind: str) -> Path:
    """Resolve a writable SDD kind root inside *context*."""

    _require_writable(context)
    if (
        context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC
        and kind != context.sidecar_role
    ):
        raise WorkspaceOwnershipError(
            f"primary-sidecar sync context is limited to role "
            f"{context.sidecar_role!r}, not {kind!r}"
        )
    root = _kind_root_for_context(context, kind)
    if context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC:
        _require_separate_sidecar_clone(context, root, kind)
    return root


def writable_beads_dir(context: OperationContext) -> Path:
    """Resolve the writable beads store for *context*."""

    return writable_kind_root(context, "beads")


def writable_plans_dir(context: OperationContext) -> Path:
    """Resolve the writable plans store for *context*."""

    return writable_kind_root(context, "plans")


def writable_sidecar_root(context: OperationContext, role: str) -> Path:
    """Resolve a writable sidecar clone for *role* inside *context*."""

    return writable_kind_root(context, role)


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
    target = _normalize_path(repo_root)
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
        sidecar = _kind_root_for_context(context, context.sidecar_role)
        _require_separate_sidecar_clone(context, sidecar, context.sidecar_role)
        if not _path_is_within(target, sidecar):
            raise WorkspaceOwnershipError(
                f"primary-sidecar sync may only mutate {sidecar}, not {target}"
            )
        return
    if not _path_is_within(target, context.checkout_dir):
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
    identity = _identify_checkout(
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
    return _context_from_identity(
        identity,
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
    )


@dataclass(frozen=True)
class _CheckoutIdentity:
    project: str
    workspace_num: int
    checkout_dir: Path
    primary_checkout_dir: Path
    project_file: Path | None
    marker: CheckoutMarker | None
    claim: WorkspaceClaim | None
    claim_alive: bool


def _context_from_identity(
    identity: _CheckoutIdentity,
    *,
    access_kind: AccessKind,
    mutation_origin: MutationOrigin,
) -> OperationContext:
    return OperationContext(
        project=identity.project,
        access_kind=access_kind,
        mutation_origin=mutation_origin,
        workspace_num=identity.workspace_num,
        checkout_dir=identity.checkout_dir,
        primary_checkout_dir=identity.primary_checkout_dir,
        project_file=identity.project_file,
        claim_pid=identity.claim.pid if identity.claim is not None else None,
        claim_workflow=(
            identity.claim.workflow if identity.claim is not None else None
        ),
    )


def _identify_checkout(
    path: Path,
    *,
    project: str | None,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
    claims: Sequence[WorkspaceClaim] | None = None,
    process_running: ProcessRunningProbe | None = None,
) -> _CheckoutIdentity | None:
    found = find_marker_from_cwd(str(path))
    if found is not None:
        checkout_dir, marker = found
        primary = _normalize_path(marker.primary_workspace_dir)
        workspace_num = normalize_workspace_num(marker.workspace_num)
        project_name = project or marker.project_name or marker.project_key
        spec = _coerce_project_file(project_name, project_file)
        claim = _claim_for_workspace(
            workspace_num,
            project_file=spec,
            claims=claims,
        )
        return _CheckoutIdentity(
            project=project_name,
            workspace_num=workspace_num,
            checkout_dir=_normalize_path(checkout_dir),
            primary_checkout_dir=primary,
            project_file=spec,
            marker=marker,
            claim=claim,
            claim_alive=_claim_is_alive(claim, process_running),
        )

    if project is None and project_file is None:
        return _primary_like_identity(path)
    if project is None:
        return _primary_like_identity(path)

    try:
        store = _store_for_project(
            project,
            project_file=project_file,
            config=config,
            env=env,
        )
    except WorkspaceOwnershipError:
        return None

    resolved_num = resolve_workspace_num_for_dir(
        store.primary_workspace_dir,
        str(path),
        config=config,
        env=env,
    )
    if resolved_num is None:
        resolved_num, owned = _registry_owner_for_path(store, path)
        if resolved_num is None or owned is None:
            return None
        checkout = owned
    else:
        checkout = _normalize_path(store.resolve(resolved_num).checkout_dir)

    workspace_num = normalize_workspace_num(resolved_num)
    spec = _coerce_project_file(project, project_file)
    claim = _claim_for_workspace(
        workspace_num,
        project_file=spec,
        claims=claims,
    )
    return _CheckoutIdentity(
        project=project,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        primary_checkout_dir=_normalize_path(store.primary_workspace_dir),
        project_file=spec,
        marker=None,
        claim=claim,
        claim_alive=_claim_is_alive(claim, process_running),
    )


def _primary_like_identity(path: Path) -> _CheckoutIdentity | None:
    """Treat an unmarked SASE store checkout as the user-owned primary.

    Primary checkouts do not carry ``checkout.json``. A ``.sase/sdd-store.json``
    or ``.sase/sdd`` ancestor is enough to refuse machine writes as ``#0``
    without guessing a workspace number from the directory name.
    """

    checkout = _primary_like_checkout(path)
    if checkout is None:
        return None
    return _CheckoutIdentity(
        project="",
        workspace_num=PRIMARY_WORKSPACE_NUM,
        checkout_dir=checkout,
        primary_checkout_dir=checkout,
        project_file=None,
        marker=None,
        claim=None,
        claim_alive=False,
    )


def _primary_like_checkout(path: Path) -> Path | None:
    current = path
    while True:
        sase_dir = current / ".sase"
        if (sase_dir / "sdd-store.json").is_file() or (sase_dir / "sdd").is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _primary_identity(
    project: str,
    *,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
) -> _CheckoutIdentity:
    store = _store_for_project(
        project,
        project_file=project_file,
        config=config,
        env=env,
    )
    primary = _normalize_path(store.primary_workspace_dir)
    return _CheckoutIdentity(
        project=project,
        workspace_num=PRIMARY_WORKSPACE_NUM,
        checkout_dir=primary,
        primary_checkout_dir=primary,
        project_file=_coerce_project_file(project, project_file),
        marker=None,
        claim=None,
        claim_alive=False,
    )


def _store_for_project(
    project: str,
    *,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
) -> WorkspaceStore:
    primary = _primary_dir_for_project(project, project_file=project_file)
    if primary is None:
        raise WorkspaceOwnershipError(
            f"cannot resolve primary checkout for project {project!r}"
        )
    return WorkspaceStore(str(primary), config=config, env=env)


def _primary_dir_for_project(
    project: str,
    *,
    project_file: str | Path | None,
) -> Path | None:
    spec = _coerce_project_file(project, project_file)
    if spec is not None:
        from sase.workspace_provider.utils import parse_workspace_dir

        workspace_dir = parse_workspace_dir(str(spec))
        if workspace_dir:
            primary = Path(workspace_dir.rstrip("/"))
            if primary.is_dir():
                return _normalize_path(primary)
    from sase.bead.workspace import resolve_primary_workspace_for_project

    resolved = resolve_primary_workspace_for_project(project)
    return None if resolved is None else _normalize_path(resolved)


def _registry_owner_for_path(
    store: WorkspaceStore,
    path: Path,
) -> tuple[int | None, Path | None]:
    registry = load_or_init_registry(store)
    best_num: int | None = None
    best_checkout: Path | None = None
    best_depth = -1
    for raw_num, entry in registry.workspaces.items():
        try:
            workspace_num = normalize_workspace_num(int(raw_num))
        except (TypeError, ValueError):
            continue
        checkout = _normalize_path(entry.checkout_dir)
        if not _path_is_within(path, checkout):
            continue
        depth = len(checkout.parts)
        if depth > best_depth:
            best_depth = depth
            best_num = workspace_num
            best_checkout = checkout
    return best_num, best_checkout


def _marker_for_checkout(checkout: Path) -> CheckoutMarker | None:
    found = find_marker_from_cwd(str(checkout))
    if found is None:
        return None
    found_dir, marker = found
    if _normalize_path(found_dir) != checkout:
        return None
    return marker


def _live_claim_for_workspace(
    workspace_num: int,
    *,
    project_file: Path | None,
    claims: Sequence[WorkspaceClaim] | None,
    process_running: ProcessRunningProbe | None,
) -> WorkspaceClaim | None:
    claim = _claim_for_workspace(
        workspace_num,
        project_file=project_file,
        claims=claims,
    )
    if claim is None or not _claim_is_alive(claim, process_running):
        return None
    return claim


def _claim_for_workspace(
    workspace_num: int,
    *,
    project_file: Path | None,
    claims: Sequence[WorkspaceClaim] | None,
) -> WorkspaceClaim | None:
    if claims is None:
        if project_file is None or not project_file.is_file():
            return None
        claims = get_claimed_workspaces(str(project_file))
    for claim in claims:
        if normalize_workspace_num(claim.workspace_num) == workspace_num:
            return claim
    return None


def _claim_is_alive(
    claim: WorkspaceClaim | None,
    process_running: ProcessRunningProbe | None,
) -> bool:
    if claim is None:
        return False
    probe = process_running if process_running is not None else _pid_is_alive
    try:
        return bool(probe(claim.pid))
    except (OSError, RuntimeError, ValueError):
        return False


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _kind_root_for_context(context: OperationContext, kind: str) -> Path:
    from sase.sdd.store import resolve_sdd_store

    if context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC:
        from sase._linked_repo_paths import sidecar_repo_clone_dir

        return _normalize_path(
            sidecar_repo_clone_dir(context.primary_checkout_dir, kind)
        )
    checkout = (
        context.primary_checkout_dir
        if context.access_kind is AccessKind.READ_ONLY_CANONICAL
        else context.checkout_dir
    )
    store = resolve_sdd_store(checkout, context.workspace_num)
    root = _normalize_path(store.kind_root(kind))
    if (
        context.access_kind in {AccessKind.LEASED_OPERATIONAL, AccessKind.USER_DIRECTED}
        and not context.is_primary
        and not _path_is_within(root, context.checkout_dir)
    ):
        return _workspace_local_kind_root(context.checkout_dir, store, kind)
    return root


def _workspace_local_kind_root(
    checkout: Path,
    store: Any,
    kind: str,
) -> Path:
    """Keep writable roots inside a numbered checkout when policy points at primary."""

    if getattr(store, "is_sidecar_storage", False):
        from sase._linked_repo_paths import sidecar_repo_clone_dir

        return _normalize_path(sidecar_repo_clone_dir(checkout, kind))
    if getattr(store, "is_in_tree", False):
        return checkout / "sdd" / kind
    return checkout / ".sase" / "sdd" / kind


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
        canonical = _normalize_path(root)
        if not _path_is_within(target, canonical):
            continue
        if _path_is_within(canonical, context.checkout_dir):
            continue
        if (
            context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC
            and context.sidecar_role is not None
        ):
            allowed = _kind_root_for_context(context, context.sidecar_role)
            if _path_is_within(target, allowed):
                continue
        return True
    return False


def _require_writable(context: OperationContext) -> None:
    if not context.is_writable:
        raise WorkspaceOwnershipError(
            "writable store APIs require a writable operation context, "
            "not read-only canonical access"
        )


def _require_separate_sidecar_clone(
    context: OperationContext,
    sidecar_root: Path,
    role: str,
) -> None:
    primary = context.primary_checkout_dir
    if sidecar_root == primary:
        raise WorkspaceOwnershipError(
            f"primary-sidecar sync cannot target the primary checkout for {role}"
        )
    primary_git = _checkout_git_root(primary)
    sidecar_git = _checkout_git_root(sidecar_root)
    if (
        primary_git is not None
        and sidecar_git is not None
        and primary_git == sidecar_git
    ):
        raise WorkspaceOwnershipError(
            f"primary-sidecar sync cannot mutate in-tree {role} inside {primary}"
        )


def _checkout_git_root(path: Path) -> Path | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    root = result.stdout.strip()
    if result.returncode != 0 or not root:
        return None
    return Path(root).resolve()


def _coerce_project_file(
    project: str,
    project_file: str | Path | None,
) -> Path | None:
    if project_file is not None:
        path = Path(project_file)
        return path if path.is_file() else None
    if not project:
        return None
    try:
        from sase.workflows.utils import get_project_file_path

        path = Path(get_project_file_path(project))
    except Exception:
        return None
    return path if path.is_file() else None


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "AccessKind",
    "MutationOrigin",
    "OperationContext",
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
