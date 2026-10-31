"""Scan-wire conversion for compact ``wait_turn_bindings``."""

from __future__ import annotations

from sase.core.agent_scan_wire_conversion import (
    _agent_meta_from_dict,
    _waiting_marker_from_dict,
)
from sase.core.agent_scan_wire_markers_wait_turn import (
    WaitTurnBindingWire,
    format_wait_turn_binding,
    wait_turn_bindings_from_payload,
)


def test_format_wait_turn_binding() -> None:
    assert format_wait_turn_binding("16h", "16h--gate") == "16h → turn 16h--gate"


def test_meta_derives_wait_turn_bindings_from_artifacts() -> None:
    meta = _agent_meta_from_dict(
        {
            "wait_for_artifacts": [
                {
                    "requested": "16h",
                    "name": "16h--gate",
                    "target": "turn",
                    "turn_name": "16h--gate",
                },
                {"name": "planner", "target": "session", "turn_name": "planner--plan"},
                {"requested": "missing", "target": "turn"},
            ]
        }
    )
    assert meta.wait_turn_bindings == [
        WaitTurnBindingWire(name="16h", turn_name="16h--gate")
    ]


def test_meta_skips_history_only_fork_sources() -> None:
    meta = _agent_meta_from_dict(
        {
            "wait_for_fork_sources": [
                {
                    "requested": "live",
                    "target": "turn",
                    "turn_name": "live--gate",
                },
                {
                    "requested": "hist",
                    "target": "turn",
                    "turn_name": "hist--gate",
                    "history_only": True,
                },
            ]
        }
    )
    assert meta.wait_turn_bindings == [
        WaitTurnBindingWire(name="live", turn_name="live--gate")
    ]


def test_explicit_wait_turn_bindings_win_over_records() -> None:
    payload = {
        "wait_turn_bindings": [{"name": "16h", "turn_name": "16h--gate"}],
        "wait_for_artifacts": [
            {"requested": "other", "target": "turn", "turn_name": "other--gate"}
        ],
    }
    assert wait_turn_bindings_from_payload(payload) == [
        WaitTurnBindingWire(name="16h", turn_name="16h--gate")
    ]
    meta = _agent_meta_from_dict(payload)
    assert meta.wait_turn_bindings == [
        WaitTurnBindingWire(name="16h", turn_name="16h--gate")
    ]


def test_malformed_wait_turn_bindings_are_dropped() -> None:
    meta = _agent_meta_from_dict(
        {
            "wait_turn_bindings": [
                {"name": "16h"},
                {"turn_name": "16h--gate"},
                42,
                {"name": "  ", "turn_name": "x"},
                {"name": "ok", "turn_name": "ok--gate"},
            ]
        }
    )
    assert meta.wait_turn_bindings == [
        WaitTurnBindingWire(name="ok", turn_name="ok--gate")
    ]
    for value in ("16h", 42, None, {}):
        assert (
            _agent_meta_from_dict({"wait_turn_bindings": value}).wait_turn_bindings
            == []
        )


def test_waiting_marker_derives_wait_turn_bindings() -> None:
    marker = _waiting_marker_from_dict(
        {
            "waiting_for": ["16h"],
            "wait_for_artifacts": [
                {
                    "requested": "16h",
                    "target": "turn",
                    "turn_name": "16h--gate",
                }
            ],
        }
    )
    assert marker.wait_turn_bindings == [
        WaitTurnBindingWire(name="16h", turn_name="16h--gate")
    ]
