"""Typed models for durable command-backed notification gates."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from sase.notification_gates.query import GateQueryError, parse_gate_query

GATE_REQUEST_SCHEMA_VERSION = 2
GATE_RESPONSE_SCHEMA_VERSION = 2
GATE_RESULT_SCHEMA_VERSION = 2

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OPTION_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_MAX_GATE_LABEL_LENGTH = 160
_MAX_GATE_ICON_CODEPOINTS = 32
_MAX_GATE_ICON_BYTES = 128

GateFeedbackMode = Literal["disabled", "optional", "required"]


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


def validate_option_identifier(value: object, target: str) -> str:
    """Return an identifier accepted by the option-query grammar."""
    if not isinstance(value, str) or not _OPTION_IDENTIFIER_RE.fullmatch(value):
        raise GateError(
            "invalid_identifier",
            target,
            f"{target} must match [a-z][a-z0-9_-]*",
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


def validate_icon(value: object, target: str) -> str | None:
    """Return one bounded display grapheme, or reject an invalid icon."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise GateError(
            "invalid_icon", target, f"{target} must be a single emoji or glyph"
        )
    if (
        len(value) > _MAX_GATE_ICON_CODEPOINTS
        or len(value.encode("utf-8")) > _MAX_GATE_ICON_BYTES
        or _grapheme_cluster_count(value) != 1
    ):
        raise GateError(
            "invalid_icon", target, f"{target} must be a single emoji or glyph"
        )
    return value


def _grapheme_cluster_count(value: str) -> int:
    """Count the bounded glyph forms accepted for gate icons.

    This deliberately covers combining marks, emoji modifiers, regional-indicator
    pairs, keycaps, tag sequences, and zero-width-joiner emoji without adding a
    Unicode-segmentation dependency to the gate service.
    """
    clusters = 0
    join_next = False
    regional_run = 0
    for character in value:
        codepoint = ord(character)
        if _is_disallowed_icon_control(character):
            return 2
        if clusters == 0:
            if codepoint == 0x200D or _is_grapheme_extend(character):
                return 2
            clusters = 1
            regional_run = 1 if _is_regional_indicator(codepoint) else 0
            continue
        if join_next:
            if codepoint == 0x200D:
                return 2
            join_next = False
            regional_run = 0
            continue
        if codepoint == 0x200D:
            join_next = True
            regional_run = 0
            continue
        if _is_grapheme_extend(character):
            continue
        if _is_regional_indicator(codepoint) and regional_run % 2 == 1:
            regional_run += 1
            continue
        clusters += 1
        regional_run = 1 if _is_regional_indicator(codepoint) else 0
    return clusters + int(join_next)


def _is_grapheme_extend(character: str) -> bool:
    codepoint = ord(character)
    return (
        unicodedata.combining(character) != 0
        or unicodedata.category(character) in {"Mc", "Me", "Mn"}
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0x1F3FB <= codepoint <= 0x1F3FF
        or 0xE0020 <= codepoint <= 0xE007F
    )


def _is_disallowed_icon_control(character: str) -> bool:
    codepoint = ord(character)
    return unicodedata.category(character).startswith("C") and not (
        codepoint == 0x200D or 0xE0020 <= codepoint <= 0xE007F
    )


def _is_regional_indicator(codepoint: int) -> bool:
    return 0x1F1E6 <= codepoint <= 0x1F1FF


def _validate_label(value: object, target: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError("invalid_request", target, f"{target} is required")
    normalized = value.strip()
    if len(normalized) > _MAX_GATE_LABEL_LENGTH:
        raise GateError(
            "invalid_request",
            target,
            f"{target} must be at most {_MAX_GATE_LABEL_LENGTH} characters",
        )
    return normalized


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
class GateOption:
    """One command-bearing control referenced exactly once by a gate query."""

    id: str
    label: str
    command: _GateCommand
    input_schema: dict[str, Any] = field(default_factory=dict)
    result_schema: dict[str, Any] = field(default_factory=dict)
    icon: str | None = None
    default_selected: bool = True
    feedback: GateFeedbackMode = "disabled"

    @classmethod
    def from_mapping(
        cls,
        value: object,
        index: int,
        *,
        default_feedback: GateFeedbackMode = "disabled",
    ) -> GateOption:
        target = f"options[{index}]"
        data = _json_object(value, target)
        _reject_unknown_fields(
            data,
            {
                "id",
                "label",
                "command",
                "input_schema",
                "result_schema",
                "icon",
                "default_selected",
                "feedback",
            },
            target,
        )
        option_id = validate_option_identifier(data.get("id"), f"{target}.id")
        label = _validate_label(data.get("label"), f"{target}.label")
        default_selected = data.get("default_selected", True)
        if not isinstance(default_selected, bool):
            raise GateError(
                "invalid_request",
                f"{target}.default_selected",
                "default_selected must be a boolean",
            )
        feedback = data.get("feedback", default_feedback)
        if feedback not in {"disabled", "optional", "required"}:
            raise GateError(
                "invalid_request",
                f"{target}.feedback",
                "feedback must be disabled, optional, or required",
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
            id=option_id,
            label=label,
            command=_GateCommand.from_value(data.get("command"), f"{target}.command"),
            input_schema=input_schema,
            result_schema=result_schema,
            icon=validate_icon(data.get("icon"), f"{target}.icon"),
            default_selected=default_selected,
            feedback=feedback,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command.to_dict(),
            "input_schema": self.input_schema,
            "result_schema": self.result_schema,
            "icon": self.icon,
            "default_selected": self.default_selected,
            "feedback": self.feedback,
        }


@dataclass(frozen=True)
class GateGroup:
    """Display metadata for one AND branch's submit control."""

    options: tuple[str, ...]
    label: str | None = None
    icon: str | None = None

    @classmethod
    def from_mapping(cls, value: object, index: int) -> GateGroup:
        target = f"groups[{index}]"
        data = _json_object(value, target)
        _reject_unknown_fields(data, {"options", "label", "icon"}, target)
        raw_options = data.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise GateError(
                "invalid_group",
                f"{target}.options",
                "group options must be a non-empty array of option ids",
            )
        options = tuple(
            validate_option_identifier(option_id, f"{target}.options[{option_index}]")
            for option_index, option_id in enumerate(raw_options)
        )
        if len(set(options)) != len(options):
            raise GateError(
                "invalid_group",
                f"{target}.options",
                "group option ids must be unique",
            )
        raw_label = data.get("label")
        label = (
            None if raw_label is None else _validate_label(raw_label, f"{target}.label")
        )
        return cls(
            options=options,
            label=label,
            icon=validate_icon(data.get("icon"), f"{target}.icon"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "options": list(self.options),
            "label": self.label,
            "icon": self.icon,
        }


def normalize_gate_structure(
    query_value: object,
    options_value: object,
    groups_value: object,
    *,
    default_feedback: GateFeedbackMode = "disabled",
) -> tuple[
    str, tuple[GateOption, ...], tuple[GateGroup, ...], tuple[tuple[str, ...], ...]
]:
    """Validate and normalize the query/options/groups cross-reference contract."""
    try:
        parsed = parse_gate_query(query_value)
    except GateQueryError as exc:
        raise GateError("invalid_query", "query", str(exc)) from exc

    if not isinstance(options_value, list) or not options_value:
        raise GateError(
            "invalid_request", "options", "at least one gate option is required"
        )
    options = tuple(
        GateOption.from_mapping(
            option,
            index,
            default_feedback=default_feedback,
        )
        for index, option in enumerate(options_value)
    )
    option_ids = [option.id for option in options]
    duplicates = sorted(
        option_id for option_id in set(option_ids) if option_ids.count(option_id) > 1
    )
    if duplicates:
        raise GateError(
            "duplicate_identifier",
            "options",
            f"duplicate option id(s): {', '.join(duplicates)}",
        )
    queried_ids = {option_id for branch in parsed.branches for option_id in branch}
    declared_ids = set(option_ids)
    unknown = sorted(queried_ids - declared_ids)
    missing = sorted(declared_ids - queried_ids)
    if unknown:
        raise GateError(
            "unknown_option",
            "query",
            f"query references undeclared option(s): {', '.join(unknown)}",
        )
    if missing:
        raise GateError(
            "unreferenced_option",
            "options",
            f"option(s) are not referenced by the query: {', '.join(missing)}",
        )

    if groups_value is None:
        groups_value = []
    if not isinstance(groups_value, list):
        raise GateError("invalid_request", "groups", "groups must be an array")
    configs = tuple(
        GateGroup.from_mapping(group, index) for index, group in enumerate(groups_value)
    )
    and_branches = tuple(branch for branch in parsed.branches if len(branch) > 1)
    branch_by_members = {frozenset(branch): branch for branch in and_branches}
    configs_by_members: dict[frozenset[str], GateGroup] = {}
    for index, config in enumerate(configs):
        members = frozenset(config.options)
        branch = branch_by_members.get(members)
        if branch is None:
            raise GateError(
                "invalid_group",
                f"groups[{index}].options",
                "configured group does not match an AND branch in the query",
            )
        if members in configs_by_members:
            raise GateError(
                "invalid_group",
                f"groups[{index}].options",
                "an AND branch may be configured only once",
            )
        configs_by_members[members] = config

    by_id = {option.id: option for option in options}
    groups: list[GateGroup] = []
    for branch in and_branches:
        group_config = configs_by_members.get(frozenset(branch))
        first = by_id[branch[0]]
        groups.append(
            GateGroup(
                options=branch,
                label=(
                    group_config.label
                    if group_config is not None and group_config.label is not None
                    else first.label
                ),
                icon=(
                    group_config.icon
                    if group_config is not None and group_config.icon is not None
                    else first.icon
                ),
            )
        )
    return parsed.query, options, tuple(groups), parsed.branches


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
    query: str
    options: tuple[GateOption, ...]
    groups: tuple[GateGroup, ...]
    branches: tuple[tuple[str, ...], ...]
    operations: tuple[_GateOperation, ...]
    resources: tuple[GateResource, ...]
    auto: _GateAuto

    @classmethod
    def from_mapping(cls, value: object) -> GateSpec:
        data = _json_object(value, "request")
        schema_version = data.get("schema_version")
        if (
            type(schema_version) is not int
            or schema_version != GATE_REQUEST_SCHEMA_VERSION
        ):
            raise GateError(
                "unsupported_schema",
                "schema_version",
                "schema_version must be 2; expected a v2 gate request with "
                "query, options, and optional groups (choices/extras are unsupported)",
            )
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
                "query",
                "options",
                "groups",
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
        query, options, groups, branches = normalize_gate_structure(
            data.get("query"),
            data.get("options"),
            data.get("groups", []),
            default_feedback="optional" if kind == "custom" else "disabled",
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
            schema_version=GATE_REQUEST_SCHEMA_VERSION,
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
            query=query,
            options=options,
            groups=groups,
            branches=branches,
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
    "GateCreationResult",
    "GateError",
    "GateExecutionResult",
    "GateFeedbackMode",
    "GateGroup",
    "GateOption",
    "GateResource",
    "GateSpec",
    "normalize_gate_structure",
    "validate_icon",
    "validate_identifier",
    "validate_option_identifier",
    "validate_relative_path",
]
