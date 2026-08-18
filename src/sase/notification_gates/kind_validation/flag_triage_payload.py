"""Structured payload parsing for FlagTriage gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, cast

from sase.notification_gates.models import GateError
from sase.task_type_gate_presentation import (
    TaskTypeGateDisplay,
    parse_task_type_gate_display,
)

if TYPE_CHECKING:
    from sase.bead.model import FlagRecord

_FLAG_TRIAGE_REQUIRED_PAYLOAD_FIELDS = frozenset(
    {
        "bead_id",
        "project",
        "title",
        "created_at",
        "size",
        "refs",
        "flag",
        "due_state",
        "due_as_of",
        "release",
        "definition",
        "task_type",
        "task_type_fields",
    }
)
_FLAG_TRIAGE_OPTIONAL_PAYLOAD_FIELDS = frozenset({"task_type_display"})
_FLAG_TRIAGE_FLAG_FIELDS = frozenset(
    {"key", "kind", "remove_by_date", "remove_by_release"}
)
_FLAG_TRIAGE_DEFINITION_FIELDS = frozenset({"kind", "description"})
_FLAG_TRIAGE_DUE_STATES = frozenset({"live", "soon", "due"})
_FLAG_TRIAGE_KINDS = frozenset({"", "beta", "sunset"})


@dataclass(frozen=True)
class FlagTriagePayload:
    """The validated, structurally typed view of a flag triage gate payload."""

    bead_id: str
    project: str
    title: str
    created_at: str
    size: str | None
    refs: tuple[str, ...]
    flag: FlagRecord
    kind: str
    due_state: str
    due_as_of: str
    release: str
    definition: Mapping[str, str] | None
    task_type: str = ""
    task_type_fields: Mapping[str, str] = dataclass_field(default_factory=dict)
    task_type_display: TaskTypeGateDisplay | None = None


def parse_flag_triage_payload(payload: Mapping[str, Any]) -> FlagTriagePayload:
    """Validate *payload* against the structured FlagTriage presentation contract."""
    from sase.bead.model import PhaseSize
    from sase.core.paths import is_valid_sase_project_name

    payload_fields = set(payload)
    allowed_fields = (
        _FLAG_TRIAGE_REQUIRED_PAYLOAD_FIELDS | _FLAG_TRIAGE_OPTIONAL_PAYLOAD_FIELDS
    )
    if not _FLAG_TRIAGE_REQUIRED_PAYLOAD_FIELDS <= payload_fields <= allowed_fields:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload",
            "flag triage payload does not match the structured presentation contract",
        )
    for field in ("bead_id", "title", "due_as_of", "release"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_flag_triage_payload",
                f"payload.{field}",
                f"flag triage payload requires {field}",
            )
    project = payload.get("project")
    if not isinstance(project, str) or not is_valid_sase_project_name(project):
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.project",
            "flag triage payload requires a canonical SASE project key",
        )
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.created_at",
            "flag triage payload created_at must be a string",
        )
    size = payload.get("size")
    if size is not None and (
        not isinstance(size, str) or size not in {item.value for item in PhaseSize}
    ):
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.size",
            "flag triage payload size must be null or a valid task size",
        )
    refs = payload.get("refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.refs",
            "flag triage payload refs must be a string list",
        )
    due_state = payload.get("due_state")
    if due_state not in _FLAG_TRIAGE_DUE_STATES:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.due_state",
            "flag triage payload due_state must be live, soon, or due",
        )
    record, kind = _parse_flag_block(payload.get("flag"))
    try:
        record.validate()
    except ValueError as exc:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.flag",
            str(exc),
        ) from exc
    definition = _parse_definition(payload.get("definition"))
    task_type, task_type_fields = _parse_flag_task_type(payload)
    task_type_display = _parse_flag_task_type_display(payload, task_type)
    return FlagTriagePayload(
        bead_id=cast(str, payload["bead_id"]),
        project=project,
        title=cast(str, payload["title"]),
        created_at=created_at,
        size=cast("str | None", size),
        refs=tuple(cast(list[str], refs)),
        flag=record,
        kind=kind,
        due_state=cast(str, due_state),
        due_as_of=cast(str, payload["due_as_of"]),
        release=cast(str, payload["release"]),
        definition=definition,
        task_type=task_type,
        task_type_fields=task_type_fields,
        task_type_display=task_type_display,
    )


def _parse_flag_block(value: object) -> tuple[FlagRecord, str]:
    from sase.bead.flag_codec import flag_from_dict

    if not isinstance(value, Mapping) or set(value) != _FLAG_TRIAGE_FLAG_FIELDS:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.flag",
            "flag triage payload requires key, kind, and both thresholds",
        )
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in _FLAG_TRIAGE_KINDS:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.flag.kind",
            "flag triage payload kind must be empty, beta, or sunset",
        )
    record = flag_from_dict(dict(value))
    if record is None:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.flag",
            "flag triage payload requires a flag record",
        )
    return record, kind


def _parse_flag_task_type(
    payload: Mapping[str, Any],
) -> tuple[str, Mapping[str, str]]:
    task_type = payload.get("task_type", "")
    if not isinstance(task_type, str):
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.task_type",
            "flag triage payload task_type must be a string",
        )
    raw_fields = payload.get("task_type_fields", {})
    if not isinstance(raw_fields, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_fields.items()
    ):
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.task_type_fields",
            "flag triage payload task_type_fields must be a string-to-string mapping",
        )
    if raw_fields and not task_type:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.task_type_fields",
            "flag triage payload task_type_fields requires task_type",
        )
    return task_type, dict(cast("Mapping[str, str]", raw_fields))


def _parse_flag_task_type_display(
    payload: Mapping[str, Any], task_type: str
) -> TaskTypeGateDisplay | None:
    if "task_type_display" not in payload:
        return None
    if not task_type:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.task_type_display",
            "flag triage payload task_type_display requires task_type",
        )
    try:
        return parse_task_type_gate_display(payload["task_type_display"])
    except ValueError as exc:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.task_type_display",
            str(exc),
        ) from exc


def _parse_definition(value: object) -> Mapping[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _FLAG_TRIAGE_DEFINITION_FIELDS:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.definition",
            "flag triage payload definition must be null or {kind, description}",
        )
    kind = value.get("kind")
    description = value.get("description")
    if not isinstance(kind, str) or not kind or not isinstance(description, str):
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.definition",
            "flag triage payload definition fields must be strings",
        )
    return {"kind": kind, "description": description}


__all__ = ["FlagTriagePayload", "parse_flag_triage_payload"]
