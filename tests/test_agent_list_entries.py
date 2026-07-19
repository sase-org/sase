"""Tests for integration-facing rich agent list projections."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from sase.agent.running import RunningAgentInfo
from sase.agents.cli_list import _agent_to_json
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.core.time import get_timezone
from sase.integrations.agent_list_entries import (
    _AgentChildrenSummary,
    _attach_runner_slot_context,
    _build_agent_list_entry,
    agent_list_entries,
)


def _agent(**overrides: Any) -> RunningAgentInfo:
    tz = get_timezone()
    defaults = {
        "name": "alpha",
        "project": "sase",
        "pid": 1234,
        "model": "opus",
        "provider": "claude",
        "workspace_num": 11,
        "duration": "5m",
        "approve": False,
        "prompt": "Fix the thing",
        "status": "RUNNING",
        "started_at": datetime(2026, 7, 9, 12, 0, tzinfo=tz),
        "duration_seconds": 300,
        "artifacts_dir": "/tmp/sase/artifacts/ace-run/20260709120000",
    }
    defaults.update(overrides)
    return RunningAgentInfo(**defaults)


def _record(**overrides: Any) -> AgentArtifactRecordWire:
    defaults = {
        "project_name": "sase",
        "project_dir": "/tmp/sase",
        "project_file": "/tmp/sase/sase.gp",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/sase/artifacts/ace-run/20260709120000",
        "timestamp": "20260709120000",
    }
    defaults.update(overrides)
    return AgentArtifactRecordWire(**defaults)


def test_entry_maps_metadata_and_pending_question_to_stopped_bucket() -> None:
    entry = _build_agent_list_entry(
        _agent(),
        record=_record(
            agent_meta=AgentMetaWire(
                reasoning_effort="high",
                vcs_provider="github",
                tag="sase-26",
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
    assert entry.tag == "sase-26"
    assert entry.bead_id == "sase-26.1"
    assert entry.output_variables == {"PLAN": "plans/foo.md"}
    assert entry.pending_question is True
    assert entry.needs_user_action is True


def test_wait_info_prefers_waiting_marker_and_computes_remaining_seconds() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=tz)
    entry = _build_agent_list_entry(
        _agent(status="STARTING"),
        record=_record(
            agent_meta=AgentMetaWire(wait_for=["meta-dep"], wait_duration=999.0),
            waiting=WaitingMarkerWire(
                waiting_for=["dep"],
                wait_until=(now + timedelta(minutes=5)).isoformat(),
            ),
        ),
        now=now,
    )

    assert entry.status == "WAITING"
    assert entry.status_bucket == "Waiting"
    assert entry.wait.wait_for == ("dep",)
    assert entry.wait.wait_until is not None
    assert entry.wait.remaining_seconds == 300


def test_runner_slot_wait_info_includes_live_count_and_queue_position() -> None:
    first = _build_agent_list_entry(
        _agent(name="first", status="WAITING"),
        record=_record(
            timestamp="20260709120001",
            artifact_dir="/tmp/sase/artifacts/ace-run/20260709120001",
            agent_meta=AgentMetaWire(),
            waiting=WaitingMarkerWire(
                wait_runners=9,
                slot_requested_at="2026-07-12T12:00:01Z",
            ),
        ),
    )
    second = _build_agent_list_entry(
        _agent(name="second", status="WAITING"),
        record=_record(
            timestamp="20260709120002",
            artifact_dir="/tmp/sase/artifacts/ace-run/20260709120002",
            agent_meta=AgentMetaWire(),
            waiting=WaitingMarkerWire(
                wait_runners=0,
                wait_runners_explicit=True,
                slot_requested_at="2026-07-12T12:00:02Z",
            ),
        ),
    )

    first, second = _attach_runner_slot_context(
        [first, second], 7, runner_slot_holders=("phase",)
    )

    assert first.wait.wait_runners == 9
    assert first.wait.runner_slots_in_use == 7
    assert first.wait.runner_slot_queue_position == 1
    assert first.wait.runner_slot_queue_size == 1
    assert first.wait.runner_slot_holders == ("phase",)
    assert second.wait.wait_runners_explicit is True
    assert second.wait.runner_slot_queue_position is None
    assert second.wait.runner_slot_queue_size == 1
    assert second.wait.runner_slot_holders == ("phase",)


def test_answered_question_runner_wait_has_waiting_precedence(tmp_path) -> None:
    request_path = tmp_path / "question_request.json"
    request_path.write_text("{}")
    (tmp_path / "question_response.json").write_text("{}")
    entry = _build_agent_list_entry(
        _agent(status="RUNNING"),
        record=_record(
            agent_meta=AgentMetaWire(run_started_at="2026-07-09T12:00:00Z"),
            pending_question=PendingQuestionMarkerWire(
                session_id="q1", request_path=str(request_path)
            ),
            waiting=WaitingMarkerWire(
                wait_runners=0,
                slot_requested_at="2026-07-09T12:05:00Z",
            ),
        ),
    )

    assert entry.status == "WAITING"
    assert entry.wait.wait_runners == 0
    assert entry.wait.slot_requested_at == "2026-07-09T12:05:00Z"

    (entry,) = _attach_runner_slot_context([entry], 0)
    assert entry.wait.runner_slot_queue_position == 1


def test_plan_marker_becomes_actionable_plan_ready() -> None:
    entry = _build_agent_list_entry(
        _agent(),
        record=_record(
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
            _agent(),
            record=_record(
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
        _agent(name="run"),
        record=_record(agent_meta=AgentMetaWire()),
        children=_AgentChildrenSummary(count=2, status_counts=(("Running", 2),)),
    )

    assert running.children.badge == "×2"
    assert running.children.status_counts == (("Running", 2),)


def test_completed_epic_parent_is_terminal_despite_running_bucket() -> None:
    entry = _build_agent_list_entry(
        _agent(status="EPIC APPROVED"),
        record=_record(
            has_done_marker=True,
            done=DoneMarkerWire(outcome="epic_approved"),
        ),
    )

    assert entry.status == "EPIC APPROVED"
    assert entry.status_bucket == "Running"
    assert entry.has_done_marker is True
    assert entry.is_terminal is True


def test_live_epic_parent_is_not_terminal() -> None:
    entry = _build_agent_list_entry(
        _agent(),
        record=_record(
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
        _agent(
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


def test_agent_list_json_exposes_runner_slot_fields() -> None:
    entry = _build_agent_list_entry(
        _agent(status="WAITING"),
        record=_record(
            agent_meta=AgentMetaWire(),
            waiting=WaitingMarkerWire(
                wait_runners=0,
                wait_runners_explicit=True,
                slot_requested_at="2026-07-12T12:00:00Z",
            ),
        ),
    )
    (entry,) = _attach_runner_slot_context([entry], 0, runner_slot_holders=("phase",))

    payload = _agent_to_json(entry)

    assert payload["wait_runners"] == 0
    assert payload["wait_runners_explicit"] is True
    assert payload["slot_requested_at"] == "2026-07-12T12:00:00Z"
    assert payload["runner_slots_in_use"] == 0
    assert payload["runner_slot_queue_position"] == 1
    assert payload["runner_slot_queue_size"] == 1
    assert payload["parent_agent_name"] is None
    assert payload["agent_family"] is None
    assert payload["runner_slot_holders"] == ["phase"]


def test_agent_list_entries_names_parallel_child_blocking_waiter(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    child_dir = tmp_path / "ace-run" / "20260717120001"
    child_dir.mkdir(parents=True)
    (child_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "parent_agent_name": "epic",
                "agent_family": "epic",
            }
        )
    )
    waiter_dir = tmp_path / "ace-run" / "20260717120002"
    waiter_dir.mkdir()
    (waiter_dir / "waiting.json").write_text(
        json.dumps(
            {
                "wait_runners": 0,
                "slot_requested_at": "2026-07-17T12:00:02-04:00",
            }
        )
    )
    child = _agent(
        name="epic--phase",
        artifacts_dir=str(child_dir),
        holds_runner_slot=True,
    )
    waiter = _agent(
        name="waiter",
        status="WAITING",
        artifacts_dir=str(waiter_dir),
        holds_runner_slot=False,
    )
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries.list_running_agents",
        lambda: [child, waiter],
    )
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries._children_by_parent_timestamp",
        lambda **_kwargs: {},
    )

    entries = agent_list_entries()
    by_name = {entry.name: entry for entry in entries}

    assert by_name["waiter"].wait.runner_slots_in_use == 1
    assert by_name["waiter"].wait.runner_slot_holders == ("epic--phase",)
    child_payload = _agent_to_json(by_name["epic--phase"])
    assert child_payload["parent_agent_name"] == "epic"
    assert child_payload["agent_family"] == "epic"
