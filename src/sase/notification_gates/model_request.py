"""Request and resource models for notification gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notification_gates.model_options import (
    GateGroup,
    GateOption,
    normalize_gate_structure,
    normalize_primary_branch,
)
from sase.notification_gates.model_validation import (
    GATE_REQUEST_SCHEMA_VERSION,
    GateError,
    json_object,
    reject_unknown_fields,
    validate_identifier,
    validate_relative_path,
)


@dataclass(frozen=True)
class _GateOperation:
    """A non-terminal operation supported by a local gate surface."""

    id: str
    kind: str
    target: str

    @classmethod
    def from_mapping(cls, value: object, index: int) -> _GateOperation:
        field = f"operations[{index}]"
        data = json_object(value, field)
        reject_unknown_fields(data, {"id", "kind", "target"}, field)
        operation_id = validate_identifier(data.get("id"), f"{field}.id")
        kind = data.get("kind")
        if kind != "edit_file":
            raise GateError(
                "invalid_operation",
                f"{field}.kind",
                "only the edit_file operation is supported",
            )
        target = validate_relative_path(data.get("target"), f"{field}.target")
        return cls(id=operation_id, kind=kind, target=target)

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "target": self.target}


@dataclass(frozen=True)
class GateResource:
    """A file copied or generated inside a gate bundle."""

    path: str
    role: str
    executable: bool = False
    content: str | None = None
    source: Path | None = None

    @classmethod
    def from_mapping(cls, value: object, index: int) -> GateResource:
        field = f"resources[{index}]"
        data = json_object(value, field)
        reject_unknown_fields(
            data,
            {"path", "role", "executable", "content", "source"},
            field,
        )
        path = validate_relative_path(data.get("path"), f"{field}.path")
        role = data.get("role", "attachment")
        if role not in {"attachment", "command", "editable", "preview"}:
            raise GateError(
                "invalid_resource",
                f"{field}.role",
                "resource role must be attachment, command, editable, or preview",
            )
        content = data.get("content")
        source_value = data.get("source")
        if (content is None) == (source_value is None):
            raise GateError(
                "invalid_resource",
                field,
                "resource must provide exactly one of content or source",
            )
        if content is not None and not isinstance(content, str):
            raise GateError(
                "invalid_resource", f"{field}.content", "content must be a string"
            )
        if source_value is not None and (
            not isinstance(source_value, str) or not source_value
        ):
            raise GateError(
                "invalid_resource", f"{field}.source", "source must be a path"
            )
        executable = data.get("executable", role == "command")
        if not isinstance(executable, bool):
            raise GateError(
                "invalid_resource",
                f"{field}.executable",
                "executable must be a boolean",
            )
        if executable and role != "command":
            raise GateError(
                "invalid_resource",
                f"{field}.executable",
                "only command resources may be executable",
            )
        return cls(
            path=path,
            role=role,
            executable=executable,
            content=content,
            source=Path(source_value).expanduser()
            if source_value is not None
            else None,
        )

    def envelope_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "role": self.role,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class _GateAuto:
    """Common automatic-resolution request interpreted by the kind adapter."""

    enabled: bool = False
    argument: str | None = None

    @classmethod
    def from_value(cls, value: object) -> _GateAuto:
        if value is None:
            return cls()
        if isinstance(value, bool):
            return cls(enabled=value)
        data = json_object(value, "auto")
        reject_unknown_fields(data, {"enabled", "argument"}, "auto")
        enabled = data.get("enabled", False)
        argument = data.get("argument")
        if not isinstance(enabled, bool):
            raise GateError(
                "invalid_auto", "auto.enabled", "auto.enabled must be a boolean"
            )
        if argument is not None and not isinstance(argument, str):
            raise GateError(
                "invalid_auto", "auto.argument", "auto.argument must be a string"
            )
        return cls(enabled=enabled, argument=argument)

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "argument": self.argument}


@dataclass(frozen=True)
class GateSpec:
    """Validated input to the gate creation service."""

    schema_version: int
    kind: str
    request_id: str | None
    producer: dict[str, Any]
    continuation_mode: str
    gate_timeout_seconds: float | None
    payload: dict[str, Any]
    presentation: dict[str, Any]
    query: str
    options: tuple[GateOption, ...]
    groups: tuple[GateGroup, ...]
    branches: tuple[tuple[str, ...], ...]
    primary_branch: tuple[str, ...]
    operations: tuple[_GateOperation, ...]
    resources: tuple[GateResource, ...]
    auto: _GateAuto

    @classmethod
    def from_mapping(cls, value: object) -> GateSpec:
        data = json_object(value, "request")
        schema_version = data.get("schema_version")
        if (
            type(schema_version) is not int
            or schema_version != GATE_REQUEST_SCHEMA_VERSION
        ):
            raise GateError(
                "unsupported_schema",
                "schema_version",
                "schema_version must be 3; expected a v3 gate request with "
                "query, options, primary_branch, and optional groups "
                "(choices/extras are unsupported)",
            )
        reject_unknown_fields(
            data,
            {
                "schema_version",
                "kind",
                "request_id",
                "producer",
                "continuation_mode",
                "gate_timeout_seconds",
                "payload",
                "presentation",
                "notification",
                "query",
                "options",
                "groups",
                "primary_branch",
                "operations",
                "resources",
                "assets",
                "auto",
            },
            "request",
        )
        kind = validate_identifier(data.get("kind"), "kind")
        raw_request_id = data.get("request_id")
        request_id = (
            None
            if raw_request_id is None
            else validate_identifier(raw_request_id, "request_id")
        )
        continuation = data.get("continuation_mode", "none")
        if not isinstance(continuation, str) or not continuation.strip():
            raise GateError(
                "invalid_request",
                "continuation_mode",
                "continuation_mode must be a non-empty string",
            )
        timeout = data.get("gate_timeout_seconds")
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise GateError(
                    "invalid_timeout",
                    "gate_timeout_seconds",
                    "gate_timeout_seconds must be a positive number",
                )
            timeout = float(timeout)
            if timeout <= 0:
                raise GateError(
                    "invalid_timeout",
                    "gate_timeout_seconds",
                    "gate_timeout_seconds must be a positive number",
                )
        from sase.notification_gates.registry import adapter_for_kind

        adapter = adapter_for_kind(kind)
        query, options, groups, branches = normalize_gate_structure(
            data.get("query"),
            data.get("options"),
            data.get("groups", []),
            default_feedback=adapter.default_feedback,
        )
        primary_branch = normalize_primary_branch(data.get("primary_branch"), branches)
        raw_operations = data.get("operations", [])
        if not isinstance(raw_operations, list):
            raise GateError(
                "invalid_request", "operations", "operations must be an array"
            )
        operations = tuple(
            _GateOperation.from_mapping(operation, index)
            for index, operation in enumerate(raw_operations)
        )
        raw_resources = data.get("resources", data.get("assets", []))
        if not isinstance(raw_resources, list):
            raise GateError(
                "invalid_request", "resources", "resources must be an array"
            )
        resources = tuple(
            GateResource.from_mapping(resource, index)
            for index, resource in enumerate(raw_resources)
        )
        if "resources" in data and "assets" in data:
            raise GateError(
                "invalid_request",
                "resources",
                "use resources or assets, not both",
            )
        if "presentation" in data and "notification" in data:
            raise GateError(
                "invalid_request",
                "presentation",
                "use presentation or notification, not both",
            )
        return cls(
            schema_version=GATE_REQUEST_SCHEMA_VERSION,
            kind=kind,
            request_id=request_id,
            producer=json_object(data.get("producer", {}), "producer"),
            continuation_mode=continuation.strip(),
            gate_timeout_seconds=timeout,
            payload=json_object(data.get("payload", {}), "payload"),
            presentation=json_object(
                data.get("presentation", data.get("notification", {})),
                "presentation",
            ),
            query=query,
            options=options,
            groups=groups,
            branches=branches,
            primary_branch=primary_branch,
            operations=operations,
            resources=resources,
            auto=_GateAuto.from_value(data.get("auto")),
        )
