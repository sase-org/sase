"""Durable command-backed notification gate service."""

from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.models import (
    GATE_REQUEST_SCHEMA_VERSION,
    LEGACY_GATE_REQUEST_SCHEMA_VERSION,
    GATE_RESPONSE_SCHEMA_VERSION,
    GATE_RESULT_SCHEMA_VERSION,
    GateCreationResult,
    GateError,
    GateExecutionResult,
    GateGroup,
    GateOption,
    GateSpec,
)
from sase.notification_gates.query import (
    GateQueryError,
    ParsedGateQuery,
    parse_gate_query,
)
from sase.notification_gates.paths import (
    GateBundlePaths,
    ResolvedGateBundle,
    bundle_paths,
    resolve_action_bundle,
    resolve_notification_bundle,
)
from sase.notification_gates.poller import (
    GatePollResult,
    poll_gate,
    wait_for_gate,
)
from sase.notification_gates.registry import (
    PRIVILEGED_GATE_ACTIONS,
    GateAdapter,
    adapter_for_action,
    adapter_for_kind,
    registered_gate_kinds,
)
from sase.notification_gates.service import create_gate, refresh_gate_after_edit

__all__ = [
    "GATE_REQUEST_SCHEMA_VERSION",
    "LEGACY_GATE_REQUEST_SCHEMA_VERSION",
    "GATE_RESPONSE_SCHEMA_VERSION",
    "GATE_RESULT_SCHEMA_VERSION",
    "PRIVILEGED_GATE_ACTIONS",
    "GateAdapter",
    "GateBranchData",
    "GateBundlePaths",
    "GateCreationResult",
    "GateError",
    "GateExecutionResult",
    "GateGroup",
    "GateOption",
    "GatePollResult",
    "GateQueryError",
    "GateSpec",
    "ParsedGateQuery",
    "ResolvedGateBundle",
    "adapter_for_action",
    "adapter_for_kind",
    "bundle_paths",
    "cancel_gate",
    "create_gate",
    "execute_gate_selection",
    "parse_gate_query",
    "poll_gate",
    "refresh_gate_after_edit",
    "registered_gate_kinds",
    "resolve_action_bundle",
    "resolve_notification_bundle",
    "wait_for_gate",
]
