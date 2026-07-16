"""Typed models for durable command-backed notification gates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

GATE_REQUEST_SCHEMA_VERSION = 1
GATE_RESPONSE_SCHEMA_VERSION = 1
GATE_RESULT_SCHEMA_VERSION = 1

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class GateError(RuntimeError):
    """A deterministic gate validation, durability, or execution failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


def validate_identifier(value: object, target: str) -> str:
    """Return a safe identifier or raise :class:`GateError`."""
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise GateError(
            "invalid_identifier",
            target,
            f"{target} must contain only letters, digits, '.', '_', or '-'",
        )
    return value


def validate_relative_path(value: object, target: str) -> str:
    """Return a normalized safe POSIX path owned by a request bundle."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise GateError("invalid_path", target, f"{target} must be a relative path")
    if "\\" in value:
        raise GateError("invalid_path", target, f"{target} must use '/' separators")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise GateError(
            "invalid_path", target, f"{target} must stay within the request bundle"
        )
    return path.as_posix()


def _json_object(value: object, target: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GateError("invalid_request", target, f"{target} must be an object")
    return {str(key): item for key, item in value.items()}


def _string_list(value: object, target: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GateError(
            "invalid_request", target, f"{target} must be an array of strings"
        )
    return tuple(value)


@dataclass(frozen=True)
class _GateCommand:
    """A shell-free command descriptor."""

    argv: tuple[str, ...]

    @classmethod
    def from_value(cls, value: object, target: str) -> _GateCommand:
        if isinstance(value, list):
            argv = _string_list(value, target)
        else:
            data = _json_object(value, target)
            unknown = set(data) - {"argv"}
            if unknown:
                raise GateError(
                    "invalid_request",
                    target,
                    f"unsupported command field(s): {', '.join(sorted(unknown))}",
                )
            argv = _string_list(data.get("argv"), f"{target}.argv")
        if not argv or not argv[0]:
            raise GateError("invalid_command", target, "command argv must not be empty")
        validate_relative_path(argv[0], f"{target}.argv[0]")
        if any("\x00" in argument for argument in argv):
            raise GateError(
                "invalid_command", target, "command arguments cannot contain NUL"
            )
        return cls(argv=argv)

    def to_dict(self) -> dict[str, Any]:
        return {"argv": list(self.argv)}


@dataclass(frozen=True)
class GateChoice:
    """One terminal choice exposed by a gate."""

    id: str
    label: str
    command: _GateCommand
    input_schema: dict[str, Any] = field(default_factory=dict)
    result_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: object, index: int) -> GateChoice:
        target = f"choices[{index}]"
        data = _json_object(value, target)
        _reject_unknown_fields(
            data,
            {"id", "label", "command", "input_schema", "result_schema"},
            target,
        )
        choice_id = validate_identifier(data.get("id"), f"{target}.id")
        label = data.get("label")
        if not isinstance(label, str) or not label.strip():
            raise GateError(
                "invalid_request", f"{target}.label", "choice label is required"
            )
        input_schema = _json_object(
            data.get("input_schema", {}), f"{target}.input_schema"
        )
        result_schema = _json_object(
            data.get("result_schema", {}), f"{target}.result_schema"
        )
        _check_json_schema(input_schema, f"{target}.input_schema")
        _check_json_schema(result_schema, f"{target}.result_schema")
        return cls(
            id=choice_id,
            label=label.strip(),
            command=_GateCommand.from_value(data.get("command"), f"{target}.command"),
            input_schema=input_schema,
            result_schema=result_schema,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command.to_dict(),
            "input_schema": self.input_schema,
            "result_schema": self.result_schema,
        }


@dataclass(frozen=True)
class _GateOperation:
    """A non-terminal operation supported by a local gate surface."""

    id: str
    kind: str
    target: str

    @classmethod
    def from_mapping(cls, value: object, index: int) -> _GateOperation:
        field = f"operations[{index}]"
        data = _json_object(value, field)
        _reject_unknown_fields(data, {"id", "kind", "target"}, field)
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
        data = _json_object(value, field)
        _reject_unknown_fields(
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
        data = _json_object(value, "auto")
        _reject_unknown_fields(data, {"enabled", "argument"}, "auto")
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
    choices: tuple[GateChoice, ...]
    operations: tuple[_GateOperation, ...]
    resources: tuple[GateResource, ...]
    auto: _GateAuto

    @classmethod
    def from_mapping(cls, value: object) -> GateSpec:
        data = _json_object(value, "request")
        _reject_unknown_fields(
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
                "choices",
                "operations",
                "resources",
                "assets",
                "auto",
            },
            "request",
        )
        schema_version = data.get("schema_version")
        if (
            type(schema_version) is not int
            or schema_version != GATE_REQUEST_SCHEMA_VERSION
        ):
            raise GateError(
                "unsupported_schema",
                "schema_version",
                f"schema_version must be {GATE_REQUEST_SCHEMA_VERSION}",
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
        raw_choices = data.get("choices")
        if not isinstance(raw_choices, list) or not raw_choices:
            raise GateError(
                "invalid_request", "choices", "at least one terminal choice is required"
            )
        choices = tuple(
            GateChoice.from_mapping(choice, index)
            for index, choice in enumerate(raw_choices)
        )
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
            schema_version=schema_version,
            kind=kind,
            request_id=request_id,
            producer=_json_object(data.get("producer", {}), "producer"),
            continuation_mode=continuation.strip(),
            gate_timeout_seconds=timeout,
            payload=_json_object(data.get("payload", {}), "payload"),
            presentation=_json_object(
                data.get("presentation", data.get("notification", {})),
                "presentation",
            ),
            choices=choices,
            operations=operations,
            resources=resources,
            auto=_GateAuto.from_value(data.get("auto")),
        )


@dataclass(frozen=True)
class GateCreationResult:
    """Stable machine-readable result returned after durable creation."""

    schema_version: int
    notification_id: str | None
    request_id: str
    kind: str
    bundle_path: Path
    request_path: Path
    response_path: Path
    preview_path: Path | None
    continuation_mode: str
    auto_resolution: dict[str, Any]
    hashes: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "notification_id": self.notification_id,
            "request_id": self.request_id,
            "kind": self.kind,
            "bundle_path": str(self.bundle_path),
            "request_path": str(self.request_path),
            "response_path": str(self.response_path),
            "preview_path": (
                None if self.preview_path is None else str(self.preview_path)
            ),
            "continuation_mode": self.continuation_mode,
            "auto_resolution": self.auto_resolution,
            "hashes": self.hashes,
        }

    @classmethod
    def from_mapping(cls, value: object) -> GateCreationResult:
        data = _json_object(value, "creation result")
        preview_path = data.get("preview_path")
        notification_id = data.get("notification_id")
        if notification_id is not None and not isinstance(notification_id, str):
            raise GateError(
                "invalid_state", "notification_id", "notification_id must be a string"
            )
        if preview_path is not None and not isinstance(preview_path, str):
            raise GateError(
                "invalid_state", "preview_path", "preview_path must be a string"
            )
        return cls(
            schema_version=int(data["schema_version"]),
            notification_id=notification_id,
            request_id=str(data["request_id"]),
            kind=str(data["kind"]),
            bundle_path=Path(str(data["bundle_path"])),
            request_path=Path(str(data["request_path"])),
            response_path=Path(str(data["response_path"])),
            preview_path=None if preview_path is None else Path(preview_path),
            continuation_mode=str(data["continuation_mode"]),
            auto_resolution=_json_object(
                data.get("auto_resolution", {}), "auto_resolution"
            ),
            hashes=_json_object(data.get("hashes", {}), "hashes"),
        )


@dataclass(frozen=True)
class GateExecutionResult:
    """Result of resolving a terminal gate choice."""

    response: dict[str, Any]
    already_completed: bool = False


def _check_json_schema(schema: dict[str, Any], target: str) -> None:
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise GateError(
            "invalid_schema", target, f"invalid JSON schema: {exc}"
        ) from exc


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed: set[str], target: str
) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise GateError(
            "invalid_request",
            target,
            f"unsupported field(s): {', '.join(sorted(unknown))}",
        )


__all__ = [
    "GATE_REQUEST_SCHEMA_VERSION",
    "GATE_RESPONSE_SCHEMA_VERSION",
    "GATE_RESULT_SCHEMA_VERSION",
    "GateChoice",
    "GateCreationResult",
    "GateError",
    "GateExecutionResult",
    "GateResource",
    "GateSpec",
    "validate_identifier",
    "validate_relative_path",
]
