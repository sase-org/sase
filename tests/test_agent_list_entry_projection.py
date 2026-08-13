"""Tests for individual rich agent list entry projections."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sase.core.agent_scan_wire import (
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.core.time import get_timezone
from sase.integrations.agent_list_entries import (
    _AgentChildrenSummary,
    _build_agent_list_entry,
)
from sase.integrations._agent_list_entry_builder import record_status_bucket
from tests._agent_list_entries_helpers import agent, record


def test_entry_maps_metadata_and_pending_question_to_stopped_bucket() -> None:
    entry = _build_agent_list_entry(
        agent(),
        record=record(
            agent_meta=AgentMetaWire(
                reasoning_effort="high",
                vcs_provider="github",
                tribe="sase-26",
                bead_id="sase-26.1",
                changespec_name="sase-123",
                agent_family="alpha",
                agent_family_role="code",
                parent_agent_name="planner",
                output_variables={"PLAN": "plans/foo.md"},
            ),
            pending_question=PendingQuestionMarkerWire(session_id="q1"),
        ),
    )

    assert entry.status == "QUESTION"
    assert entry.status_bucket == "Stopped"
    assert entry.status_glyph == "▲"
    assert entry.provider_badge == "🎭"
    assert entry.reasoning_effort == "high"
    assert entry.vcs_provider_display == "GitHub"
    assert entry.tribe == "sase-26"
    assert entry.bead_id == "sase-26.1"
    assert entry.output_variables == {"PLAN": "plans/foo.md"}
    assert entry.pending_question is True
    assert entry.needs_user_action is True


def test_wait_info_prefers_waiting_marker_and_computes_remaining_seconds() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=tz)
    entry = _build_agent_list_entry(
        agent(status="STARTING"),
        record=record(
            agent_meta=AgentMetaWire(
                wait_for=["meta-dep"],
                wait_for_beads=["meta-bead"],
                wait_duration=999.0,
            ),
            waiting=WaitingMarkerWire(
                waiting_for=["dep"],
                wait_for_beads=["sase-87.2"],
                wait_until=(now + timedelta(minutes=5)).isoformat(),
            ),
        ),
        now=now,
    )

    assert entry.status == "WAITING"
    assert entry.status_bucket == "Waiting"
    assert entry.wait.wait_for == ("dep",)
    assert entry.wait.wait_for_beads == ("sase-87.2",)
    assert entry.wait.wait_until is not None
    assert entry.wait.remaining_seconds == 300


def test_plan_marker_becomes_actionable_plan_ready() -> None:
    entry = _build_agent_list_entry(
        agent(),
        record=record(
            agent_meta=AgentMetaWire(
                plan=True,
                plan_submitted_at=["2026-07-09T12:01:00Z"],
            )
        ),
    )

    assert entry.status == "PLAN"
    assert entry.status_bucket == "Stopped"
    assert entry.needs_user_action is True


def test_plan_marker_uses_authored_tier(tmp_path: Path) -> None:
    for tier, expected in (("tale", "TALE"), ("epic", "EPIC")):
        plan_path = tmp_path / f"{tier}.md"
        plan_path.write_text(f"---\ntier: {tier}\n---\n# Plan\n", encoding="utf-8")
        entry = _build_agent_list_entry(
            agent(),
            record=record(
                agent_meta=AgentMetaWire(
                    plan=True,
                    plan_path=str(plan_path),
                    plan_submitted_at=["2026-07-09T12:01:00Z"],
                )
            ),
        )

        assert entry.status == expected
        assert entry.status_bucket == "Stopped"
        assert entry.needs_user_action is True


def test_children_summary_is_preserved() -> None:
    running = _build_agent_list_entry(
        agent(name="run"),
        record=record(agent_meta=AgentMetaWire()),
        children=_AgentChildrenSummary(count=2, status_counts=(("Running", 2),)),
    )

    assert running.children.badge == "×2"
    assert running.children.status_counts == (("Running", 2),)


def test_completed_epic_parent_is_terminal_despite_running_bucket() -> None:
    entry = _build_agent_list_entry(
        agent(status="EPIC APPROVED"),
        record=record(
            has_done_marker=True,
            done=DoneMarkerWire(outcome="epic_approved"),
        ),
    )

    assert entry.status == "EPIC APPROVED"
    assert entry.status_bucket == "Running"
    assert entry.has_done_marker is True
    assert entry.is_terminal is True


def test_entry_uses_agent_status_bucket_override_for_custom_label() -> None:
    entry = _build_agent_list_entry(
        agent(status="MONITORED", status_bucket="Done"),
        record=record(agent_meta=AgentMetaWire()),
    )

    assert entry.status == "MONITORED"
    assert entry.status_bucket == "Done"
    assert entry.status_glyph == "✓"
    assert entry.is_terminal is True


def test_record_status_bucket_uses_marker_override_for_custom_label() -> None:
    bucket = record_status_bucket(
        record(
            agent_meta=AgentMetaWire(status_bucket="Done"),
            has_done_marker=True,
            done=DoneMarkerWire(outcome="completed"),
        )
    )

    assert bucket == "Done"


def test_terminal_monitor_entry_uses_monitor_state_bucket_and_label() -> None:
    artifact_record = record(
        agent_meta=AgentMetaWire(
            monitor_id="m123",
            monitor_state="timeout",
            monitor_label="sleep",
            monitor_command="sleep 60",
            monitor_stop_status="SLEPT",
            status_bucket="Running",
            agent_family_role="monitor",
            role_suffix="--mon",
        ),
        has_done_marker=True,
        done=DoneMarkerWire(
            outcome="monitored",
            monitor_state="timeout",
            status_label="SLEPT",
            status_bucket="Running",
        ),
    )

    entry = _build_agent_list_entry(
        agent(status="DONE", status_bucket="Running"),
        record=artifact_record,
    )

    assert record_status_bucket(artifact_record) == "Failed"
    assert entry.status == "SLEPT"
    assert entry.status_bucket == "Failed"
    assert entry.is_monitor is True
    assert entry.monitor_state == "timeout"


def test_live_epic_parent_is_not_terminal() -> None:
    entry = _build_agent_list_entry(
        agent(),
        record=record(
            agent_meta=AgentMetaWire(
                plan=True,
                plan_approved=True,
                plan_action="epic",
            ),
        ),
    )

    assert entry.status == "EPIC APPROVED"
    assert entry.status_bucket == "Running"
    assert entry.has_done_marker is False
    assert entry.is_terminal is False


def test_missing_artifact_markers_are_safe() -> None:
    entry = _build_agent_list_entry(
        agent(
            artifacts_dir="/tmp/does-not-exist",
            model=None,
            provider=None,
            prompt=None,
        ),
        record=None,
    )

    assert entry.name == "alpha"
    assert entry.model is None
    assert entry.provider_badge is None
    assert entry.status == "RUNNING"
