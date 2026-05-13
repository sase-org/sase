"""Tests for waiting metadata enrichment."""

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import AgentMetaWire, WaitingMarkerWire
from tests._enrich_agent_helpers import local_time_from_iso, make_agent


def test_wait_duration_from_waiting_json(tmp_path: Path) -> None:
    """wait_duration is read from waiting.json when present."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_duration": 600.0}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.wait_duration == 600.0


def test_waiting_json_flips_starting_to_waiting(tmp_path: Path) -> None:
    """waiting.json marker overrides a pre-run STARTING row."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "waiting.json").write_text(json.dumps({"waiting_for": ["dep_agent"]}))

    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.waiting_for == ["dep_agent"]


def test_run_started_at_promotes_starting_to_running(tmp_path: Path) -> None:
    """run_started_at is the display-status promotion point."""
    timestamp = "2026-04-27T15:05:00Z"
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "run_started_at": timestamp})
    )

    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"
    assert agent.run_start_time == local_time_from_iso(timestamp)


def test_wait_completed_at_promotes_starting_to_running(tmp_path: Path) -> None:
    """Completed waits are displayed as RUNNING before run_started_at is written."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "wait_completed_at": "2026-04-27T15:04:59Z"})
    )

    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"
    assert agent.run_start_time is None


def test_wait_duration_from_agent_meta_fallback(tmp_path: Path) -> None:
    """wait_duration falls back to agent_meta.json when waiting.json absent."""
    meta = {"pid": 1234, "wait_duration": 300.0}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_duration == 300.0


def test_wait_duration_waiting_json_takes_precedence(tmp_path: Path) -> None:
    """waiting.json wait_duration takes precedence over agent_meta.json."""
    meta = {"pid": 1234, "wait_duration": 300.0}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_duration": 600.0}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_duration == 600.0


def test_wait_duration_none_when_absent(tmp_path: Path) -> None:
    """wait_duration stays None when not in any source."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_duration is None


def test_waiting_json_with_agents_and_duration(tmp_path: Path) -> None:
    """Mixed case: waiting_for agents + wait_duration both populated."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": ["dep_agent"], "wait_duration": 300.0}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.waiting_for == ["dep_agent"]
    assert agent.wait_duration == 300.0


def test_duration_only_waiting_json_sets_waiting_status(tmp_path: Path) -> None:
    """Duration-only waiting.json (empty waiting_for) sets WAITING status."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_duration": 120.0}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.waiting_for == []
    assert agent.wait_duration == 120.0


def test_wait_until_from_waiting_json(tmp_path: Path) -> None:
    """wait_until is read from waiting.json when present."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.wait_until == "2026-04-11T14:30:00"


def test_wait_until_from_agent_meta_fallback(tmp_path: Path) -> None:
    """wait_until falls back to agent_meta.json when waiting.json absent."""
    meta = {"pid": 1234, "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_until == "2026-04-11T14:30:00"


def test_wait_until_waiting_json_takes_precedence(tmp_path: Path) -> None:
    """waiting.json wait_until takes precedence over agent_meta.json."""
    meta = {"pid": 1234, "wait_until": "2026-04-11T12:00:00"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_until == "2026-04-11T14:30:00"


def test_wait_until_none_when_absent(tmp_path: Path) -> None:
    """wait_until stays None when not in any source."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_until is None


def test_wait_until_with_agents(tmp_path: Path) -> None:
    """Mixed case: waiting_for agents + wait_until both populated."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": ["dep_agent"], "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.waiting_for == ["dep_agent"]
    assert agent.wait_until == "2026-04-11T14:30:00"


def test_waiting_marker_wire_flips_starting_to_waiting() -> None:
    """Snapshot enrichment mirrors STARTING -> WAITING marker handling."""
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(),
        WaitingMarkerWire(waiting_for=["dep_agent"]),
        None,
    )
    assert agent.status == "WAITING"
    assert agent.waiting_for == ["dep_agent"]


def test_run_started_at_wire_promotes_starting_to_running() -> None:
    """Snapshot metadata promotes STARTING rows when run_started_at exists."""
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(run_started_at="2026-04-27T15:05:00Z"),
        None,
        None,
    )
    assert agent.status == "RUNNING"
    assert agent.run_start_time is not None


def test_wait_completed_at_wire_promotes_starting_to_running() -> None:
    """Snapshot metadata mirrors completed-wait status promotion."""
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(wait_completed_at="2026-04-27T15:04:59Z"),
        None,
        None,
    )
    assert agent.status == "RUNNING"
    assert agent.run_start_time is None
