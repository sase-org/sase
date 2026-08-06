"""Structured payload parsing for TaskTriage gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
        "plus_one_evidence",
        "close_history",
    }
)


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
    plus_one_evidence: tuple[TaskPlusOneEvidence, ...]
    close_history: tuple[CloseRecord, ...]


def parse_task_triage_payload(payload: Mapping[str, Any]) -> TaskTriagePayload:
    """Validate *payload* against the structured presentation contract."""
    from sase.bead.model import PhaseSize
    from sase.core.paths import is_valid_sase_project_name

    if set(payload) != _TASK_TRIAGE_PAYLOAD_FIELDS:
        raise GateError(
            "invalid_task_triage_payload",
            "payload",
            "task triage payload does not match the structured presentation contract",
        )
    for field in ("bead_id", "title"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.{field}",
                f"task triage payload requires {field}",
            )
    project = payload.get("project")
    if not isinstance(project, str) or not is_valid_sase_project_name(project):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.project",
            "task triage payload requires a canonical SASE project key",
        )
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.created_at",
            "task triage payload created_at must be a string",
        )
    size = payload.get("size")
    if size is not None and (
        not isinstance(size, str) or size not in {item.value for item in PhaseSize}
    ):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.size",
            "task triage payload size must be null or a valid task size",
        )
    refs = payload.get("refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.refs",
            "task triage payload refs must be a string list",
        )
    evidence = _parse_plus_one_evidence(payload.get("plus_one_evidence"))
    count = payload.get("plus_one_count")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(evidence):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.plus_one_count",
            "task triage +1 count must equal its evidence entries",
        )
    close_history = _parse_close_history(payload.get("close_history"))
    return TaskTriagePayload(
        bead_id=cast(str, payload["bead_id"]),
        project=project,
        title=cast(str, payload["title"]),
        created_at=created_at,
        size=cast(str | None, size),
        refs=tuple(cast(list[str], refs)),
        plus_one_count=count,
        plus_one_evidence=evidence,
        close_history=close_history,
    )


def _parse_plus_one_evidence(
    raw_evidence: object,
) -> tuple[TaskPlusOneEvidence, ...]:
    from sase.bead.model import TaskPlusOneEvidence

    if not isinstance(raw_evidence, list):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.plus_one_evidence",
            "task triage +1 evidence must be a list",
        )
    evidence: list[TaskPlusOneEvidence] = []
    reporters: set[str] = set()
    for index, raw_item in enumerate(raw_evidence):
        if not isinstance(raw_item, Mapping) or set(raw_item) != {
            "timestamp",
            "reporter",
            "note",
            "refs",
        }:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}",
                "task triage +1 evidence entry is malformed",
            )
        item_refs = raw_item.get("refs")
        if not isinstance(item_refs, list) or any(
            not isinstance(ref, str) for ref in item_refs
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}.refs",
                "task triage +1 evidence refs must be a string list",
            )
        if any(
            not isinstance(raw_item.get(field), str)
            for field in ("timestamp", "reporter", "note")
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}",
                "task triage +1 evidence text fields must be strings",
            )
        item = TaskPlusOneEvidence(
            timestamp=cast(str, raw_item["timestamp"]),
            reporter=cast(str, raw_item["reporter"]),
            note=cast(str, raw_item["note"]),
            refs=tuple(item_refs),
        )
        try:
            item.validate()
        except ValueError as exc:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}",
                str(exc),
            ) from exc
        if item.reporter in reporters:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}.reporter",
                "task triage +1 evidence reporters must be unique",
            )
        reporters.add(item.reporter)
        evidence.append(item)
    return tuple(evidence)


def _parse_close_history(raw_close_history: object) -> tuple[CloseRecord, ...]:
    from sase.bead.model import CloseRecord, ReopenCause, Resolution

    if not isinstance(raw_close_history, list):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.close_history",
            "task triage close history must be a list",
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
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                "task triage close history entry is malformed",
            )
        raw_resolution = raw_record.get("resolution")
        if raw_resolution is not None and raw_resolution not in resolution_values:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}.resolution",
                "task triage close history resolution is invalid",
            )
        raw_reopened_via = raw_record.get("reopened_via")
        if raw_reopened_via not in reopen_cause_values:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}.reopened_via",
                "task triage close history reopened_via is invalid",
            )
        raw_close_reason = raw_record.get("close_reason")
        raw_reopened_by = raw_record.get("reopened_by")
        if (raw_close_reason is not None and not isinstance(raw_close_reason, str)) or (
            raw_reopened_by is not None and not isinstance(raw_reopened_by, str)
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                "task triage close history text fields must be strings or null",
            )
        if any(
            not isinstance(raw_record.get(field), str)
            for field in ("closed_at", "reopened_at")
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                "task triage close history timestamps must be strings",
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
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                str(exc),
            ) from exc
        close_history.append(record)
    return tuple(close_history)
