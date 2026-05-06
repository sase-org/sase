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


def test_auto_approve_plan_action_from_agent_meta(tmp_path: Path) -> None:
    """Plan-specific auto approval is preserved and renders as approved."""
    meta = {"pid": 1234, "auto_approve_plan_action": "epic"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.auto_approve_plan_action == "epic"
    assert agent.approve is True


def test_auto_approve_plan_action_from_agent_meta_wire() -> None:
    """Snapshot metadata mirrors filesystem auto-approval enrichment."""
    agent = _make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(auto_approve_plan_action="epic"),
        None,
    )

    assert agent.auto_approve_plan_action == "epic"
    assert agent.approve is True


def test_tag_from_agent_meta(tmp_path: Path) -> None:
    """A valid tag in agent_meta.json seeds the agent tag."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "tag": "sase-26"})
    )

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.tag == "sase-26"


def test_invalid_tag_from_agent_meta_is_ignored(tmp_path: Path) -> None:
    """Malformed stored directive metadata is not surfaced as a UI tag."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "tag": "has space"})
    )

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.tag is None


def test_tag_from_agent_meta_wire() -> None:
    """Snapshot metadata mirrors filesystem tag enrichment."""
    agent = _make_agent()

    enrich_agent_from_meta_wire(agent, AgentMetaWire(tag="sase-26"), None)

    assert agent.tag == "sase-26"


def test_auto_epic_plan_before_submission_stays_running(tmp_path: Path) -> None:
    """An auto-epic plan writer is still active before it submits a plan."""
    meta = {"pid": 1234, "plan": True, "auto_approve_plan_action": "epic"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"
    assert agent.auto_approve_plan_action == "epic"
    assert agent.approve is True


def test_manual_plan_before_submission_stays_running(tmp_path: Path) -> None:
    """A manual plan writer is still active until a plan exists for review."""
    meta = {"pid": 1234, "plan": True}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"


def test_manual_plan_after_submission_becomes_planning(tmp_path: Path) -> None:
    """PLANNING means a submitted plan is waiting on manual review."""
    meta = {
        "pid": 1234,
        "plan": True,
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "PLANNING"
    assert len(agent.plan_times) == 1


def test_feedback_plan_path_from_agent_meta(tmp_path: Path) -> None:
    """feedback_submitted_at plus plan_path records rejected plan paths."""
    timestamp = "2026-04-27T15:05:00Z"
    plan_path = str(Path.home() / ".sase" / "plans" / "foo.md")
    meta = {
        "pid": 1234,
        "feedback_submitted_at": timestamp,
        "plan_path": plan_path,
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    expected = (
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        .astimezone(get_timezone())
        .replace(tzinfo=None)
    )
    assert agent.feedback_times == [expected]
    assert agent.feedback_plan_paths == {expected: plan_path}


def test_feedback_plan_path_from_agent_meta_wire() -> None:
    """Wire metadata mirrors filesystem feedback plan path enrichment."""
    timestamp = "2026-04-27T15:05:00Z"
    plan_path = str(Path.home() / ".sase" / "plans" / "foo.md")
    agent = _make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            feedback_submitted_at=[timestamp],
            plan_path=plan_path,
        ),
        None,
    )

    expected = (
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        .astimezone(get_timezone())
        .replace(tzinfo=None)
    )
    assert agent.feedback_times == [expected]
    assert agent.feedback_plan_paths == {expected: plan_path}


def test_auto_epic_plan_after_submission_stays_running(tmp_path: Path) -> None:
    """Auto-epic plans do not require manual review after submission."""
    meta = {
        "pid": 1234,
        "plan": True,
        "auto_approve_plan_action": "epic",
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"
    assert len(agent.plan_times) == 1


def test_approved_plan_statuses_are_preserved(tmp_path: Path) -> None:
    """Approved plan markers still take precedence over submission state."""
    meta = {
        "pid": 1234,
        "plan": True,
        "plan_approved": True,
        "plan_action": "epic",
        "auto_approve_plan_action": "epic",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "EPIC APPROVED"


def test_approve_plan_after_submission_stays_running(tmp_path: Path) -> None:
    """General auto-approval also means no manual plan review is pending."""
    meta = {
        "pid": 1234,
        "plan": True,
        "approve": True,
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"
    assert agent.approve is True


def test_wire_auto_epic_plan_before_submission_stays_running() -> None:
    """Snapshot enrichment mirrors active auto-epic plan drafting."""
    agent = _make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(plan=True, auto_approve_plan_action="epic"),
        None,
    )

    assert agent.status == "RUNNING"
    assert agent.auto_approve_plan_action == "epic"
    assert agent.approve is True


def test_wire_manual_plan_after_submission_becomes_planning() -> None:
    """Snapshot enrichment mirrors manual plan review state."""
    agent = _make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            plan=True,
            plan_submitted_at=["2026-04-27T15:05:00Z"],
        ),
        None,
    )

    assert agent.status == "PLANNING"
    assert len(agent.plan_times) == 1


def test_wire_auto_epic_plan_after_submission_stays_running() -> None:
    """Snapshot auto-epic plans do not become manual review items."""
    agent = _make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            plan=True,
            auto_approve_plan_action="epic",
            plan_submitted_at=["2026-04-27T15:05:00Z"],
        ),
        None,
    )

    assert agent.status == "RUNNING"
    assert len(agent.plan_times) == 1


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
