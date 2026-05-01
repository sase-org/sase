"""Tests for wait_duration enrichment from waiting.json and agent_meta.json."""

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_scan_wire import AgentMetaWire
from sase.core.time import get_timezone


def _make_agent(status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status=status,
        start_time=datetime(2026, 4, 10, 22, 0, 0),
    )


def test_wait_duration_from_waiting_json(tmp_path: Path) -> None:
    """wait_duration is read from waiting.json when present."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_duration": 600.0}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.wait_duration == 600.0


def test_wait_duration_from_agent_meta_fallback(tmp_path: Path) -> None:
    """wait_duration falls back to agent_meta.json when waiting.json absent."""
    meta = {"pid": 1234, "wait_duration": 300.0}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_duration == 300.0


def test_wait_duration_waiting_json_takes_precedence(tmp_path: Path) -> None:
    """waiting.json wait_duration takes precedence over agent_meta.json."""
    meta = {"pid": 1234, "wait_duration": 300.0}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_duration": 600.0}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_duration == 600.0


def test_wait_duration_none_when_absent(tmp_path: Path) -> None:
    """wait_duration stays None when not in any source."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_duration is None


def test_waiting_json_with_agents_and_duration(tmp_path: Path) -> None:
    """Mixed case: waiting_for agents + wait_duration both populated."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": ["dep_agent"], "wait_duration": 300.0}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = _make_agent()
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

    agent = _make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.waiting_for == []
    assert agent.wait_duration == 120.0


# --- wait_until tests ---


def test_wait_until_from_waiting_json(tmp_path: Path) -> None:
    """wait_until is read from waiting.json when present."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.wait_until == "2026-04-11T14:30:00"


def test_wait_until_from_agent_meta_fallback(tmp_path: Path) -> None:
    """wait_until falls back to agent_meta.json when waiting.json absent."""
    meta = {"pid": 1234, "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_until == "2026-04-11T14:30:00"


def test_wait_until_waiting_json_takes_precedence(tmp_path: Path) -> None:
    """waiting.json wait_until takes precedence over agent_meta.json."""
    meta = {"pid": 1234, "wait_until": "2026-04-11T12:00:00"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": [], "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_until == "2026-04-11T14:30:00"


def test_wait_until_none_when_absent(tmp_path: Path) -> None:
    """wait_until stays None when not in any source."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_until is None


def test_wait_until_with_agents(tmp_path: Path) -> None:
    """Mixed case: waiting_for agents + wait_until both populated."""
    meta = {"pid": 1234}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))
    waiting = {"waiting_for": ["dep_agent"], "wait_until": "2026-04-11T14:30:00"}
    (tmp_path / "waiting.json").write_text(json.dumps(waiting))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"
    assert agent.waiting_for == ["dep_agent"]
    assert agent.wait_until == "2026-04-11T14:30:00"


def test_epic_started_at_from_agent_meta(tmp_path: Path) -> None:
    """epic_started_at is parsed into agent.epic_time."""
    timestamp = "2026-04-27T15:05:00Z"
    meta = {"pid": 1234, "epic_started_at": timestamp}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    expected = (
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        .astimezone(get_timezone())
        .replace(tzinfo=None)
    )
    assert agent.epic_time == expected


def test_epic_started_at_from_agent_meta_wire() -> None:
    """wire metadata enrichment mirrors filesystem epic_started_at parsing."""
    timestamp = "2026-04-27T15:05:00Z"
    agent = _make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(epic_started_at=timestamp),
        None,
    )

    expected = (
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        .astimezone(get_timezone())
        .replace(tzinfo=None)
    )
    assert agent.epic_time == expected
