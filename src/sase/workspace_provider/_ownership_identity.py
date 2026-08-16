"""Checkout identity resolution for the workspace ownership contract.

Split out of :mod:`sase.workspace_provider.ownership`. Identity comes from
the checkout marker, the workspace registry, and live RUNNING claims —
never from numbered-directory suffixes such as ``proj_10``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.running_field import WorkspaceClaim
from sase.workspace_provider._ownership_claims import (
    claim_for_workspace,
    claim_is_alive,
)
from sase.workspace_provider._ownership_types import (
    AccessKind,
    MutationOrigin,
    OperationContext,
    ProcessRunningProbe,
    WorkspaceOwnershipError,
    normalize_path,
    normalize_workspace_num,
    path_is_within,
)
from sase.workspace_provider.lookup import resolve_workspace_num_for_dir
from sase.workspace_provider.marker import CheckoutMarker, find_marker_from_cwd
from sase.workspace_provider.registry import load_or_init_registry
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM, WorkspaceStore


@dataclass(frozen=True)
class _CheckoutIdentity:
    """Evidence gathered about one checkout before rights are granted."""

    project: str
    workspace_num: int
    checkout_dir: Path
    primary_checkout_dir: Path
    project_file: Path | None
    marker: CheckoutMarker | None
    claim: WorkspaceClaim | None
    claim_alive: bool


def context_from_identity(
    identity: _CheckoutIdentity,
    *,
    access_kind: AccessKind,
    mutation_origin: MutationOrigin,
) -> OperationContext:
    """Grant *access_kind* rights to an already-identified checkout."""

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


def identify_checkout(
    path: Path,
    *,
    project: str | None,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
    claims: Sequence[WorkspaceClaim] | None = None,
    process_running: ProcessRunningProbe | None = None,
) -> _CheckoutIdentity | None:
    """Identify the checkout owning *path*, or ``None`` without evidence."""

    found = find_marker_from_cwd(str(path))
    if found is not None:
        checkout_dir, marker = found
        primary = normalize_path(marker.primary_workspace_dir)
        workspace_num = normalize_workspace_num(marker.workspace_num)
        project_name = project or marker.project_name or marker.project_key
        spec = coerce_project_file(project_name, project_file)
        claim = claim_for_workspace(
            workspace_num,
            project_file=spec,
            claims=claims,
        )
        return _CheckoutIdentity(
            project=project_name,
            workspace_num=workspace_num,
            checkout_dir=normalize_path(checkout_dir),
            primary_checkout_dir=primary,
            project_file=spec,
            marker=marker,
            claim=claim,
            claim_alive=claim_is_alive(claim, process_running),
        )

    if project is None and project_file is None:
        return _primary_like_identity(path)
    if project is None:
        return _primary_like_identity(path)

    try:
        store = store_for_project(
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
        checkout = normalize_path(store.resolve(resolved_num).checkout_dir)

    workspace_num = normalize_workspace_num(resolved_num)
    spec = coerce_project_file(project, project_file)
    claim = claim_for_workspace(
        workspace_num,
        project_file=spec,
        claims=claims,
    )
    return _CheckoutIdentity(
        project=project,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        primary_checkout_dir=normalize_path(store.primary_workspace_dir),
        project_file=spec,
        marker=None,
        claim=claim,
        claim_alive=claim_is_alive(claim, process_running),
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


def primary_identity(
    project: str,
    *,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
) -> _CheckoutIdentity:
    """Identify *project*'s primary checkout as workspace ``#0``."""

    store = store_for_project(
        project,
        project_file=project_file,
        config=config,
        env=env,
    )
    primary = normalize_path(store.primary_workspace_dir)
    return _CheckoutIdentity(
        project=project,
        workspace_num=PRIMARY_WORKSPACE_NUM,
        checkout_dir=primary,
        primary_checkout_dir=primary,
        project_file=coerce_project_file(project, project_file),
        marker=None,
        claim=None,
        claim_alive=False,
    )


def store_for_project(
    project: str,
    *,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
) -> WorkspaceStore:
    """Open the workspace store rooted at *project*'s primary checkout."""

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
    spec = coerce_project_file(project, project_file)
    if spec is not None:
        from sase.workspace_provider.utils import parse_workspace_dir

        workspace_dir = parse_workspace_dir(str(spec))
        if workspace_dir:
            primary = Path(workspace_dir.rstrip("/"))
            if primary.is_dir():
                return normalize_path(primary)
    from sase.bead.workspace import resolve_primary_workspace_for_project

    resolved = resolve_primary_workspace_for_project(project)
    return None if resolved is None else normalize_path(resolved)


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
        checkout = normalize_path(entry.checkout_dir)
        if not path_is_within(path, checkout):
            continue
        depth = len(checkout.parts)
        if depth > best_depth:
            best_depth = depth
            best_num = workspace_num
            best_checkout = checkout
    return best_num, best_checkout


def marker_for_checkout(checkout: Path) -> CheckoutMarker | None:
    """Return the marker written at *checkout* itself, not an ancestor's."""

    found = find_marker_from_cwd(str(checkout))
    if found is None:
        return None
    found_dir, marker = found
    if normalize_path(found_dir) != checkout:
        return None
    return marker


def coerce_project_file(
    project: str,
    project_file: str | Path | None,
) -> Path | None:
    """Resolve the project file to use, or ``None`` when none exists."""

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


__all__ = [
    "coerce_project_file",
    "context_from_identity",
    "identify_checkout",
    "marker_for_checkout",
    "primary_identity",
    "store_for_project",
]
