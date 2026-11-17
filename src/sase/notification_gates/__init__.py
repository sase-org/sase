"""Durable command-backed notification gate service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase._lazy_exports import LazyExportMap, lazy_dir, lazy_getattr

_EXPORTS: LazyExportMap = {
    "GATE_REQUEST_SCHEMA_VERSION": (
        "sase.notification_gates.models",
        "GATE_REQUEST_SCHEMA_VERSION",
    ),
    "LEGACY_GATE_REQUEST_SCHEMA_VERSION": (
        "sase.notification_gates.models",
        "LEGACY_GATE_REQUEST_SCHEMA_VERSION",
    ),
    "GATE_RESPONSE_SCHEMA_VERSION": (
        "sase.notification_gates.models",
        "GATE_RESPONSE_SCHEMA_VERSION",
    ),
    "GATE_RESULT_SCHEMA_VERSION": (
        "sase.notification_gates.models",
        "GATE_RESULT_SCHEMA_VERSION",
    ),
    "PRIVILEGED_GATE_ACTIONS": (
        "sase.notification_gates.registry",
        "PRIVILEGED_GATE_ACTIONS",
    ),
    "EditTarget": ("sase.notification_gates.edits", "EditTarget"),
    "GateActionDisplay": (
        "sase.notification_gates.model_operations",
        "GateActionDisplay",
    ),
    "GateAdapter": ("sase.notification_gates.registry", "GateAdapter"),
    "GateBranchData": ("sase.notification_gates.branches", "GateBranchData"),
    "GateBundlePaths": ("sase.notification_gates.paths", "GateBundlePaths"),
    "GateCreationResult": ("sase.notification_gates.models", "GateCreationResult"),
    "GateError": ("sase.notification_gates.models", "GateError"),
    "GateExecutionResult": (
        "sase.notification_gates.models",
        "GateExecutionResult",
    ),
    "GateGroup": ("sase.notification_gates.models", "GateGroup"),
    "GateInputField": ("sase.notification_gates.models", "GateInputField"),
    "GateOperation": ("sase.notification_gates.model_operations", "GateOperation"),
    "GateOperationResult": (
        "sase.notification_gates.model_results",
        "GateOperationResult",
    ),
    "GateOption": ("sase.notification_gates.models", "GateOption"),
    "GatePollResult": ("sase.notification_gates.poller", "GatePollResult"),
    "GateQueryError": ("sase.notification_gates.query", "GateQueryError"),
    "GateSpec": ("sase.notification_gates.models", "GateSpec"),
    "ParsedGateQuery": ("sase.notification_gates.query", "ParsedGateQuery"),
    "ResolvedGateBundle": ("sase.notification_gates.paths", "ResolvedGateBundle"),
    "accept_edited_origin": ("sase.notification_gates.edits", "accept_edited_origin"),
    "discard_origin_draft": ("sase.notification_gates.edits", "discard_origin_draft"),
    "adapter_for_action": (
        "sase.notification_gates.registry",
        "adapter_for_action",
    ),
    "adapter_for_kind": ("sase.notification_gates.registry", "adapter_for_kind"),
    "bundle_paths": ("sase.notification_gates.paths", "bundle_paths"),
    "cancel_gate": ("sase.notification_gates.executor", "cancel_gate"),
    "coerce_field_text": (
        "sase.notification_gates.input_collection",
        "coerce_field_text",
    ),
    "collected_input_fields": (
        "sase.notification_gates.input_collection",
        "collected_input_fields",
    ),
    "compile_gate_input_schema": (
        "sase.notification_gates.models",
        "compile_gate_input_schema",
    ),
    "create_gate": ("sase.notification_gates.service", "create_gate"),
    "execute_gate_operation": (
        "sase.notification_gates.operations",
        "execute_gate_operation",
    ),
    "execute_gate_selection": (
        "sase.notification_gates.executor",
        "execute_gate_selection",
    ),
    "input_arg_for_field": (
        "sase.notification_gates.input_collection",
        "input_arg_for_field",
    ),
    "option_inputs_from_values": (
        "sase.notification_gates.input_collection",
        "option_inputs_from_values",
    ),
    "origin_draft_state": ("sase.notification_gates.edits", "origin_draft_state"),
    "parse_gate_query": ("sase.notification_gates.query", "parse_gate_query"),
    "poll_gate": ("sase.notification_gates.poller", "poll_gate"),
    "refresh_gate_after_edit": (
        "sase.notification_gates.edits",
        "refresh_gate_after_edit",
    ),
    "registered_gate_kinds": (
        "sase.notification_gates.registry",
        "registered_gate_kinds",
    ),
    "resolve_edit_path": ("sase.notification_gates.edits", "resolve_edit_path"),
    "resolve_action_bundle": (
        "sase.notification_gates.paths",
        "resolve_action_bundle",
    ),
    "resolve_notification_bundle": (
        "sase.notification_gates.paths",
        "resolve_notification_bundle",
    ),
    "wait_for_gate": ("sase.notification_gates.poller", "wait_for_gate"),
}

__all__ = [
    "GATE_REQUEST_SCHEMA_VERSION",
    "LEGACY_GATE_REQUEST_SCHEMA_VERSION",
    "GATE_RESPONSE_SCHEMA_VERSION",
    "GATE_RESULT_SCHEMA_VERSION",
    "PRIVILEGED_GATE_ACTIONS",
    "EditTarget",
    "GateActionDisplay",
    "GateAdapter",
    "GateBranchData",
    "GateBundlePaths",
    "GateCreationResult",
    "GateError",
    "GateExecutionResult",
    "GateGroup",
    "GateInputField",
    "GateOperation",
    "GateOperationResult",
    "GateOption",
    "GatePollResult",
    "GateQueryError",
    "GateSpec",
    "ParsedGateQuery",
    "ResolvedGateBundle",
    "accept_edited_origin",
    "discard_origin_draft",
    "adapter_for_action",
    "adapter_for_kind",
    "bundle_paths",
    "cancel_gate",
    "coerce_field_text",
    "collected_input_fields",
    "compile_gate_input_schema",
    "create_gate",
    "execute_gate_operation",
    "execute_gate_selection",
    "input_arg_for_field",
    "option_inputs_from_values",
    "origin_draft_state",
    "parse_gate_query",
    "poll_gate",
    "refresh_gate_after_edit",
    "registered_gate_kinds",
    "resolve_edit_path",
    "resolve_action_bundle",
    "resolve_notification_bundle",
    "wait_for_gate",
]

if TYPE_CHECKING:
    from sase.notification_gates.branches import GateBranchData
    from sase.notification_gates.edits import (
        EditTarget,
        accept_edited_origin,
        discard_origin_draft,
        origin_draft_state,
        refresh_gate_after_edit,
        resolve_edit_path,
    )
    from sase.notification_gates.executor import cancel_gate, execute_gate_selection
    from sase.notification_gates.input_collection import (
        coerce_field_text,
        collected_input_fields,
        input_arg_for_field,
        option_inputs_from_values,
    )
    from sase.notification_gates.model_operations import (
        GateActionDisplay,
        GateOperation,
    )
    from sase.notification_gates.model_results import GateOperationResult
    from sase.notification_gates.models import (
        GATE_REQUEST_SCHEMA_VERSION,
        GATE_RESPONSE_SCHEMA_VERSION,
        GATE_RESULT_SCHEMA_VERSION,
        LEGACY_GATE_REQUEST_SCHEMA_VERSION,
        GateCreationResult,
        GateError,
        GateExecutionResult,
        GateGroup,
        GateInputField,
        GateOption,
        GateSpec,
        compile_gate_input_schema,
    )
    from sase.notification_gates.operations import execute_gate_operation
    from sase.notification_gates.paths import (
        GateBundlePaths,
        ResolvedGateBundle,
        bundle_paths,
        resolve_action_bundle,
        resolve_notification_bundle,
    )
    from sase.notification_gates.poller import GatePollResult, poll_gate, wait_for_gate
    from sase.notification_gates.query import (
        GateQueryError,
        ParsedGateQuery,
        parse_gate_query,
    )
    from sase.notification_gates.registry import (
        PRIVILEGED_GATE_ACTIONS,
        GateAdapter,
        adapter_for_action,
        adapter_for_kind,
        registered_gate_kinds,
    )
    from sase.notification_gates.service import create_gate


def __getattr__(name: str) -> Any:
    return lazy_getattr(__name__, globals(), _EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__
_LAZY_EXPORTS = _EXPORTS
_PEP562_HOOKS = (__getattr__, __dir__)
