"""Shared record and field accessors for agent list entry projections."""

from __future__ import annotations

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    AgentSessionTurnWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)


def record_meta(record: AgentArtifactRecordWire | None) -> AgentMetaWire | None:
    return record.agent_meta if record is not None else None


def record_waiting(record: AgentArtifactRecordWire | None) -> WaitingMarkerWire | None:
    return record.waiting if record is not None else None


def record_pending_question(
    record: AgentArtifactRecordWire | None,
) -> PendingQuestionMarkerWire | None:
    return record.pending_question if record is not None else None


def field_text(obj: object | None, attr: str) -> str | None:
    value = getattr(obj, attr, None)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def first_field_text(*values: str | None) -> str | None:
    return next((value for value in values if value), None)


def field_int(obj: object | None, attr: str) -> int | None:
    value = getattr(obj, attr, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def monitor_str(source: AgentMetaWire | DoneMarkerWire | None, attr: str) -> str | None:
    """Read a shared ``agent_session_turn`` string field, only for a monitor turn."""
    return field_text(monitor_turn(source), attr)


def monitor_turn(
    source: AgentMetaWire | DoneMarkerWire | None,
) -> AgentSessionTurnWire | None:
    """Return the ``agent_session_turn`` shell, only for a monitor turn."""
    shell = source.agent_session_turn if source is not None else None
    return shell if shell is not None and shell.kind == "monitor" else None
