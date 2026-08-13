"""Tests for the validated Rust snippet session facade."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from sase.core import snippet_session_facade as facade


def test_snippet_session_facade_round_trips_through_real_binding() -> None:
    plan = facade.plan_snippet_expansion(
        "foo $1 bar $2 baz $3 buz",
        "",
        indent_continuation_lines=True,
    )
    assert plan.text == "foo  bar  baz  buz"
    assert plan.tabstop_offsets == (4, 9, 14, 18)

    result = facade.expand_snippet_session(
        facade.empty_snippet_session(),
        range_start=0,
        range_end=len(plan.text),
        tabstop_offsets=plan.tabstop_offsets,
    )
    assert result.cursor_offset == 4
    assert result.state.is_active

    result = facade.advance_snippet_session(result.state)
    assert result.cursor_offset == 9

    with pytest.raises(FrozenInstanceError):
        result.state.index = 0  # type: ignore[misc]


def test_snippet_session_facade_drives_nested_resume_through_real_binding() -> None:
    outer = facade.expand_snippet_session(
        facade.empty_snippet_session(),
        range_start=0,
        range_end=20,
        tabstop_offsets=(4, 9, 14, 18),
    )
    at_second = facade.advance_snippet_session(outer.state)
    inner = facade.expand_snippet_session(
        at_second.state,
        range_start=9,
        range_end=9,
        tabstop_offsets=(1, 3),
    )

    assert inner.cursor_offset == 10
    assert facade.advance_snippet_session(inner.state).cursor_offset == 12
    resumed = facade.advance_snippet_session(
        facade.advance_snippet_session(inner.state).state
    )
    assert resumed.cursor_offset == 14


def test_apply_snippet_session_event_forwards_typed_state_and_event(
    monkeypatch,
) -> None:
    calls: list[tuple[dict[str, object], dict[str, object]]] = []
    state = facade.SnippetSessionState(
        stops=(facade._SnippetStop(offset=2, session=0),),
        index=0,
        sessions=(facade._SnippetSpan(id=0, start=0, end=4),),
        next_session_id=1,
    )

    def binding(
        state_payload: dict[str, object],
        event_payload: dict[str, object],
    ) -> dict[str, object]:
        calls.append((state_payload, event_payload))
        return {
            "state": state_payload,
            "cursor_offset": 2,
            "text": None,
            "tabstop_offsets": [],
        }

    monkeypatch.setattr(
        facade,
        "require_rust_binding",
        lambda name: binding if name == "apply_snippet_session_event" else None,
    )

    result = facade._apply_snippet_session_event(state, {"kind": "advance"})

    assert calls == [(state.to_wire(), {"kind": "advance"})]
    assert result.cursor_offset == 2
    assert result.state == state


@pytest.mark.parametrize(
    ("payload", "exception", "match"),
    [
        ([], TypeError, "non-mapping top-level payload"),
        (
            {
                "state": [],
                "cursor_offset": None,
                "text": None,
                "tabstop_offsets": [],
            },
            TypeError,
            "'state' must be a mapping",
        ),
        (
            {
                "state": {
                    "schema_version": 2,
                    "stops": [],
                    "index": 0,
                    "sessions": [],
                    "next_session_id": 0,
                },
                "cursor_offset": None,
                "text": None,
                "tabstop_offsets": [],
            },
            ValueError,
            "unsupported schema_version",
        ),
        (
            {
                "state": {
                    "schema_version": 1,
                    "stops": [],
                    "index": 1,
                    "sessions": [],
                    "next_session_id": 0,
                },
                "cursor_offset": None,
                "text": None,
                "tabstop_offsets": [],
            },
            ValueError,
            "inactive snippet session state must use index 0",
        ),
        (
            {
                "state": {
                    "schema_version": 1,
                    "stops": [{"offset": 1, "session": 7}],
                    "index": 0,
                    "sessions": [{"id": 0, "start": 0, "end": 2}],
                    "next_session_id": 1,
                },
                "cursor_offset": None,
                "text": None,
                "tabstop_offsets": [],
            },
            ValueError,
            "stop references missing session 7",
        ),
        (
            {
                "state": {
                    "schema_version": 1,
                    "stops": [],
                    "index": 0,
                    "sessions": [],
                    "next_session_id": 0,
                },
                "cursor_offset": "1",
                "text": None,
                "tabstop_offsets": [],
            },
            TypeError,
            "'cursor_offset' must be an integer",
        ),
        (
            {
                "state": {
                    "schema_version": 1,
                    "stops": [],
                    "index": 0,
                    "sessions": [],
                    "next_session_id": 0,
                },
                "cursor_offset": None,
                "text": 1,
                "tabstop_offsets": [],
            },
            TypeError,
            "'text' must be a string or None",
        ),
        (
            {
                "state": {
                    "schema_version": 1,
                    "stops": [],
                    "index": 0,
                    "sessions": [],
                    "next_session_id": 0,
                },
                "cursor_offset": None,
                "text": None,
                "tabstop_offsets": ["1"],
            },
            TypeError,
            "'tabstop_offsets\\[0\\]' must be an integer",
        ),
    ],
)
def test_snippet_session_facade_rejects_malformed_payloads(
    monkeypatch,
    payload: object,
    exception: type[Exception],
    match: str,
) -> None:
    def binding(_state: object, _event: object) -> object:
        return payload

    monkeypatch.setattr(
        facade,
        "require_rust_binding",
        lambda _name: binding,
    )

    with pytest.raises(exception, match=match):
        facade.advance_snippet_session(facade.empty_snippet_session())


def test_plan_event_rejects_missing_text(monkeypatch) -> None:
    payload: dict[str, Any] = {
        "state": facade.empty_snippet_session().to_wire(),
        "cursor_offset": None,
        "text": None,
        "tabstop_offsets": [],
    }

    monkeypatch.setattr(
        facade,
        "require_rust_binding",
        lambda _name: lambda _state, _event: payload,
    )

    with pytest.raises(ValueError, match="plan event returned no text"):
        facade.plan_snippet_expansion(
            "x",
            "",
            indent_continuation_lines=False,
        )
