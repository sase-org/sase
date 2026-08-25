"""Shared task-type detail projection for CLI and generated memory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._models import TaskTypeRecord

TASK_TYPE_DETAIL_SCHEMA_VERSION = 1
TASK_TYPE_FIELD_VALIDATOR_KEYS: tuple[str, ...] = (
    "pattern",
    "max_length",
    "values",
    "minimum",
    "maximum",
)
DEFAULT_TASK_TYPE_FIELD_ROLES: tuple[str, ...] = ("data", "template")


@dataclass(frozen=True)
class TaskTypeFieldValidatorDetail:
    """One supported validator declared for a task-type field."""

    name: str
    value: Any


@dataclass(frozen=True)
class TaskTypeFieldDetail:
    """Projected detail for one task-type field."""

    name: str
    label: str
    type: str
    required: bool
    roles: tuple[str, ...]
    help: str
    validators: tuple[TaskTypeFieldValidatorDetail, ...]


@dataclass(frozen=True)
class _TaskTypeProvenanceDetail:
    """Projected origin metadata for one task type."""

    label: str
    source: str
    package: str
    version: str


@dataclass(frozen=True)
class _TaskTypeTriageDetail:
    """Projected task-triage policy."""

    min_plus_ones: int


@dataclass(frozen=True)
class TaskTypeDetail:
    """Complete user-facing detail for one task-type record."""

    schema_version: int
    task_type: str
    label: str
    summary: str
    when_to_use: str
    create_refusal: str | None
    glyph: str
    accent_color: str
    agent_creatable: bool
    fields: tuple[TaskTypeFieldDetail, ...]
    body_template: str
    triage: _TaskTypeTriageDetail
    provenance: _TaskTypeProvenanceDetail
    digest: str


def task_type_detail(record: TaskTypeRecord) -> TaskTypeDetail:
    """Return the shared detail projection for *record*."""

    spec = record.spec
    create_refusal = str(spec.get("create_refusal") or "").strip() or None
    return TaskTypeDetail(
        schema_version=TASK_TYPE_DETAIL_SCHEMA_VERSION,
        task_type=record.task_type,
        label=str(spec.get("label") or record.task_type),
        summary=str(spec.get("summary") or ""),
        when_to_use=str(spec.get("when_to_use") or ""),
        create_refusal=create_refusal,
        glyph=record.resolved_glyph or "•",
        accent_color=record.resolved_accent_color,
        agent_creatable=record.agent_creatable,
        fields=tuple(_field_detail(field) for field in _spec_fields(spec)),
        body_template=_body_template(spec),
        triage=_TaskTypeTriageDetail(min_plus_ones=record.min_plus_ones),
        provenance=_TaskTypeProvenanceDetail(
            label=record.provenance.label,
            source=record.provenance.source,
            package=record.provenance.package,
            version=record.provenance.version,
        ),
        digest=record.digest,
    )


def task_type_detail_to_json(detail: TaskTypeDetail) -> dict[str, Any]:
    """Return the stable ``sase bead task-type show --json`` payload."""

    payload: dict[str, Any] = {
        "accent_color": detail.accent_color,
        "agent_creatable": detail.agent_creatable,
        "body_template": detail.body_template,
        "digest": detail.digest,
        "fields": [_field_json(field) for field in detail.fields],
        "glyph": detail.glyph,
        "label": detail.label,
        "provenance": {
            "label": detail.provenance.label,
            "package": detail.provenance.package,
            "source": detail.provenance.source,
            "version": detail.provenance.version,
        },
        "schema_version": detail.schema_version,
        "summary": detail.summary,
        "task_type": detail.task_type,
        "triage": {"min_plus_ones": detail.triage.min_plus_ones},
        "when_to_use": detail.when_to_use,
    }
    if detail.create_refusal:
        payload["create_refusal"] = detail.create_refusal
    return payload


def task_type_field_heading(field: TaskTypeFieldDetail) -> str:
    """Return the human CLI heading line for *field*."""

    required = "required" if field.required else "optional"
    return f"{field.name}  {field.type}  {required}  {', '.join(field.roles)}"


def task_type_field_validator_lines(field: TaskTypeFieldDetail) -> tuple[str, ...]:
    """Return human-readable validator lines for *field*."""

    lines: list[str] = []
    for validator in field.validators:
        value = validator.value
        if validator.name == "pattern" and isinstance(value, str) and value:
            lines.append(f"pattern: {value}")
        elif validator.name == "max_length" and isinstance(value, int):
            lines.append(f"max_length: {value}")
        elif validator.name == "values" and isinstance(value, list) and value:
            lines.append("values: " + ", ".join(str(item) for item in value))
        elif validator.name == "minimum" and isinstance(value, int):
            lines.append(f"minimum: {value}")
        elif validator.name == "maximum" and isinstance(value, int):
            lines.append(f"maximum: {value}")
    return tuple(lines)


def _spec_fields(spec: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = spec.get("fields")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _field_detail(field: Mapping[str, Any]) -> TaskTypeFieldDetail:
    return TaskTypeFieldDetail(
        name=str(field.get("name") or ""),
        label=str(field.get("label") or ""),
        type=str(field.get("type") or "string"),
        required=bool(field.get("required")),
        roles=_field_roles(field),
        help=str(field.get("help") or ""),
        validators=tuple(
            TaskTypeFieldValidatorDetail(name=key, value=field[key])
            for key in TASK_TYPE_FIELD_VALIDATOR_KEYS
            if key in field
        ),
    )


def _field_roles(field: Mapping[str, Any]) -> tuple[str, ...]:
    raw = field.get("role")
    if isinstance(raw, list):
        roles = tuple(str(item) for item in raw)
        if roles:
            return roles
    return DEFAULT_TASK_TYPE_FIELD_ROLES


def _field_json(field: TaskTypeFieldDetail) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "help": field.help,
        "label": field.label,
        "name": field.name,
        "required": field.required,
        "role": list(field.roles),
        "type": field.type,
    }
    for validator in field.validators:
        payload[validator.name] = validator.value
    return payload


def _body_template(spec: Mapping[str, Any]) -> str:
    raw = spec.get("body_template")
    return raw if isinstance(raw, str) else ""


__all__ = [
    "DEFAULT_TASK_TYPE_FIELD_ROLES",
    "TASK_TYPE_DETAIL_SCHEMA_VERSION",
    "TASK_TYPE_FIELD_VALIDATOR_KEYS",
    "TaskTypeDetail",
    "TaskTypeFieldDetail",
    "TaskTypeFieldValidatorDetail",
    "task_type_detail",
    "task_type_detail_to_json",
    "task_type_field_heading",
    "task_type_field_validator_lines",
]
