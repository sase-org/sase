"""Public model interface for durable command-backed notification gates."""

from sase.notification_gates.model_options import (
    GateGroup,
    GateOption,
    normalize_gate_structure,
    normalize_primary_branch,
)
from sase.notification_gates.model_request import GateResource, GateSpec
from sase.notification_gates.model_results import (
    GateCreationResult,
    GateExecutionResult,
)
from sase.notification_gates.model_validation import (
    GATE_REQUEST_SCHEMA_VERSION,
    GATE_RESPONSE_SCHEMA_VERSION,
    GATE_RESULT_SCHEMA_VERSION,
    LEGACY_GATE_REQUEST_SCHEMA_VERSION,
    GateError,
    GateFeedbackMode,
    validate_color,
    validate_icon,
    validate_identifier,
    validate_relative_path,
)

__all__ = [
    "GATE_REQUEST_SCHEMA_VERSION",
    "GATE_RESPONSE_SCHEMA_VERSION",
    "GATE_RESULT_SCHEMA_VERSION",
    "GateCreationResult",
    "GateError",
    "GateExecutionResult",
    "GateFeedbackMode",
    "GateGroup",
    "GateOption",
    "GateResource",
    "GateSpec",
    "normalize_gate_structure",
    "validate_color",
    "validate_icon",
    "validate_identifier",
    "validate_relative_path",
]
