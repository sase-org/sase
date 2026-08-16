"""Structured payload parsing for FlagTriage gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.model import FlagRecord

_FLAG_TRIAGE_PAYLOAD_FIELDS = frozenset(
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
    }
)
_FLAG_TRIAGE_DEFINITION_FIELDS = frozenset({"kind", "description"})
_FLAG_TRIAGE_DUE_STATES = frozenset({"live", "soon", "due"})


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
    due_state: str
    due_as_of: str
    release: str
    definition: Mapping[str, str] | None


def parse_flag_triage_payload(payload: Mapping[str, Any]) -> FlagTriagePayload:
    """Validate *payload* against the structured FlagTriage presentation contract."""
    from sase.bead.flag_codec import flag_from_dict
    from sase.bead.model import PhaseSize
    from sase.core.paths import is_valid_sase_project_name

    if set(payload) != _FLAG_TRIAGE_PAYLOAD_FIELDS:
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
    record = flag_from_dict(payload.get("flag"))
    if record is None:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.flag",
            "flag triage payload requires a flag record",
        )
    try:
        record.validate()
    except ValueError as exc:
        raise GateError(
            "invalid_flag_triage_payload",
            "payload.flag",
            str(exc),
        ) from exc
    definition = _parse_definition(payload.get("definition"))
    return FlagTriagePayload(
        bead_id=cast(str, payload["bead_id"]),
        project=project,
        title=cast(str, payload["title"]),
        created_at=created_at,
        size=cast("str | None", size),
        refs=tuple(cast(list[str], refs)),
        flag=record,
        due_state=cast(str, due_state),
        due_as_of=cast(str, payload["due_as_of"]),
        release=cast(str, payload["release"]),
        definition=definition,
    )


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
