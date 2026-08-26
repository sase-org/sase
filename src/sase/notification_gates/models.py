"""Public model interface for durable command-backed notification gates."""

from sase.notification_gates.model_inputs import (
    GateInputField,
    compile_gate_input_schema,
)
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
from sase.notification_gates.model_shell import (
    GATE_SHELL_DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_GATE_SHELL_PENDING_STATUS,
    DEFAULT_GATE_SHELL_SETTLED_STATUS,
    GateShellBranchSpec,
    GateShellNext,
    GateShellSpec,
)
from sase.notification_gates.model_validation import (
    GATE_REQUEST_SCHEMA_VERSION,
    GATE_RESPONSE_SCHEMA_VERSION,
    GATE_RESULT_SCHEMA_VERSION,
    JSON_SCHEMA_DIALECT,
    LEGACY_GATE_REQUEST_SCHEMA_VERSION,
    MAX_ARRAY_ITEMS,
    MAX_INPUT_BYTES,
    MAX_INPUT_DEPTH,
    MAX_OBJECT_PROPERTIES,
    NO_INPUT_SCHEMA,
    GateError,
    GateFeedbackMode,
    check_schema_bounds,
    stamp_schema_dialect,
    validate_color,
    validate_icon,
    validate_identifier,
    validate_relative_path,
)

__all__ = [
    "GATE_REQUEST_SCHEMA_VERSION",
    "GATE_RESPONSE_SCHEMA_VERSION",
    "GATE_RESULT_SCHEMA_VERSION",
    "GATE_SHELL_DEFAULT_TIMEOUT_SECONDS",
    "JSON_SCHEMA_DIALECT",
    "MAX_ARRAY_ITEMS",
    "MAX_INPUT_BYTES",
    "MAX_INPUT_DEPTH",
    "MAX_OBJECT_PROPERTIES",
    "NO_INPUT_SCHEMA",
    "GateCreationResult",
    "GateError",
    "GateExecutionResult",
    "GateFeedbackMode",
    "GateGroup",
    "GateInputField",
    "GateOption",
    "GateResource",
    "GateShellBranchSpec",
    "GateShellNext",
    "GateShellSpec",
    "GateSpec",
    "DEFAULT_GATE_SHELL_PENDING_STATUS",
    "DEFAULT_GATE_SHELL_SETTLED_STATUS",
    "check_schema_bounds",
    "compile_gate_input_schema",
    "normalize_gate_structure",
    "stamp_schema_dialect",
    "validate_color",
    "validate_icon",
    "validate_identifier",
    "validate_relative_path",
]
