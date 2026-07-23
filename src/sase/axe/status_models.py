"""Typed Python facade for the portable AXE status wire contract."""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding

from ._status_records import (
    AXE_STATUS_WIRE_SCHEMA_VERSION,
    AxeDesiredStateRecord,
    AxeDesiredStateValue,
    AxeLifecycleEvent,
    AxeLifecycleEventKind,
    AxeLumberjackObservation,
    AxeLumberjackReportedState,
    AxeLumberjackState,
    AxeLumberjackStatus,
    AxeMaintenanceRecord,
    AxeOrchestratorCoherence,
    AxeOrchestratorObservation,
    AxeOrchestratorState,
    AxeOrchestratorStatus,
    AxeProcessObservation,
    AxeRunnerOccupancy,
    AxeStatusCollectionError,
    AxeStatusHealth,
    AxeStatusIssue,
    AxeStatusIssueSeverity,
    AxeStatusRequest,
    AxeStatusSnapshot,
    AxeStatusState,
)
from ._status_wire import AxeStatusWireError, rehydrate_axe_status_snapshot


def classify_axe_status(request: AxeStatusRequest) -> AxeStatusSnapshot:
    """Classify one typed request through the required Rust binding."""
    version_binding = require_rust_binding("axe_status_wire_schema_version")
    binding_version = version_binding()
    if (
        not isinstance(binding_version, int)
        or isinstance(binding_version, bool)
        or binding_version != AXE_STATUS_WIRE_SCHEMA_VERSION
    ):
        raise AxeStatusWireError(
            "AXE status binding schema mismatch: "
            f"got {binding_version!r}, expected {AXE_STATUS_WIRE_SCHEMA_VERSION}"
        )

    classifier = require_rust_binding("classify_axe_status")
    payload = classifier(request.to_wire())
    return rehydrate_axe_status_snapshot(payload)


def serialize_axe_status_request(request: AxeStatusRequest) -> dict[str, Any]:
    """Return the exact recursive wire dictionary for *request*."""
    return request.to_wire()


__all__ = [
    "AXE_STATUS_WIRE_SCHEMA_VERSION",
    "AxeDesiredStateRecord",
    "AxeDesiredStateValue",
    "AxeLifecycleEvent",
    "AxeLifecycleEventKind",
    "AxeLumberjackObservation",
    "AxeLumberjackReportedState",
    "AxeLumberjackState",
    "AxeLumberjackStatus",
    "AxeMaintenanceRecord",
    "AxeOrchestratorCoherence",
    "AxeOrchestratorObservation",
    "AxeOrchestratorState",
    "AxeOrchestratorStatus",
    "AxeProcessObservation",
    "AxeRunnerOccupancy",
    "AxeStatusCollectionError",
    "AxeStatusHealth",
    "AxeStatusIssue",
    "AxeStatusIssueSeverity",
    "AxeStatusRequest",
    "AxeStatusSnapshot",
    "AxeStatusState",
    "AxeStatusWireError",
    "classify_axe_status",
    "rehydrate_axe_status_snapshot",
    "serialize_axe_status_request",
]
