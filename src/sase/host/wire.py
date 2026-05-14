"""Forward-compatible Python wire models for provider/plugin host IPC."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION = 1
HOST_CAP_IPC_V1 = "host.ipc.v1"
HOST_CAP_MANIFEST_V1 = "host.manifest.v1"
HOST_CAP_LLM_METADATA = "host.llm.metadata"
HOST_CAP_LLM_INVOKE = "host.llm.invoke"
HOST_CAP_XPROMPT_CATALOG = "host.xprompt.catalog"
HOST_CAP_VCS_QUERY = "host.vcs.query"
HOST_CAP_WORKSPACE_METADATA = "host.workspace.metadata"
HOST_CAP_WORKSPACE_RESOLVE_REF = "host.workspace.resolve_ref"
HOST_CAP_WORKFLOW_STEP = "host.workflow.step"
HOST_CAP_RESOURCE_POLICY_DIAGNOSTICS = "host.resource_policy.diagnostics"

HOST_OPERATION_FAMILIES = (
    "llm",
    "vcs",
    "workspace",
    "xprompt",
    "config",
    "workflow.step",
)

HOST_ERROR_CODES = (
    "host_unavailable",
    "host_timeout",
    "host_cancelled",
    "plugin_not_found",
    "operation_unsupported",
    "capability_denied",
    "network_denied",
    "resource_limit_exceeded",
    "invalid_side_effect_intent",
    "host_protocol_error",
    "provider_execution_failed",
    "manifest_invalid",
)


@dataclass(frozen=True)
class HostActorWire:
    schema_version: int
    actor_type: str
    name: str
    version: str | None = None
    runtime: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostWorkspaceIdentityWire:
    project_id: str
    project_dir: str | None = None
    workspace_dir: str | None = None
    changespec: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostOperationSelectorWire:
    family: str
    operation: str
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostDeadlineWire:
    timeout_ms: int | None = None
    deadline_unix_ms: int | None = None
    cancellation_token: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostEnvironmentPolicyWire:
    inherit: bool = False
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostNetworkPolicyWire:
    mode: str
    allowed_hosts: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostProcessPolicyWire:
    spawn_allowed: bool = False
    allowed_commands: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostEnvironmentRequirementWire:
    required_vars: tuple[str, ...] = ()
    optional_vars: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostManifestWire:
    schema_version: int
    plugin_id: str
    version: str
    network: HostNetworkPolicyWire
    process: HostProcessPolicyWire
    environment: HostEnvironmentRequirementWire
    operation_families: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    filesystem_roots: tuple[str, ...] = ()
    timeout_hints_ms: Mapping[str, int] = field(default_factory=dict)
    warm_host_eligible: bool = False
    wasm_compatible: bool = False
    wasm_notes: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostRequestEnvelopeWire:
    schema_version: int
    request_id: str
    deadline: HostDeadlineWire
    actor: HostActorWire
    operation: HostOperationSelectorWire
    workspace: HostWorkspaceIdentityWire
    environment: HostEnvironmentPolicyWire
    declared_capabilities: tuple[str, ...] = ()
    manifest: HostManifestWire | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostFallbackWire:
    available: bool
    reason: str | None = None
    message: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostErrorWire:
    schema_version: int
    code: str
    message: str
    retryable: bool
    fallback: HostFallbackWire
    target: str | None = None
    details: Mapping[str, Any] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostLogRecordWire:
    level: str
    message: str
    target: str | None = None
    stream: str | None = None
    timestamp: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostResourceUsageWire:
    wall_ms: int
    cpu_ms: int | None = None
    peak_rss_bytes: int | None = None
    spawned_processes: int = 0
    network_requests: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostSideEffectIntentWire:
    type: str
    data: Mapping[str, Any]
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class HostResponseEnvelopeWire:
    schema_version: int
    request_id: str
    status: str
    result: Mapping[str, Any] = field(default_factory=dict)
    error: HostErrorWire | None = None
    logs: tuple[HostLogRecordWire, ...] = ()
    duration_ms: int = 0
    resource_usage: HostResourceUsageWire | None = None
    side_effects: tuple[HostSideEffectIntentWire, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)


class FakeInProcessHostTransport:
    """Small test transport that round-trips host envelopes in-process."""

    def __init__(
        self,
        handler: Callable[[HostRequestEnvelopeWire], Mapping[str, Any]] | None = None,
    ) -> None:
        self._handler = handler or (lambda request: {"request_id": request.request_id})

    def request(
        self, envelope: HostRequestEnvelopeWire | Mapping[str, Any]
    ) -> HostResponseEnvelopeWire:
        request = (
            envelope
            if isinstance(envelope, HostRequestEnvelopeWire)
            else host_request_from_dict(dict(envelope))
        )
        result = self._handler(request)
        return HostResponseEnvelopeWire(
            schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            request_id=request.request_id,
            status="ok",
            result=dict(result),
        )


def host_wire_to_json_dict(record: Any) -> Any:
    """Project host wire models to JSON-safe dict/list/scalar values."""

    if isinstance(record, (list, tuple)):
        return [host_wire_to_json_dict(item) for item in record]
    if isinstance(record, Mapping):
        return {str(k): host_wire_to_json_dict(v) for k, v in record.items()}
    if is_dataclass(record):
        payload: dict[str, Any] = {}
        extra = getattr(record, "extra", {}) or {}
        payload.update(host_wire_to_json_dict(extra))
        for item in fields(record):
            if item.name == "extra":
                continue
            value = getattr(record, item.name)
            key = "type" if item.name == "type" else item.name
            payload[key] = host_wire_to_json_dict(value)
        return payload
    return record


def host_request_from_dict(data: dict[str, Any]) -> HostRequestEnvelopeWire:
    _check_schema(data)
    return HostRequestEnvelopeWire(
        schema_version=int(data["schema_version"]),
        request_id=str(data["request_id"]),
        deadline=_deadline_from_dict(dict(data["deadline"])),
        actor=_actor_from_dict(dict(data["actor"])),
        operation=_operation_from_dict(dict(data["operation"])),
        declared_capabilities=_str_tuple(data.get("declared_capabilities") or ()),
        workspace=_workspace_from_dict(dict(data["workspace"])),
        environment=_environment_policy_from_dict(dict(data["environment"])),
        manifest=(
            None
            if data.get("manifest") is None
            else _manifest_from_dict(dict(data["manifest"]))
        ),
        payload=_mapping(data.get("payload") or {}),
        extra=_extra(data, _field_names(HostRequestEnvelopeWire)),
    )


def host_response_from_dict(data: dict[str, Any]) -> HostResponseEnvelopeWire:
    _check_schema(data)
    resource = data.get("resource_usage")
    return HostResponseEnvelopeWire(
        schema_version=int(data["schema_version"]),
        request_id=str(data["request_id"]),
        status=str(data["status"]),
        result=_mapping(data.get("result") or {}),
        error=(
            None if data.get("error") is None else _error_from_dict(dict(data["error"]))
        ),
        logs=tuple(_log_from_dict(dict(item)) for item in data.get("logs") or ()),
        duration_ms=int(data.get("duration_ms", 0)),
        resource_usage=(
            None if resource is None else _resource_usage_from_dict(dict(resource))
        ),
        side_effects=tuple(
            _side_effect_from_dict(dict(item))
            for item in data.get("side_effects") or ()
        ),
        extra=_extra(data, _field_names(HostResponseEnvelopeWire)),
    )


def _actor_from_dict(data: dict[str, Any]) -> HostActorWire:
    _check_schema(data)
    return HostActorWire(
        schema_version=int(data["schema_version"]),
        actor_type=str(data["actor_type"]),
        name=str(data["name"]),
        version=_optional_str(data.get("version")),
        runtime=_optional_str(data.get("runtime")),
        extra=_extra(data, _field_names(HostActorWire)),
    )


def _workspace_from_dict(data: dict[str, Any]) -> HostWorkspaceIdentityWire:
    return HostWorkspaceIdentityWire(
        project_id=str(data["project_id"]),
        project_dir=_optional_str(data.get("project_dir")),
        workspace_dir=_optional_str(data.get("workspace_dir")),
        changespec=_optional_str(data.get("changespec")),
        extra=_extra(data, _field_names(HostWorkspaceIdentityWire)),
    )


def _operation_from_dict(data: dict[str, Any]) -> HostOperationSelectorWire:
    return HostOperationSelectorWire(
        family=str(data["family"]),
        operation=str(data["operation"]),
        extra=_extra(data, _field_names(HostOperationSelectorWire)),
    )


def _deadline_from_dict(data: dict[str, Any]) -> HostDeadlineWire:
    return HostDeadlineWire(
        timeout_ms=_optional_int(data.get("timeout_ms")),
        deadline_unix_ms=_optional_int(data.get("deadline_unix_ms")),
        cancellation_token=_optional_str(data.get("cancellation_token")),
        extra=_extra(data, _field_names(HostDeadlineWire)),
    )


def _environment_policy_from_dict(data: dict[str, Any]) -> HostEnvironmentPolicyWire:
    return HostEnvironmentPolicyWire(
        inherit=bool(data.get("inherit", False)),
        allow=_str_tuple(data.get("allow") or ()),
        deny=_str_tuple(data.get("deny") or ()),
        required=_str_tuple(data.get("required") or ()),
        extra=_extra(data, _field_names(HostEnvironmentPolicyWire)),
    )


def _network_policy_from_dict(data: dict[str, Any]) -> HostNetworkPolicyWire:
    return HostNetworkPolicyWire(
        mode=str(data["mode"]),
        allowed_hosts=_str_tuple(data.get("allowed_hosts") or ()),
        extra=_extra(data, _field_names(HostNetworkPolicyWire)),
    )


def _process_policy_from_dict(data: dict[str, Any]) -> HostProcessPolicyWire:
    return HostProcessPolicyWire(
        spawn_allowed=bool(data.get("spawn_allowed", False)),
        allowed_commands=_str_tuple(data.get("allowed_commands") or ()),
        extra=_extra(data, _field_names(HostProcessPolicyWire)),
    )


def _environment_requirement_from_dict(
    data: dict[str, Any],
) -> HostEnvironmentRequirementWire:
    return HostEnvironmentRequirementWire(
        required_vars=_str_tuple(data.get("required_vars") or ()),
        optional_vars=_str_tuple(data.get("optional_vars") or ()),
        extra=_extra(data, _field_names(HostEnvironmentRequirementWire)),
    )


def _manifest_from_dict(data: dict[str, Any]) -> HostManifestWire:
    _check_schema(data)
    return HostManifestWire(
        schema_version=int(data["schema_version"]),
        plugin_id=str(data["plugin_id"]),
        version=str(data["version"]),
        operation_families=_str_tuple(data.get("operation_families") or ()),
        capabilities=_str_tuple(data.get("capabilities") or ()),
        network=_network_policy_from_dict(dict(data["network"])),
        filesystem_roots=_str_tuple(data.get("filesystem_roots") or ()),
        process=_process_policy_from_dict(dict(data["process"])),
        environment=_environment_requirement_from_dict(dict(data["environment"])),
        timeout_hints_ms={
            str(key): int(value)
            for key, value in _mapping(data.get("timeout_hints_ms") or {}).items()
        },
        warm_host_eligible=bool(data.get("warm_host_eligible", False)),
        wasm_compatible=bool(data.get("wasm_compatible", False)),
        wasm_notes=_optional_str(data.get("wasm_notes")),
        extra=_extra(data, _field_names(HostManifestWire)),
    )


def _fallback_from_dict(data: dict[str, Any]) -> HostFallbackWire:
    return HostFallbackWire(
        available=bool(data["available"]),
        reason=_optional_str(data.get("reason")),
        message=_optional_str(data.get("message")),
        extra=_extra(data, _field_names(HostFallbackWire)),
    )


def _error_from_dict(data: dict[str, Any]) -> HostErrorWire:
    _check_schema(data)
    return HostErrorWire(
        schema_version=int(data["schema_version"]),
        code=str(data["code"]),
        message=str(data["message"]),
        retryable=bool(data["retryable"]),
        target=_optional_str(data.get("target")),
        details=(
            None if data.get("details") is None else _mapping(dict(data["details"]))
        ),
        fallback=_fallback_from_dict(dict(data["fallback"])),
        extra=_extra(data, _field_names(HostErrorWire)),
    )


def _log_from_dict(data: dict[str, Any]) -> HostLogRecordWire:
    return HostLogRecordWire(
        level=str(data["level"]),
        message=str(data["message"]),
        target=_optional_str(data.get("target")),
        stream=_optional_str(data.get("stream")),
        timestamp=_optional_str(data.get("timestamp")),
        extra=_extra(data, _field_names(HostLogRecordWire)),
    )


def _resource_usage_from_dict(data: dict[str, Any]) -> HostResourceUsageWire:
    return HostResourceUsageWire(
        wall_ms=int(data["wall_ms"]),
        cpu_ms=_optional_int(data.get("cpu_ms")),
        peak_rss_bytes=_optional_int(data.get("peak_rss_bytes")),
        spawned_processes=int(data.get("spawned_processes", 0)),
        network_requests=int(data.get("network_requests", 0)),
        extra=_extra(data, _field_names(HostResourceUsageWire)),
    )


def _side_effect_from_dict(data: dict[str, Any]) -> HostSideEffectIntentWire:
    return HostSideEffectIntentWire(
        type=str(data["type"]),
        data=_mapping(data.get("data") or {}),
        extra=_extra(data, _field_names(HostSideEffectIntentWire)),
    )


def _check_schema(data: Mapping[str, Any]) -> None:
    schema = int(data["schema_version"])
    if schema != PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"host IPC wire schema mismatch: got {schema}, "
            f"expected {PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION}"
        )


def _extra(data: Mapping[str, Any], known: set[str]) -> Mapping[str, Any]:
    return {str(key): value for key, value in data.items() if str(key) not in known}


def _field_names(cls: type[Any]) -> set[str]:
    names = {item.name for item in fields(cls) if item.name != "extra"}
    return names


def _str_tuple(values: Any) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return {str(key): item for key, item in dict(value).items()}


__all__ = [
    "HOST_CAP_IPC_V1",
    "HOST_CAP_LLM_INVOKE",
    "HOST_CAP_LLM_METADATA",
    "HOST_CAP_MANIFEST_V1",
    "HOST_CAP_RESOURCE_POLICY_DIAGNOSTICS",
    "HOST_CAP_VCS_QUERY",
    "HOST_CAP_WORKSPACE_METADATA",
    "HOST_CAP_WORKSPACE_RESOLVE_REF",
    "HOST_CAP_WORKFLOW_STEP",
    "HOST_CAP_XPROMPT_CATALOG",
    "HOST_ERROR_CODES",
    "HOST_OPERATION_FAMILIES",
    "PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION",
    "FakeInProcessHostTransport",
    "HostActorWire",
    "HostDeadlineWire",
    "HostEnvironmentPolicyWire",
    "HostEnvironmentRequirementWire",
    "HostErrorWire",
    "HostFallbackWire",
    "HostLogRecordWire",
    "HostManifestWire",
    "HostNetworkPolicyWire",
    "HostOperationSelectorWire",
    "HostProcessPolicyWire",
    "HostRequestEnvelopeWire",
    "HostResourceUsageWire",
    "HostResponseEnvelopeWire",
    "HostSideEffectIntentWire",
    "HostWorkspaceIdentityWire",
    "host_request_from_dict",
    "host_response_from_dict",
    "host_wire_to_json_dict",
]
