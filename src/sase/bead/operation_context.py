"""Routed bead-store contexts for CLI read and mutation operations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead.cli_location import (
    BeadsLocation,
    resolved_beads_location_is_usable,
)
from sase.bead.cross_project import (
    BeadStoreSnapshot,
    enabled_project_store_snapshots,
)
from sase.bead.project import BEADS_DIRNAME
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.core.bead_target_routing_facade import (
    BeadTargetRoute,
    BeadTargetStoreDescriptor,
    route_bead_targets,
)


class BeadOperationRoutingError(RuntimeError):
    """Raised when bead target routing cannot produce one operation context."""


@dataclass(frozen=True)
class _RoutedBeadTarget:
    """One caller-supplied target resolved to a canonical bead ID and owner."""

    requested_id: str
    resolved_id: str
    route: BeadTargetRoute


@dataclass(frozen=True)
class BeadOperationContext:
    """One explicit bead-store operation context.

    ``invocation_cwd`` preserves the user's path semantics for free-form file
    inputs. ``location`` and ``ownership_context`` identify the selected owner
    used for store access, commits, publication, and refresh.
    """

    invocation_cwd: Path
    location: BeadsLocation
    project_key: str | None = None
    project_label: str | None = None
    primary_workspace: Path | None = None
    ownership_context: Any | None = None
    targets: tuple[_RoutedBeadTarget, ...] = ()

    @property
    def beads_dir(self) -> Path:
        return self.location.beads_dir

    @property
    def read_beads_dirs(self) -> list[Path]:
        return [self.beads_dir]

    @property
    def write_beads_dir(self) -> Path:
        return self.beads_dir

    @property
    def relativize_design_paths(self) -> bool:
        return self.location.beads_dirname == BEADS_DIRNAME

    @property
    def read_only(self) -> bool:
        return self.location.read_only

    @property
    def resolved_ids(self) -> tuple[str, ...]:
        return tuple(target.resolved_id for target in self.targets)


def local_operation_context(
    *,
    cwd: Path | None = None,
    materialize: bool = False,
    require_existing: bool = True,
) -> BeadOperationContext | None:
    """Return the caller's current bead-store context without target routing."""

    invocation_cwd = _invocation_cwd(cwd)
    location = _resolve_beads_location(
        cwd=invocation_cwd,
        materialize=materialize,
        require_existing=require_existing,
    )
    if location is None:
        return None
    return BeadOperationContext(
        invocation_cwd=invocation_cwd,
        location=location,
        ownership_context=_user_directed_context_for_cwd(invocation_cwd),
    )


def resolve_operation_context_for_targets(
    targets: Sequence[str],
    *,
    cwd: Path | None = None,
    require_single_store: bool = True,
    for_write: bool = False,
    materialize: bool = False,
) -> BeadOperationContext:
    """Resolve bead targets to one owner-qualified operation context.

    Shorthand resolution remains local; full IDs may fall back to enabled
    project stores. When ``require_single_store`` is true, a mixed-owner batch
    fails before a caller can mutate anything.
    """

    invocation_cwd = _invocation_cwd(cwd)
    local_location = _local_location_for_resolution(
        invocation_cwd,
        materialize=materialize,
    )
    local_descriptor = _descriptor_for_location(local_location, project_key=None)
    snapshots = _candidate_snapshots_for_targets(targets, local_descriptor)
    outcome = route_bead_targets(
        list(targets),
        local_store=local_descriptor,
        candidate_stores=[snapshot.descriptor() for snapshot in snapshots],
        require_single_store=require_single_store,
    )
    if outcome.batch_error is not None:
        raise BeadOperationRoutingError(outcome.batch_error.message)

    routed_targets: list[_RoutedBeadTarget] = []
    for route in outcome.routes:
        if route.error is not None:
            if route.error.kind == "not_found":
                raise BeadOperationRoutingError(
                    f"issue not found: {route.requested_id}"
                )
            raise BeadOperationRoutingError(route.error.message)
        if route.resolved_id is None or route.store is None:
            raise BeadOperationRoutingError(f"issue not found: {route.requested_id}")
        routed_targets.append(
            _RoutedBeadTarget(
                requested_id=route.requested_id,
                resolved_id=route.resolved_id,
                route=route,
            )
        )

    if not routed_targets:
        context = local_operation_context(
            cwd=invocation_cwd,
            materialize=materialize,
            require_existing=not materialize,
        )
        if context is None:
            raise BeadOperationRoutingError("no local bead store is available")
        return context

    store = routed_targets[0].route.store
    assert store is not None
    location, ownership_context = _location_for_store_route(
        store,
        invocation_cwd=invocation_cwd,
        local_location=local_location,
        for_write=for_write,
        materialize=materialize,
    )
    return BeadOperationContext(
        invocation_cwd=invocation_cwd,
        location=location,
        project_key=store.project_key,
        project_label=store.project_label,
        primary_workspace=store.primary_workspace,
        ownership_context=ownership_context,
        targets=tuple(routed_targets),
    )


def location_from_operation_context(
    context: BeadOperationContext | None,
    *,
    cwd: Path | None = None,
    materialize: bool = False,
    require_existing: bool = True,
) -> BeadsLocation | None:
    """Resolve a location, honoring an already-routed context when present."""

    if context is not None:
        return context.location
    return _resolve_beads_location(
        cwd=cwd,
        materialize=materialize,
        require_existing=require_existing,
    )


def project_for_operation_context(context: BeadOperationContext) -> Any:
    """Open the :class:`BeadProject` selected by *context*."""

    _refuse_read_only(context.location, operation="mutation")
    return open_bead_project_for_beads_dir(context.beads_dir)


def read_view_for_operation_context(context: BeadOperationContext) -> Any:
    """Open a read view for the store selected by *context*."""

    return open_bead_project_for_beads_dir(context.beads_dir)


def ownership_context_for_commit(context: BeadOperationContext | None) -> Any | None:
    """Return the workspace ownership context to pass into commit helpers."""

    return None if context is None else context.ownership_context


def _invocation_cwd(cwd: Path | None) -> Path:
    return (Path.cwd() if cwd is None else cwd).expanduser().resolve()


def _resolve_beads_location(*args: Any, **kwargs: Any) -> BeadsLocation | None:
    from sase.bead import cli_common

    return cli_common.resolve_beads_location(*args, **kwargs)


def _local_location_for_resolution(
    invocation_cwd: Path,
    *,
    materialize: bool,
) -> BeadsLocation | None:
    del materialize
    location = _resolve_beads_location(cwd=invocation_cwd, require_existing=True)
    return location


def _descriptor_for_location(
    location: BeadsLocation | None,
    *,
    project_key: str | None,
) -> BeadTargetStoreDescriptor | None:
    if location is None:
        return None
    issue_ids: set[str] = set()
    unavailable_reason: str | None = None
    try:
        with open_bead_project_for_beads_dir(location.beads_dir) as project:
            issue_ids = {issue.id for issue in project.list_issues()}
    except (OSError, RuntimeError, ValueError) as exc:
        unavailable_reason = str(exc) or "not readable"
    return BeadTargetStoreDescriptor(
        store_key=_store_key(location.beads_dir),
        project_key=project_key,
        project_label=project_key,
        primary_workspace=None,
        beads_dir=location.beads_dir,
        issue_prefix=_stored_issue_prefix(location.beads_dir),
        project_refs=() if project_key is None else (project_key,),
        issue_ids=tuple(sorted(issue_ids)),
        unavailable_reason=unavailable_reason,
    )


def _candidate_snapshots_for_targets(
    targets: Sequence[str],
    local_descriptor: BeadTargetStoreDescriptor | None,
) -> tuple[BeadStoreSnapshot, ...]:
    if not any(_looks_like_full_bead_id(target) for target in targets):
        return ()
    snapshots = enabled_project_store_snapshots()
    if local_descriptor is None:
        return snapshots
    local_key = local_descriptor.store_key
    return tuple(snapshot for snapshot in snapshots if snapshot.store_key != local_key)


def _location_for_store_route(
    store: Any,
    *,
    invocation_cwd: Path,
    local_location: BeadsLocation | None,
    for_write: bool,
    materialize: bool,
) -> tuple[BeadsLocation, Any | None]:
    store_beads_dir = getattr(store, "beads_dir", None)
    if store_beads_dir is None:
        raise BeadOperationRoutingError(
            f"project {_store_label(store)!r} owns the target, but its bead store "
            "is not materialized on this machine"
        )
    if local_location is not None and _same_path(
        local_location.beads_dir, store_beads_dir
    ):
        if for_write:
            _refuse_read_only(local_location, operation="mutation")
        return local_location, _user_directed_context_for_cwd(invocation_cwd)

    project_key = getattr(store, "project_key", None)
    primary = getattr(store, "primary_workspace", None)
    if project_key is None or primary is None:
        return _location_from_beads_dir(store_beads_dir), None

    ownership_context = _user_directed_context_for_project(project_key, primary)
    writable_beads_dir = _writable_beads_dir_for_context(ownership_context)
    owner_location = _resolve_beads_location(
        cwd=primary,
        materialize=materialize or for_write,
        require_existing=not (materialize or for_write),
    )
    if owner_location is None:
        raise BeadOperationRoutingError(
            f"project {_store_label(store)!r} bead store is not materialized "
            "on this machine"
        )
    if not _same_path(owner_location.beads_dir, store_beads_dir):
        raise BeadOperationRoutingError(
            f"resolved read store {store_beads_dir} and writable store "
            f"{owner_location.beads_dir} disagree for project {_store_label(store)!r}"
        )
    if writable_beads_dir is not None and not _same_path(
        writable_beads_dir,
        store_beads_dir,
    ):
        raise BeadOperationRoutingError(
            f"routed read store {store_beads_dir} is not the writable bead store "
            f"{writable_beads_dir} for project {_store_label(store)!r}"
        )
    if for_write:
        _refuse_read_only(owner_location, operation="mutation")
    return owner_location, ownership_context


def _user_directed_context_for_cwd(cwd: Path) -> Any | None:
    try:
        from sase.workspace_provider import ownership

        return ownership.user_directed_context(cwd=cwd)
    except Exception:
        return None


def _user_directed_context_for_project(project_key: str, primary: Path) -> Any | None:
    try:
        from sase.workspace_provider import ownership

        context = ownership.user_directed_context(cwd=primary, project=project_key)
        return context
    except Exception as exc:
        raise BeadOperationRoutingError(
            f"project {project_key!r} cannot be opened for writable bead access: {exc}"
        ) from exc


def _writable_beads_dir_for_context(context: Any | None) -> Path | None:
    if context is None:
        return None
    try:
        from sase.workspace_provider import ownership

        return ownership.writable_beads_dir(context)
    except Exception as exc:
        project = getattr(context, "project", "unknown")
        raise BeadOperationRoutingError(
            f"project {project!r} cannot provide a writable bead store: {exc}"
        ) from exc


def _location_from_beads_dir(beads_dir: Path) -> BeadsLocation:
    beads_dir = beads_dir.expanduser().resolve(strict=False)
    parts = beads_dir.parts
    if len(parts) >= 2 and parts[-2:] == ("sdd", "beads"):
        return BeadsLocation(beads_dir.parents[1], "sdd/beads", storage="in_tree")
    if len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"):
        return BeadsLocation(beads_dir.parent, "beads", storage="local")
    return BeadsLocation(beads_dir.parent, beads_dir.name)


def _refuse_read_only(
    location: BeadsLocation | None,
    *,
    operation: str,
) -> None:
    if location is None or not location.read_only:
        return
    raise BeadOperationRoutingError(
        f"Refusing bead-store {operation} from a plain checkout: "
        f"{location.beads_dir} was discovered through a checkout-local "
        ".sase/sdd-store.json record and is available for reads only."
    )


def _stored_issue_prefix(beads_dir: Path) -> str | None:
    try:
        payload = json.loads((beads_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    prefix = payload.get("issue_prefix")
    return prefix if isinstance(prefix, str) and prefix else None


def _looks_like_full_bead_id(value: str) -> bool:
    from sase.bead.cross_project import bead_id_prefix

    return bead_id_prefix(value) is not None


def _store_key(beads_dir: Path) -> str:
    return str(beads_dir.expanduser().resolve(strict=False))


def _same_path(left: Path, right: Path) -> bool:
    return _store_key(left) == _store_key(right)


def _store_label(store: Any) -> str:
    return (
        getattr(store, "project_label", None)
        or getattr(store, "project_key", None)
        or getattr(store, "store_key", None)
        or "unknown"
    )


__all__ = [
    "BeadOperationContext",
    "BeadOperationRoutingError",
    "local_operation_context",
    "location_from_operation_context",
    "ownership_context_for_commit",
    "project_for_operation_context",
    "read_view_for_operation_context",
    "resolve_operation_context_for_targets",
]
