"""Tests for basic Agents-tab wait application behavior (``_apply_wait``)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.modals import WaitModalResult
from tests._project_display_case import ProjectDisplayCase
from tests.ace.tui._agent_wait_resume_helpers import (
    FakeWaitResumeApp,
    make_waiting_agent,
)


def test_apply_wait_overwrites_wait_conditions(tmp_path: Path) -> None:
    waiting_path = tmp_path / "waiting.json"
    waiting_path.write_text(
        json.dumps(
            {
                "waiting_for": ["old_dep"],
                "wait_duration": 300.0,
                "wait_until": "2026-05-01T12:00:00",
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
            }
        ),
        encoding="utf-8",
    )
    agent = make_waiting_agent()
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=["alice", "bob"], time_token=None),
        )

    data = json.loads(waiting_path.read_text(encoding="utf-8"))
    assert data == {
        "cl_name": "test_cl",
        "timestamp": "20240101120000",
        "waiting_for": ["alice", "bob"],
    }
    assert agent.waiting_for == ["alice", "bob"]
    assert agent.wait_duration is None
    assert agent.wait_until is None
    assert app.notifications == [("Now waiting for: alice, bob", "information")]
    assert app.refresh_calls == 1
    assert update_index.call_count == 2
    update_index.assert_any_call(str(tmp_path))


def test_apply_wait_empty_submission_keeps_run_now_behavior(tmp_path: Path) -> None:
    agent = make_waiting_agent(
        waiting_for=["old_dep"],
        waiting_for_beads=["sase-87.2"],
        wait_duration=None,
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, run_now=True),
        )

    ready_path = tmp_path / "ready.json"
    assert json.loads(ready_path.read_text(encoding="utf-8")) == {
        "resolved_deps": ["old_dep"],
        "unwait": True,
    }
    assert agent.waiting_for == []
    assert agent.waiting_for_beads == []
    assert app.notifications == [("Wait: test_cl", "information")]
    update_index.assert_not_called()


def test_apply_wait_run_now_projects_notification_but_keeps_agent_identity(
    tmp_path: Path,
    monkeypatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    agent = make_waiting_agent(cl_name=project_display_case.patch_key)
    app = FakeWaitResumeApp()
    monkeypatch.setattr(
        "sase.project_display_names._project_display_name_map_cached",
        lambda _projects_root=None: project_display_case.snapshot,
    )

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, run_now=True),
        )

    assert app.notifications == [
        (f"Wait: {project_display_case.patch_label}", "information")
    ]
    assert agent.cl_name == project_display_case.patch_key
