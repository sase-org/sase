"""Tests for wait-queue metadata enrichment (queue weight, priority, capacity)."""

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import AgentMetaWire, WaitingMarkerWire
from tests._enrich_agent_helpers import make_agent


def test_explicit_zero_queue_weight_from_agent_meta_is_valid(tmp_path: Path) -> None:
    """A host-authored explicit zero (e.g. the epic-launch monitor) is a
    valid, non-invalid weight -- unlike an implicit zero, which stays
    invalid/fail-closed like any other non-positive weight."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_weight": 0, "queue_weight_explicit": True})
    )

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.queue_weight == 0.0
    assert agent.queue_weight_explicit is True
    assert agent.queue_weight_invalid is False


def test_implicit_zero_queue_weight_from_agent_meta_is_invalid(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_weight": 0})
    )

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.queue_weight is None
    assert agent.queue_weight_explicit is False
    assert agent.queue_weight_invalid is True


def test_explicit_zero_queue_weight_from_waiting_json_is_valid(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "queue_weight": 0.0,
                "queue_weight_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        )
    )

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.queue_weight == 0.0
    assert agent.queue_weight_explicit is True
    assert agent.queue_weight_invalid is False


def test_runner_slot_fields_from_waiting_json(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "wait_runners": 0,
                "wait_runners_explicit": True,
                "wait_priority": 3,
                "wait_priority_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:00Z",
                "held_by": "agent:hold-a",
                "hold_expires_at": 1_700_000_300.0,
            }
        )
    )

    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_runners == 0
    assert agent.wait_runners_explicit is True
    assert agent.wait_priority == 3
    assert agent.wait_priority_explicit is True
    assert agent.slot_requested_at == "2026-07-12T12:00:00Z"
    assert agent.held_by == "agent:hold-a"
    assert agent.hold_expires_at == 1_700_000_300.0


def test_queue_weight_fields_match_filesystem_and_wire(
    tmp_path: Path,
) -> None:
    metadata = {
        "pid": 1234,
        "queue_weight": 0.25,
        "queue_weight_explicit": True,
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(metadata))
    filesystem_agent = make_agent(status="STARTING")
    wire_agent = make_agent(status="STARTING")

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(**metadata),
        None,
        None,
    )

    assert filesystem_agent.queue_weight == 0.25
    assert filesystem_agent.queue_weight_explicit is True
    assert filesystem_agent.queue_weight_invalid is False
    assert wire_agent.queue_weight == 0.25
    assert wire_agent.queue_weight_explicit is True
    assert wire_agent.queue_weight_invalid is False


def test_absent_legacy_queue_weight_stays_unknown(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    filesystem_agent = make_agent(status="STARTING")
    wire_agent = make_agent(status="STARTING")

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(wire_agent, AgentMetaWire(pid=1234), None, None)

    assert filesystem_agent.queue_weight is None
    assert filesystem_agent.queue_weight_explicit is False
    assert wire_agent.queue_weight is None
    assert wire_agent.queue_weight_explicit is False


def test_waiting_queue_weight_overrides_meta_in_filesystem_and_wire(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_weight": 1.0})
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "queue_weight": 0.5,
                "queue_weight_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        )
    )
    filesystem_agent = make_agent(status="STARTING")
    wire_agent = make_agent(status="STARTING")

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(pid=1234, queue_weight=1.0),
        WaitingMarkerWire(
            queue_weight=0.5,
            queue_weight_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
        ),
        None,
    )

    assert filesystem_agent.queue_weight == 0.5
    assert filesystem_agent.queue_weight_explicit is True
    assert wire_agent.queue_weight == 0.5
    assert wire_agent.queue_weight_explicit is True


def test_invalid_filesystem_queue_weight_is_marked(tmp_path: Path) -> None:
    metadata = {
        "pid": 1234,
        "queue_weight": "heavy",
        "queue_weight_explicit": True,
        "queue_weight_error": "bad weight",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(metadata))
    agent = make_agent(status="STARTING")

    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.queue_weight is None
    assert agent.queue_weight_explicit is True
    assert agent.queue_weight_invalid is True
    assert agent.queue_weight_error == "bad weight"


def test_wait_priority_falls_back_to_agent_meta_in_filesystem_and_wire(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "wait_priority": 6})
    )
    filesystem_agent = make_agent(status="STARTING")
    wire_agent = make_agent(status="STARTING")

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(pid=1234, wait_priority=6),
        None,
        None,
    )

    assert filesystem_agent.wait_priority == 6
    assert filesystem_agent.wait_priority_explicit is True
    assert wire_agent.wait_priority == 6
    assert wire_agent.wait_priority_explicit is True


def test_runner_slot_fields_from_waiting_marker_wire() -> None:
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(wait_priority=6),
        WaitingMarkerWire(
            wait_runners=9,
            wait_runners_explicit=False,
            wait_priority=4,
            wait_priority_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            held_by="agent:hold-a",
            hold_expires_at=1_700_000_300.0,
        ),
        None,
    )

    assert agent.wait_runners == 9
    assert agent.wait_runners_explicit is False
    assert agent.wait_priority == 4
    assert agent.wait_priority_explicit is True
    assert agent.slot_requested_at == "2026-07-12T12:00:00Z"
    assert agent.held_by == "agent:hold-a"
    assert agent.hold_expires_at == 1_700_000_300.0


def test_legacy_wait_priority_marker_uses_default_value_heuristic() -> None:
    explicit_agent = make_agent(status="STARTING")
    default_agent = make_agent(status="STARTING")

    enrich_agent_from_meta_wire(
        explicit_agent,
        AgentMetaWire(),
        WaitingMarkerWire(wait_priority=20),
        None,
    )
    enrich_agent_from_meta_wire(
        default_agent,
        AgentMetaWire(),
        WaitingMarkerWire(wait_priority=10),
        None,
    )

    assert explicit_agent.wait_priority_explicit is True
    assert default_agent.wait_priority_explicit is False


def test_queue_capacity_metadata_marks_waited_in_filesystem_and_wire(
    tmp_path: Path,
) -> None:
    """Canonical queue_capacity metadata is a wait directive on both paths."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_capacity": 2, "queue_capacity_explicit": True})
    )
    filesystem_agent = make_agent(status="DONE")
    wire_agent = make_agent(status="DONE")

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(pid=1234, queue_capacity=2, queue_capacity_explicit=True),
        None,
        None,
    )

    assert filesystem_agent.wait_start_time is not None
    assert filesystem_agent.wait_start_time == filesystem_agent.start_time
    assert wire_agent.wait_start_time is not None
    assert wire_agent.wait_start_time == wire_agent.start_time


def test_canonical_queue_capacity_from_waiting_marker_wire() -> None:
    """Schema 9 waiting markers carry capacity only as queue_capacity."""
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(),
        WaitingMarkerWire(queue_capacity=3, queue_capacity_explicit=True),
        None,
    )

    assert agent.wait_runners == 3
    assert agent.wait_runners_explicit is True
