"""Tests for plan, tag, and epic metadata enrichment."""

import json
from pathlib import Path

import pytest

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import AgentMetaWire
from tests._enrich_agent_helpers import local_time_from_iso, make_agent


def test_auto_approve_plan_action_from_agent_meta(tmp_path: Path) -> None:
    """Plan-specific auto approval is preserved and renders as approved."""
    meta = {"pid": 1234, "auto_approve_plan_action": "epic"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.auto_approve_plan_action == "epic"
    assert agent.approve is True


def test_auto_approve_plan_action_from_agent_meta_wire() -> None:
    """Snapshot metadata mirrors filesystem auto-approval enrichment."""
    agent = make_agent()

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

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.tag == "sase-26"


def test_parallel_family_marker_from_filesystem_and_wire(tmp_path: Path) -> None:
    """Both TUI enrichment paths retain execution-neutral family membership."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "agent_family_parallel": True})
    )
    filesystem_agent = make_agent()
    wire_agent = make_agent()

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(agent_family_parallel=True),
        None,
    )

    assert filesystem_agent.agent_family_parallel is True
    assert wire_agent.agent_family_parallel is True


def test_clan_membership_from_filesystem_and_wire(tmp_path: Path) -> None:
    """Both enrichment paths expose rootless clan identity."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 1234,
                "agent_clan": "research",
                "agent_clan_generation": "20260717010101",
            }
        )
    )
    filesystem_agent = make_agent()
    wire_agent = make_agent()

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(agent_clan="research"),
        None,
    )

    assert filesystem_agent.agent_clan == "research"
    assert filesystem_agent.agent_clan_generation == "20260717010101"
    assert wire_agent.agent_clan == "research"


def test_invalid_tag_from_agent_meta_is_ignored(tmp_path: Path) -> None:
    """Malformed stored directive metadata is not surfaced as a UI tag."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "tag": "has space"})
    )

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.tag is None


def test_tag_from_agent_meta_wire() -> None:
    """Snapshot metadata mirrors filesystem tag enrichment."""
    agent = make_agent()

    enrich_agent_from_meta_wire(agent, AgentMetaWire(tag="sase-26"), None)

    assert agent.tag == "sase-26"


def test_parallel_family_marker_from_agent_meta(tmp_path: Path) -> None:
    """Filesystem metadata exposes the explicit cleanup-cascade marker."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "agent_family_parallel": True})
    )
    agent = make_agent()

    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.agent_family_parallel is True


def test_parallel_family_marker_from_agent_meta_wire() -> None:
    """Snapshot metadata mirrors filesystem parallel-family enrichment."""
    agent = make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(agent_family_parallel=True),
        None,
    )

    assert agent.agent_family_parallel is True


def test_auto_epic_plan_before_submission_stays_running(tmp_path: Path) -> None:
    """An auto-epic plan writer is still active before it submits a plan."""
    meta = {"pid": 1234, "plan": True, "auto_approve_plan_action": "epic"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"
    assert agent.auto_approve_plan_action == "epic"
    assert agent.approve is True


def test_manual_plan_before_submission_stays_running(tmp_path: Path) -> None:
    """A manual plan writer is still active until a plan exists for review."""
    meta = {"pid": 1234, "plan": True}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"


def test_manual_plan_after_submission_becomes_plan(tmp_path: Path) -> None:
    """PLAN means a submitted plan is waiting on manual review."""
    meta = {
        "pid": 1234,
        "plan": True,
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "PLAN"
    assert len(agent.plan_times) == 1


@pytest.mark.parametrize(("tier", "expected"), [("tale", "TALE"), ("epic", "EPIC")])
def test_manual_plan_after_submission_uses_authored_tier(
    tmp_path: Path,
    tier: str,
    expected: str,
) -> None:
    plan_path = tmp_path / f"{tier}.md"
    plan_path.write_text(f"---\ntier: {tier}\n---\n# Plan\n", encoding="utf-8")
    meta = {
        "pid": 1234,
        "plan": True,
        "plan_path": str(plan_path),
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    filesystem_agent = make_agent()
    wire_agent = make_agent()
    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(
            plan=True,
            plan_path=str(plan_path),
            plan_submitted_at=["2026-04-27T15:05:00Z"],
        ),
        None,
    )

    assert filesystem_agent.status == expected
    assert wire_agent.status == expected


def test_manual_plan_tier_resolves_relative_to_recorded_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    plan_path = workspace / "plans" / "epic.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ntier: epic\n---\n# Plan\n", encoding="utf-8")
    meta = {
        "pid": 1234,
        "plan": True,
        "plan_path": "plans/epic.md",
        "workspace_dir": str(workspace),
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(json.dumps(meta))

    filesystem_agent = make_agent()
    wire_agent = make_agent()
    enrich_agent_from_meta(filesystem_agent, str(artifacts))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(
            plan=True,
            plan_path="plans/epic.md",
            workspace_dir=str(workspace),
            plan_submitted_at=["2026-04-27T15:05:00Z"],
        ),
        None,
    )

    assert filesystem_agent.status == "EPIC"
    assert wire_agent.status == "EPIC"


def test_manual_plan_after_submission_overrides_starting(tmp_path: Path) -> None:
    """Plan review markers override pre-run STARTING rows."""
    meta = {
        "pid": 1234,
        "plan": True,
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "PLAN"
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

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    expected = local_time_from_iso(timestamp)
    assert agent.feedback_times == [expected]
    assert agent.feedback_plan_paths == {expected: plan_path}


def test_feedback_plan_path_from_agent_meta_wire() -> None:
    """Wire metadata mirrors filesystem feedback plan path enrichment."""
    timestamp = "2026-04-27T15:05:00Z"
    plan_path = str(Path.home() / ".sase" / "plans" / "foo.md")
    agent = make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            feedback_submitted_at=[timestamp],
            plan_path=plan_path,
        ),
        None,
    )

    expected = local_time_from_iso(timestamp)
    assert agent.feedback_times == [expected]
    assert agent.feedback_plan_paths == {expected: plan_path}


def test_direct_plan_path_priority_from_agent_meta(tmp_path: Path) -> None:
    """Committed metadata selects SDD while retaining both source paths."""
    (tmp_path / "plan_path.json").write_text(
        json.dumps({"plan_path": "/plans/marker.md"})
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "plan_path": "/plans/archived.md",
                "sdd_plan_path": "/plans/canonical.md",
                "plan_committed": True,
                "epic_bead_id": "sase-10",
                "phase_bead_id": "sase-10.2",
            }
        )
    )
    agent = make_agent()

    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.plan_path == "/plans/canonical.md"
    assert agent.archived_plan_path == "/plans/archived.md"
    assert agent.sdd_plan_path == "/plans/canonical.md"
    assert agent.plan_committed is True
    assert agent.epic_bead_id == "sase-10"
    assert agent.phase_bead_id == "sase-10.2"


def test_plan_path_marker_survives_missing_agent_meta(tmp_path: Path) -> None:
    (tmp_path / "plan_path.json").write_text(
        json.dumps({"plan_path": "/plans/marker.md"})
    )
    agent = make_agent()

    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.plan_path == "/plans/marker.md"
    assert agent.archived_plan_path == "/plans/marker.md"


def test_direct_plan_path_priority_from_agent_meta_wire() -> None:
    agent = make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            plan_path="/plans/archived.md",
            sdd_plan_path="/plans/canonical.md",
            plan_committed=True,
            epic_bead_id="sase-10",
            phase_bead_id="sase-10.2",
        ),
        None,
        plan_path_marker="/plans/marker.md",
    )

    assert agent.plan_path == "/plans/canonical.md"
    assert agent.archived_plan_path == "/plans/archived.md"
    assert agent.sdd_plan_path == "/plans/canonical.md"
    assert agent.plan_committed is True
    assert agent.epic_bead_id == "sase-10"
    assert agent.phase_bead_id == "sase-10.2"


def test_explicit_uncommitted_false_selects_archive_for_filesystem_and_wire(
    tmp_path: Path,
) -> None:
    payload = {
        "plan_path": "/plans/archived.md",
        "sdd_plan_path": "/plans/canonical.md",
        "plan_action": "tale",
        "plan_committed": False,
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(payload))
    filesystem_agent = make_agent()
    wire_agent = make_agent()

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(**payload),
        None,
    )

    for agent in (filesystem_agent, wire_agent):
        assert agent.plan_path == "/plans/archived.md"
        assert agent.archived_plan_path == "/plans/archived.md"
        assert agent.sdd_plan_path == "/plans/canonical.md"
        assert agent.plan_committed is False


def test_non_boolean_plan_committed_is_not_truthiness_coerced(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "plan_path": "/plans/archived.md",
                "sdd_plan_path": "/plans/canonical.md",
                "plan_committed": "false",
            }
        )
    )
    agent = make_agent()

    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.plan_committed is None
    assert agent.plan_path == "/plans/archived.md"


def test_auto_epic_plan_after_submission_stays_running(tmp_path: Path) -> None:
    """Auto-epic plans do not require manual review after submission."""
    meta = {
        "pid": 1234,
        "plan": True,
        "auto_approve_plan_action": "epic",
        "plan_submitted_at": "2026-04-27T15:05:00Z",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
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

    agent = make_agent()
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

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"
    assert agent.approve is True


def test_wire_auto_epic_plan_before_submission_stays_running() -> None:
    """Snapshot enrichment mirrors active auto-epic plan drafting."""
    agent = make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(plan=True, auto_approve_plan_action="epic"),
        None,
    )

    assert agent.status == "RUNNING"
    assert agent.auto_approve_plan_action == "epic"
    assert agent.approve is True


def test_wire_manual_plan_after_submission_becomes_plan() -> None:
    """Snapshot enrichment mirrors manual plan review state."""
    agent = make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            plan=True,
            plan_submitted_at=["2026-04-27T15:05:00Z"],
        ),
        None,
    )

    assert agent.status == "PLAN"
    assert len(agent.plan_times) == 1


def test_wire_manual_plan_after_submission_overrides_starting() -> None:
    """Snapshot plan review markers override pre-run STARTING rows."""
    agent = make_agent(status="STARTING")

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            plan=True,
            plan_submitted_at=["2026-04-27T15:05:00Z"],
        ),
        None,
    )

    assert agent.status == "PLAN"
    assert len(agent.plan_times) == 1


def test_wire_auto_epic_plan_after_submission_stays_running() -> None:
    """Snapshot auto-epic plans do not become manual review items."""
    agent = make_agent()

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


def test_epic_started_at_from_agent_meta(tmp_path: Path) -> None:
    """epic_started_at is parsed into agent.epic_time."""
    timestamp = "2026-04-27T15:05:00Z"
    meta = {"pid": 1234, "epic_started_at": timestamp}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.epic_time == local_time_from_iso(timestamp)


def test_plan_action_from_agent_meta_for_non_running_status(tmp_path: Path) -> None:
    """plan_action is populated from meta even when the agent is not RUNNING.

    The status-mapping `_plan_enrichment_status` gate stays bound to RUNNING,
    but plan_action itself must be independently inspectable so the parent's
    approved-status variant survives across `sase ace` restart.
    """
    meta = {"pid": 1234, "plan_action": "tale"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta))

    agent = make_agent(status="DONE")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.plan_action == "tale"
    assert agent.status == "DONE"


def test_plan_action_from_agent_meta_wire_for_non_running_status() -> None:
    """Wire metadata mirrors filesystem plan_action enrichment for DONE agents."""
    agent = make_agent(status="DONE")

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(plan_action="tale"),
        None,
    )

    assert agent.plan_action == "tale"
    assert agent.status == "DONE"


def test_epic_started_at_from_agent_meta_wire() -> None:
    """wire metadata enrichment mirrors filesystem epic_started_at parsing."""
    timestamp = "2026-04-27T15:05:00Z"
    agent = make_agent()

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(epic_started_at=timestamp),
        None,
    )

    assert agent.epic_time == local_time_from_iso(timestamp)
