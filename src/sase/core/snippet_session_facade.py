"""Validated Python facade for the Rust snippet session engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

SNIPPET_SESSION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class _SnippetStop:
    """One active tabstop in document-offset space."""

    offset: int
    session: int


@dataclass(frozen=True, slots=True)
class _SnippetSpan:
    """Document span for one live snippet expansion."""

    id: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SnippetSessionState:
    """Typed Python view of the Rust snippet session state."""

    schema_version: int = SNIPPET_SESSION_SCHEMA_VERSION
    stops: tuple[_SnippetStop, ...] = ()
    index: int = 0
    sessions: tuple[_SnippetSpan, ...] = ()
    next_session_id: int = 0

    @property
    def is_active(self) -> bool:
        return bool(self.stops)

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stops": [
                {"offset": stop.offset, "session": stop.session} for stop in self.stops
            ],
            "index": self.index,
            "sessions": [
                {"id": span.id, "start": span.start, "end": span.end}
                for span in self.sessions
            ],
            "next_session_id": self.next_session_id,
        }


@dataclass(frozen=True, slots=True)
class _SnippetExpansionPlan:
    """Expansion text and tabstop offsets planned by the Rust engine."""

    text: str
    tabstop_offsets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _SnippetSessionTransition:
    """Typed result from one snippet session event."""

    state: SnippetSessionState
    cursor_offset: int | None = None
    text: str | None = None
    tabstop_offsets: tuple[int, ...] = ()


def empty_snippet_session() -> SnippetSessionState:
    return SnippetSessionState()


def plan_snippet_expansion(
    template: str,
    line_indent: str,
    *,
    indent_continuation_lines: bool,
    state: SnippetSessionState | None = None,
) -> _SnippetExpansionPlan:
    result = _apply_snippet_session_event(
        state or empty_snippet_session(),
        {
            "kind": "plan",
            "template": template,
            "line_indent": line_indent,
            "indent_continuation_lines": indent_continuation_lines,
        },
    )
    if result.text is None:
        raise ValueError("snippet session plan event returned no text")
    return _SnippetExpansionPlan(
        text=result.text,
        tabstop_offsets=result.tabstop_offsets,
    )


def expand_snippet_session(
    state: SnippetSessionState,
    *,
    range_start: int,
    range_end: int,
    tabstop_offsets: Sequence[int],
) -> _SnippetSessionTransition:
    return _apply_snippet_session_event(
        state,
        {
            "kind": "expand",
            "range_start": range_start,
            "range_end": range_end,
            "tabstop_offsets": list(tabstop_offsets),
        },
    )


def advance_snippet_session(
    state: SnippetSessionState,
) -> _SnippetSessionTransition:
    return _apply_snippet_session_event(state, {"kind": "advance"})


def retreat_snippet_session(
    state: SnippetSessionState,
) -> _SnippetSessionTransition:
    return _apply_snippet_session_event(state, {"kind": "retreat"})


def apply_snippet_session_edit(
    state: SnippetSessionState,
    *,
    edit_start: int,
    edit_end: int,
    inserted_len: int,
) -> _SnippetSessionTransition:
    return _apply_snippet_session_event(
        state,
        {
            "kind": "apply_edit",
            "edit_start": edit_start,
            "edit_end": edit_end,
            "inserted_len": inserted_len,
        },
    )


def clear_snippet_session(
    state: SnippetSessionState,
) -> _SnippetSessionTransition:
    return _apply_snippet_session_event(state, {"kind": "clear"})


def _apply_snippet_session_event(
    state: SnippetSessionState,
    event: Mapping[str, object],
) -> _SnippetSessionTransition:
    binding = require_rust_binding("apply_snippet_session_event")
    payload: Any = binding(state.to_wire(), dict(event))
    return _transition_from_wire(payload)


def _transition_from_wire(payload: Any) -> _SnippetSessionTransition:
    if not isinstance(payload, Mapping):
        raise TypeError(
            "apply_snippet_session_event returned a non-mapping top-level payload"
        )

    state = _state_from_wire(payload.get("state"), "state")
    cursor_offset = _optional_nonnegative_int(
        payload.get("cursor_offset"),
        "cursor_offset",
    )
    text = _optional_string(payload.get("text"), "text")
    tabstop_offsets = _nonnegative_int_tuple(
        payload.get("tabstop_offsets"),
        "tabstop_offsets",
    )
    return _SnippetSessionTransition(
        state=state,
        cursor_offset=cursor_offset,
        text=text,
        tabstop_offsets=tabstop_offsets,
    )


def _state_from_wire(value: Any, field: str) -> SnippetSessionState:
    if not isinstance(value, Mapping):
        raise TypeError(f"snippet session field {field!r} must be a mapping")

    schema_version = _nonnegative_int(value.get("schema_version"), "schema_version")
    if schema_version != SNIPPET_SESSION_SCHEMA_VERSION:
        raise ValueError(
            f"snippet session state has unsupported schema_version {schema_version!r}"
        )

    stops = _stops_from_wire(value.get("stops"))
    index = _nonnegative_int(value.get("index"), "index")
    sessions = _sessions_from_wire(value.get("sessions"))
    next_session_id = _nonnegative_int(
        value.get("next_session_id"),
        "next_session_id",
    )

    if not stops:
        if index != 0:
            raise ValueError("inactive snippet session state must use index 0")
        if sessions:
            raise ValueError("inactive snippet session state must not carry sessions")
    elif index >= len(stops):
        raise ValueError(
            "snippet session state index points past the stop list: "
            f"{index} >= {len(stops)}"
        )

    session_ids = {span.id for span in sessions}
    for stop in stops:
        if stop.session not in session_ids:
            raise ValueError(
                "snippet session state stop references missing session "
                f"{stop.session!r}"
            )

    if session_ids and next_session_id <= max(session_ids):
        raise ValueError(
            "snippet session state next_session_id must exceed existing session ids"
        )

    return SnippetSessionState(
        schema_version=schema_version,
        stops=stops,
        index=index,
        sessions=sessions,
        next_session_id=next_session_id,
    )


def _stops_from_wire(value: Any) -> tuple[_SnippetStop, ...]:
    items = _sequence(value, "stops")
    stops: list[_SnippetStop] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise TypeError("snippet session field 'stops' contains a non-mapping item")
        stops.append(
            _SnippetStop(
                offset=_nonnegative_int(item.get("offset"), "stops.offset"),
                session=_nonnegative_int(item.get("session"), "stops.session"),
            )
        )
    return tuple(stops)


def _sessions_from_wire(value: Any) -> tuple[_SnippetSpan, ...]:
    items = _sequence(value, "sessions")
    sessions: list[_SnippetSpan] = []
    seen_ids: set[int] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise TypeError(
                "snippet session field 'sessions' contains a non-mapping item"
            )
        session_id = _nonnegative_int(item.get("id"), "sessions.id")
        if session_id in seen_ids:
            raise ValueError(
                f"snippet session state contains duplicate session id {session_id!r}"
            )
        seen_ids.add(session_id)
        start = _nonnegative_int(item.get("start"), "sessions.start")
        end = _nonnegative_int(item.get("end"), "sessions.end")
        if end < start:
            raise ValueError(
                "snippet session state contains a session span whose end "
                f"{end} precedes start {start}"
            )
        sessions.append(_SnippetSpan(id=session_id, start=start, end=end))
    return tuple(sessions)


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"snippet session field {field!r} must be a sequence")
    return value


def _nonnegative_int_tuple(value: Any, field: str) -> tuple[int, ...]:
    return tuple(
        _nonnegative_int(item, f"{field}[{index}]")
        for index, item in enumerate(_sequence(value, field))
    )


def _optional_nonnegative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, field)


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"snippet session field {field!r} must be a string or None")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int:
        raise TypeError(f"snippet session field {field!r} must be an integer")
    if value < 0:
        raise ValueError(f"snippet session field {field!r} must be non-negative")
    return value


__all__ = [
    "SNIPPET_SESSION_SCHEMA_VERSION",
    "SnippetSessionState",
    "advance_snippet_session",
    "apply_snippet_session_edit",
    "clear_snippet_session",
    "empty_snippet_session",
    "expand_snippet_session",
    "plan_snippet_expansion",
    "retreat_snippet_session",
]
