"""Tests for Agents-tab wait application effects on runner-slot queue state."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.ace.tui.modals import WaitModalResult
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)
from tests.ace.tui._agent_wait_resume_helpers import (
    FakeWaitResumeApp,
    make_waiting_agent,
)


def test_apply_wait_updates_parked_runner_threshold_in_place(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%queue(priority=20)\nDo work",
        encoding="utf-8",
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"wait_priority": 20}),
        encoding="utf-8",
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
                "wait_runners": 9,
                "wait_runners_explicit": False,
                "wait_priority": 20,
                "wait_priority_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=9,
        wait_runners_explicit=False,
        wait_priority=20,
        wait_priority_explicit=True,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, capacity=1),
        )

    waiting = json.loads((tmp_path / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["queue_capacity"] == 1
    assert waiting["queue_capacity_explicit"] is True
    assert "wait_runners" not in waiting
    assert "wait_runners_explicit" not in waiting
    assert waiting["wait_priority"] == 20
    assert waiting["wait_priority_explicit"] is True
    assert waiting["slot_requested_at"] == "2026-07-12T12:00:00Z"
    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%queue(capacity=1, priority=20)\nDo work"
    )
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == (
        {"queue_capacity": 1, "queue_capacity_explicit": True, "wait_priority": 20}
    )
    assert agent.wait_runners == 1
    assert agent.wait_runners_explicit is True
    assert agent.wait_priority == 20
    assert agent.wait_priority_explicit is True
    assert agent.status == "QUEUED"
    assert app.killed_agents == []


def test_apply_wait_run_now_releases_parked_runner_slot(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%queue(capacity=1, priority=3)\nDo work", encoding="utf-8"
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 100,
                "queue_capacity": 1,
                "queue_capacity_explicit": True,
                "wait_priority": 3,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
                "queue_capacity": 1,
                "queue_capacity_explicit": True,
                "wait_priority": 3,
                "wait_priority_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=1,
        wait_runners_explicit=True,
        wait_priority=3,
        wait_priority_explicit=True,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    app = FakeWaitResumeApp()

    running_record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(tmp_path),
        project_file=str(tmp_path / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "running"),
        timestamp="20240101115959",
        agent_meta=AgentMetaWire(
            pid=200,
            run_started_at="2026-07-12T11:59:59Z",
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=True),
    )

    def scan_records() -> list[AgentArtifactRecordWire]:
        waiting_data = json.loads((tmp_path / "waiting.json").read_text())
        return [
            running_record,
            AgentArtifactRecordWire(
                project_name="proj",
                project_dir=str(tmp_path),
                project_file=str(tmp_path / "proj.sase"),
                workflow_dir_name="ace-run",
                artifact_dir=str(tmp_path),
                timestamp="20240101120000",
                agent_meta=AgentMetaWire(pid=100),
                waiting=WaitingMarkerWire(
                    queue_capacity=waiting_data.get("queue_capacity"),
                    queue_capacity_explicit=bool(
                        waiting_data.get("queue_capacity_explicit", False)
                    ),
                    wait_priority=waiting_data.get("wait_priority"),
                    slot_requested_at=waiting_data.get("slot_requested_at"),
                ),
                workflow_state=WorkflowStateWire(appears_as_agent=True),
            ),
        ]

    with (
        patch(
            "sase.ace.tui.actions.agents._directive_persistence."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        patch.object(run_agent_wait_slots, "_scan_runner_slot_records", scan_records),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, run_now=True),
        )

        waiting = json.loads((tmp_path / "waiting.json").read_text())
        assert "queue_capacity" not in waiting
        assert waiting["queue_capacity_explicit"] is False
        assert "wait_runners" not in waiting
        assert "wait_runners_explicit" not in waiting
        assert "wait_priority" not in waiting
        assert waiting["wait_priority_explicit"] is False
        assert waiting["slot_requested_at"] == "2026-07-12T12:00:00Z"
        assert not (tmp_path / "ready.json").exists()
        assert json.loads((tmp_path / "agent_meta.json").read_text()) == {"pid": 100}
        assert (tmp_path / "raw_xprompt.md").read_text() == "Do work"
        assert agent.wait_runners is None
        assert agent.wait_runners_explicit is False
        assert agent.wait_priority is None
        assert agent.wait_priority_explicit is False
        assert agent.slot_requested_at == "2026-07-12T12:00:00Z"

        claimed, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(tmp_path),
            cl_name="test_cl",
            timestamp="20240101120000",
            directive_threshold=None,
            directive_priority=None,
            claim=lambda: "started",
        )

    assert claimed == "started"
    assert parked is False
    assert not (tmp_path / "waiting.json").exists()
    assert not (tmp_path / "ready.json").exists()
    assert app.killed_agents == []


def test_apply_wait_updates_parked_priority_in_place(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%queue(capacity=1, priority=20)\nDo work",
        encoding="utf-8",
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "queue_capacity": 1,
                "queue_capacity_explicit": True,
                "wait_priority": 20,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "queue_capacity": 1,
                "queue_capacity_explicit": True,
                "wait_priority": 20,
                "wait_priority_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=1,
        wait_runners_explicit=True,
        wait_priority=20,
        wait_priority_explicit=True,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(
                agents=[],
                time_token=None,
                capacity=1,
                priority=2,
            ),
        )

    assert (tmp_path / "raw_xprompt.md").read_text() == (
        "%queue(capacity=1, priority=2)\nDo work"
    )
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {
        "queue_capacity": 1,
        "queue_capacity_explicit": True,
        "wait_priority": 2,
    }
    waiting = json.loads((tmp_path / "waiting.json").read_text())
    assert waiting["wait_priority"] == 2
    assert waiting["wait_priority_explicit"] is True
    assert waiting["slot_requested_at"] == "2026-07-12T12:00:00Z"
    assert agent.wait_priority == 2
    assert agent.wait_priority_explicit is True
    assert agent.status == "QUEUED"
    assert app.killed_agents == []
