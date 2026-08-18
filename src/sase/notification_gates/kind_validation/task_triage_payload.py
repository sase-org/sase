"""Structured payload parsing for TaskTriage gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, cast

from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.model import CloseRecord, TaskPlusOneEvidence

_TASK_TRIAGE_PAYLOAD_FIELDS = frozenset(
    {
        "bead_id",
        "project",
        "title",
        "created_at",
        "size",
        "refs",
        "plus_one_count",
        "closed_at",
        "plus_one_evidence",
        "close_history",
        "task_type",
        "task_type_fields",
    }
)
_LEGACY_TASK_TRIAGE_PAYLOAD_FIELDS = _TASK_TRIAGE_PAYLOAD_FIELDS - {"closed_at"}


@dataclass(frozen=True)
class TaskTriagePayload:
    """The validated, structurally typed view of a task triage gate payload."""

    bead_id: str
    project: str
    title: str
    created_at: str
    size: str | None
    refs: tuple[str, ...]
    plus_one_count: int
    closed_at: str | None
    plus_one_evidence: tuple[TaskPlusOneEvidence, ...]
    close_history: tuple[CloseRecord, ...]
    task_type: str = ""
    task_type_fields: Mapping[str, str] = dataclass_field(default_factory=dict)


def parse_task_triage_payload(payload: Mapping[str, Any]) -> TaskTriagePayload:
    """Validate *payload* against the structured presentation contract."""
    return parse_task_bead_payload(payload)


def parse_task_bead_payload(
    payload: Mapping[str, Any],
    *,
    code: str = "invalid_task_triage_payload",
    label: str = "task triage",
    extra_fields: frozenset[str] = frozenset(),
) -> TaskTriagePayload:
    """Validate the task-bead fields every bead gate payload carries.

    The BeadSnooze gate presents the same task the TaskTriage gate does, so
    it validates the same fields through this parser and adds only its own
    *extra_fields* on top; *code* and *label* keep its errors named after the
    kind that actually failed.
    """
    from sase.bead.model import PhaseSize
    from sase.core.paths import is_valid_sase_project_name

    payload_fields = set(payload)
    expected_fields = _TASK_TRIAGE_PAYLOAD_FIELDS | extra_fields
    legacy_fields = _LEGACY_TASK_TRIAGE_PAYLOAD_FIELDS | extra_fields
    if payload_fields not in (expected_fields, legacy_fields):
        raise GateError(
            code,
            "payload",
            f"{label} payload does not match the structured presentation contract",
        )
    for field in ("bead_id", "title"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                code,
                f"payload.{field}",
                f"{label} payload requires {field}",
            )
    project = payload.get("project")
    if not isinstance(project, str) or not is_valid_sase_project_name(project):
        raise GateError(
            code,
            "payload.project",
            f"{label} payload requires a canonical SASE project key",
        )
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise GateError(
            code,
            "payload.created_at",
            f"{label} payload created_at must be a string",
        )
    size = payload.get("size")
    if size is not None and (
        not isinstance(size, str) or size not in {item.value for item in PhaseSize}
    ):
        raise GateError(
            code,
            "payload.size",
            f"{label} payload size must be null or a valid task size",
        )
    refs = payload.get("refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise GateError(
            code,
            "payload.refs",
            f"{label} payload refs must be a string list",
        )
    evidence = _parse_plus_one_evidence(payload.get("plus_one_evidence"), code, label)
    count = payload.get("plus_one_count")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(evidence):
        raise GateError(
            code,
            "payload.plus_one_count",
            f"{label} +1 count must equal its evidence entries",
        )
    close_history = _parse_close_history(payload.get("close_history"), code, label)
    closed_at = payload.get("closed_at")
    if closed_at is not None and not isinstance(closed_at, str):
        raise GateError(
            code,
            "payload.closed_at",
            f"{label} payload closed_at must be null or a string",
        )
    task_type, task_type_fields = _parse_task_type(payload, code, label)
    return TaskTriagePayload(
        bead_id=cast(str, payload["bead_id"]),
        project=project,
        title=cast(str, payload["title"]),
        created_at=created_at,
        size=cast(str | None, size),
        refs=tuple(cast(list[str], refs)),
        plus_one_count=count,
        closed_at=closed_at,
        plus_one_evidence=evidence,
        close_history=close_history,
        task_type=task_type,
        task_type_fields=task_type_fields,
    )


def _parse_task_type(
    payload: Mapping[str, Any], code: str, label: str
) -> tuple[str, Mapping[str, str]]:
    task_type = payload.get("task_type", "")
    if not isinstance(task_type, str):
        raise GateError(
            code,
            "payload.task_type",
            f"{label} payload task_type must be a string",
        )
    raw_fields = payload.get("task_type_fields", {})
    if not isinstance(raw_fields, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_fields.items()
    ):
        raise GateError(
            code,
            "payload.task_type_fields",
            f"{label} payload task_type_fields must be a string-to-string mapping",
        )
    if raw_fields and not task_type:
        raise GateError(
            code,
            "payload.task_type_fields",
            f"{label} payload task_type_fields requires task_type",
        )
    return task_type, dict(cast("Mapping[str, str]", raw_fields))


def _parse_plus_one_evidence(
    raw_evidence: object, code: str, label: str
) -> tuple[TaskPlusOneEvidence, ...]:
    from sase.bead.model import TaskPlusOneEvidence

    if not isinstance(raw_evidence, list):
        raise GateError(
            code,
            "payload.plus_one_evidence",
            f"{label} +1 evidence must be a list",
        )
    evidence: list[TaskPlusOneEvidence] = []
    reporters: set[str] = set()
    for index, raw_item in enumerate(raw_evidence):
        item_fields = set(raw_item) if isinstance(raw_item, Mapping) else set()
        allowed_fields = (
            {"timestamp", "reporter", "note", "refs"},
            {"timestamp", "reporter", "note", "refs", "observed_since"},
        )
        if not isinstance(raw_item, Mapping) or item_fields not in allowed_fields:
            raise GateError(
                code,
                f"payload.plus_one_evidence.{index}",
                f"{label} +1 evidence entry is malformed",
            )
        item_refs = raw_item.get("refs")
        if not isinstance(item_refs, list) or any(
            not isinstance(ref, str) for ref in item_refs
        ):
            raise GateError(
                code,
                f"payload.plus_one_evidence.{index}.refs",
                f"{label} +1 evidence refs must be a string list",
            )
        if any(
            not isinstance(raw_item.get(field), str)
            for field in ("timestamp", "reporter", "note")
        ):
            raise GateError(
                code,
                f"payload.plus_one_evidence.{index}",
                f"{label} +1 evidence text fields must be strings",
            )
        observed_since = raw_item.get("observed_since")
        if observed_since is not None and not isinstance(observed_since, str):
            raise GateError(
                code,
                f"payload.plus_one_evidence.{index}.observed_since",
                f"{label} +1 evidence observed_since must be a string",
            )
        item = TaskPlusOneEvidence(
            timestamp=cast(str, raw_item["timestamp"]),
            reporter=cast(str, raw_item["reporter"]),
            note=cast(str, raw_item["note"]),
            refs=tuple(item_refs),
            observed_since=cast(str | None, observed_since),
        )
        try:
            item.validate()
        except ValueError as exc:
            raise GateError(
                code,
                f"payload.plus_one_evidence.{index}",
                str(exc),
            ) from exc
        if item.reporter in reporters:
            raise GateError(
                code,
                f"payload.plus_one_evidence.{index}.reporter",
                f"{label} +1 evidence reporters must be unique",
            )
        reporters.add(item.reporter)
        evidence.append(item)
    return tuple(evidence)


def _parse_close_history(
    raw_close_history: object, code: str, label: str
) -> tuple[CloseRecord, ...]:
    from sase.bead.model import CloseRecord, ReopenCause, Resolution

    if not isinstance(raw_close_history, list):
        raise GateError(
            code,
            "payload.close_history",
            f"{label} close history must be a list",
        )
    resolution_values = {item.value for item in Resolution}
    reopen_cause_values = {item.value for item in ReopenCause}
    close_history: list[CloseRecord] = []
    for index, raw_record in enumerate(raw_close_history):
        if not isinstance(raw_record, Mapping) or set(raw_record) != {
            "closed_at",
            "close_reason",
            "resolution",
            "reopened_at",
            "reopened_via",
            "reopened_by",
        }:
            raise GateError(
                code,
                f"payload.close_history.{index}",
                f"{label} close history entry is malformed",
            )
        raw_resolution = raw_record.get("resolution")
        if raw_resolution is not None and raw_resolution not in resolution_values:
            raise GateError(
                code,
                f"payload.close_history.{index}.resolution",
                f"{label} close history resolution is invalid",
            )
        raw_reopened_via = raw_record.get("reopened_via")
        if raw_reopened_via not in reopen_cause_values:
            raise GateError(
                code,
                f"payload.close_history.{index}.reopened_via",
                f"{label} close history reopened_via is invalid",
            )
        raw_close_reason = raw_record.get("close_reason")
        raw_reopened_by = raw_record.get("reopened_by")
        if (raw_close_reason is not None and not isinstance(raw_close_reason, str)) or (
            raw_reopened_by is not None and not isinstance(raw_reopened_by, str)
        ):
            raise GateError(
                code,
                f"payload.close_history.{index}",
                f"{label} close history text fields must be strings or null",
            )
        if any(
            not isinstance(raw_record.get(field), str)
            for field in ("closed_at", "reopened_at")
        ):
            raise GateError(
                code,
                f"payload.close_history.{index}",
                f"{label} close history timestamps must be strings",
            )
        record = CloseRecord(
            closed_at=cast(str, raw_record["closed_at"]),
            reopened_at=cast(str, raw_record["reopened_at"]),
            reopened_via=ReopenCause(raw_reopened_via),
            close_reason=cast(str | None, raw_close_reason),
            resolution=Resolution(raw_resolution) if raw_resolution else None,
            reopened_by=cast(str | None, raw_reopened_by),
        )
        try:
            record.validate()
        except ValueError as exc:
            raise GateError(
                code,
                f"payload.close_history.{index}",
                str(exc),
            ) from exc
        close_history.append(record)
    return tuple(close_history)
