"""Python facade for Rust-backed bead target routing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding

BEAD_TARGET_ROUTING_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BeadTargetStoreDescriptor:
    """One host-discovered bead store snapshot for target routing."""

    store_key: str
    project_key: str | None = None
    project_label: str | None = None
    primary_workspace: Path | None = None
    beads_dir: Path | None = None
    issue_prefix: str | None = None
    project_refs: tuple[str, ...] = ()
    issue_ids: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    def to_wire(self) -> dict[str, Any]:
        """Return the Rust routing descriptor shape."""

        return {
            "store_key": self.store_key,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "primary_workspace": (
                None if self.primary_workspace is None else str(self.primary_workspace)
            ),
            "beads_dir": None if self.beads_dir is None else str(self.beads_dir),
            "issue_prefix": self.issue_prefix,
            "project_refs": list(self.project_refs),
            "issue_ids": list(self.issue_ids),
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class _BeadTargetStoreRoute:
    """The owner store selected by the Rust target router."""

    store_key: str
    project_key: str | None = None
    project_label: str | None = None
    primary_workspace: Path | None = None
    beads_dir: Path | None = None


@dataclass(frozen=True)
class _BeadTargetRouteError:
    """Structured target-routing failure for one bead ID or one batch."""

    kind: str
    message: str
    candidates: tuple[_BeadTargetStoreRoute, ...] = ()


@dataclass(frozen=True)
class BeadTargetRoute:
    """Routing result for one requested bead ID."""

    requested_id: str
    resolved_id: str | None = None
    store: _BeadTargetStoreRoute | None = None
    error: _BeadTargetRouteError | None = None


@dataclass(frozen=True)
class _BeadTargetRoutingOutcome:
    """Rust-backed routing result for one invocation batch."""

    routes: tuple[BeadTargetRoute, ...]
    batch_error: _BeadTargetRouteError | None = None


def route_bead_targets(
    targets: tuple[str, ...] | list[str],
    *,
    local_store: BeadTargetStoreDescriptor | None = None,
    candidate_stores: tuple[BeadTargetStoreDescriptor, ...]
    | list[BeadTargetStoreDescriptor] = (),
    project_pinned: bool = False,
    require_single_store: bool = False,
) -> _BeadTargetRoutingOutcome:
    """Resolve bead targets with the shared Rust routing policy."""

    binding = require_rust_binding("bead_route_targets")
    payload: dict[str, Any] = binding(
        {
            "schema_version": BEAD_TARGET_ROUTING_WIRE_SCHEMA_VERSION,
            "targets": list(targets),
            "local_store": None if local_store is None else local_store.to_wire(),
            "candidate_stores": [store.to_wire() for store in candidate_stores],
            "project_pinned": project_pinned,
            "require_single_store": require_single_store,
        }
    )
    return _outcome_from_wire(payload)


def _outcome_from_wire(payload: dict[str, Any]) -> _BeadTargetRoutingOutcome:
    return _BeadTargetRoutingOutcome(
        routes=tuple(_route_from_wire(route) for route in payload.get("routes") or ()),
        batch_error=_error_from_wire(payload.get("batch_error")),
    )


def _route_from_wire(payload: dict[str, Any]) -> BeadTargetRoute:
    return BeadTargetRoute(
        requested_id=str(payload.get("requested_id") or ""),
        resolved_id=_optional_str(payload.get("resolved_id")),
        store=_store_route_from_wire(payload.get("store")),
        error=_error_from_wire(payload.get("error")),
    )


def _error_from_wire(payload: object) -> _BeadTargetRouteError | None:
    if not isinstance(payload, dict):
        return None
    return _BeadTargetRouteError(
        kind=str(payload.get("kind") or ""),
        message=str(payload.get("message") or ""),
        candidates=tuple(
            route
            for item in payload.get("candidates") or ()
            if (route := _store_route_from_wire(item)) is not None
        ),
    )


def _store_route_from_wire(payload: object) -> _BeadTargetStoreRoute | None:
    if not isinstance(payload, dict):
        return None
    return _BeadTargetStoreRoute(
        store_key=str(payload.get("store_key") or ""),
        project_key=_optional_str(payload.get("project_key")),
        project_label=_optional_str(payload.get("project_label")),
        primary_workspace=_optional_path(payload.get("primary_workspace")),
        beads_dir=_optional_path(payload.get("beads_dir")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_path(value: object) -> Path | None:
    text = _optional_str(value)
    return None if text is None else Path(text)


def _store_route_for_descriptor(
    store: BeadTargetStoreDescriptor,
) -> _BeadTargetStoreRoute:
    """Return the owner-route shape for one routing descriptor."""
    return _BeadTargetStoreRoute(
        store_key=store.store_key,
        project_key=store.project_key,
        project_label=store.project_label,
        primary_workspace=store.primary_workspace,
        beads_dir=store.beads_dir,
    )


def resolved_bead_target_route(
    requested_id: str,
    resolved_id: str,
    store: BeadTargetStoreDescriptor,
) -> BeadTargetRoute:
    """Build a successful route without consulting the ID router.

    The mutation's locked resolution stays the authority for existence and
    ambiguity: *resolved_id* is the requested ID carried forward (canonical
    for full IDs, raw for shorthand) so callers can pass it straight into
    the operation that performs the single store read.
    """
    return BeadTargetRoute(
        requested_id=requested_id,
        resolved_id=resolved_id,
        store=_store_route_for_descriptor(store),
        error=None,
    )


def error_bead_target_route(
    requested_id: str,
    *,
    kind: str,
    message: str,
    candidates: Sequence[BeadTargetStoreDescriptor] = (),
) -> BeadTargetRoute:
    """Build a failed route with the router's error shape."""
    return BeadTargetRoute(
        requested_id=requested_id,
        resolved_id=None,
        store=None,
        error=_BeadTargetRouteError(
            kind=kind,
            message=message,
            candidates=tuple(
                _store_route_for_descriptor(store) for store in candidates
            ),
        ),
    )


def _store_route_label(store: _BeadTargetStoreRoute) -> str:
    """Mirror the core router's multi-store display label."""
    label = store.project_label or store.project_key or store.store_key
    if store.project_key and store.project_key != label:
        return f"{label} ({store.project_key})"
    return label


def multiple_stores_batch_error(
    routes: Sequence[BeadTargetRoute],
) -> _BeadTargetRouteError | None:
    """Mirror the core router's require-single-store batch error."""
    if any(route.error is not None for route in routes):
        return None
    by_store: dict[str, _BeadTargetStoreRoute] = {}
    for route in routes:
        if route.store is None:
            continue
        by_store.setdefault(route.store.store_key, route.store)
    if len(by_store) <= 1:
        return None
    candidates = list(by_store.values())
    labels = ", ".join(_store_route_label(store) for store in candidates)
    return _BeadTargetRouteError(
        kind="incompatible_stores",
        message=(
            "bead targets resolve to multiple stores: "
            f"{labels}; split the command by project"
        ),
        candidates=tuple(candidates),
    )


__all__ = [
    "BEAD_TARGET_ROUTING_WIRE_SCHEMA_VERSION",
    "BeadTargetRoute",
    "BeadTargetStoreDescriptor",
    "error_bead_target_route",
    "multiple_stores_batch_error",
    "resolved_bead_target_route",
    "route_bead_targets",
]
