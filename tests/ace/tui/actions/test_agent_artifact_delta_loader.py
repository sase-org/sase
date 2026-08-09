from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agent_artifact_delta_from_disk_with_state,
)
from tests.agent_scan_golden.fixture_builder import (
    TS_ACE_RUN_DONE,
    TS_HOME_RUNNING,
    TS_WORKFLOW_ROOT,
    build_fixture_tree,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact_dir(
    projects_root: Path,
    project: str,
    workflow: str,
    timestamp: str,
) -> Path:
    return projects_root / project / "artifacts" / workflow / timestamp


def test_delta_loader_normalizes_exact_artifact_dirs_without_broad_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    projects_root = build_fixture_tree(sase_home / "projects")

    waiting_dir = _artifact_dir(projects_root, "home", "ace-run", "20260601000000")
    _write_json(waiting_dir / "running.json", {"pid": 1234, "cl_name": "~"})
    _write_json(
        waiting_dir / "agent_meta.json",
        {
            "name": "waiting_runner",
            "run_started_at": "2026-06-01T00:00:00Z",
        },
    )
    _write_json(waiting_dir / "waiting.json", {"waiting_for": ["dep_agent"]})

    question_dir = _artifact_dir(projects_root, "home", "ace-run", "20260601010000")
    _write_json(question_dir / "running.json", {"pid": 1235, "cl_name": "~"})
    _write_json(
        question_dir / "agent_meta.json",
        {
            "name": "question_runner",
            "run_started_at": "2026-06-01T01:00:00Z",
        },
    )
    _write_json(question_dir / "pending_question.json", {"session_id": "abc"})

    hidden_done_dir = _artifact_dir(
        projects_root,
        "myproj",
        "ace-run",
        "20260601020000",
    )
    _write_json(hidden_done_dir / "done.json", {"outcome": "completed", "hidden": True})

    artifact_dirs = [
        _artifact_dir(projects_root, "home", "ace-run", TS_HOME_RUNNING),
        _artifact_dir(projects_root, "myproj", "ace-run", TS_ACE_RUN_DONE),
        waiting_dir,
        question_dir,
        hidden_done_dir,
        _artifact_dir(
            projects_root,
            "myproj",
            "workflow-three_phase",
            TS_WORKFLOW_ROOT,
        ),
    ]

    with (
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            side_effect=AssertionError("delta load must not broad scan"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=AssertionError("delta load must not query visible inbox"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            side_effect=AssertionError("delta load must not read RUNNING fields"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_hooks",
            side_effect=AssertionError("delta load must not read hooks"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_mentors",
            side_effect=AssertionError("delta load must not read mentors"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_comments",
            side_effect=AssertionError("delta load must not read comments"),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "upsert_agent_artifact_index_artifacts"
        ) as upsert_index,
    ):
        result = load_agent_artifact_delta_from_disk_with_state(
            set(),
            artifact_dirs,
            patch_snapshot=[],
        )

    agents = result.all_agents
    by_suffix = {agent.raw_suffix: agent for agent in agents}
    assert by_suffix[TS_HOME_RUNNING].status == "RUNNING"
    assert by_suffix[TS_ACE_RUN_DONE].status == "DONE"
    assert by_suffix["20260601000000"].status == "WAITING"
    assert by_suffix["20260601010000"].status == "QUESTION"
    assert by_suffix["20260601020000"].hidden is True
    assert any(
        agent.is_workflow_child and agent.step_name == "code" for agent in agents
    )
    assert result.load_state.artifact_source == "artifact_delta"
    assert result.load_state.repair_recommended is False

    indexed_dirs = list(upsert_index.call_args.args[0])
    assert set(indexed_dirs) == {str(path) for path in artifact_dirs}


def test_delta_loader_marks_missing_exact_dir_for_broad_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    projects_root = build_fixture_tree(sase_home / "projects")
    missing_dir = _artifact_dir(projects_root, "home", "ace-run", "20990101000000")

    with patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}):
        result = load_agent_artifact_delta_from_disk_with_state(
            set(),
            [missing_dir],
            patch_snapshot=[],
            update_index=False,
        )

    assert result.all_agents == []
    assert result.load_state.repair_recommended is True
    assert result.load_state.repair_reason == "artifact_delta_scan_incomplete"


def test_delta_loader_accepts_expected_deleted_exact_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    projects_root = build_fixture_tree(sase_home / "projects")
    deleted_dir = _artifact_dir(projects_root, "home", "ace-run", "20990101000000")

    with patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}):
        result = load_agent_artifact_delta_from_disk_with_state(
            set(),
            [deleted_dir],
            patch_snapshot=[],
            update_index=False,
            deleted_artifact_dirs=[deleted_dir],
        )

    assert result.all_agents == []
    assert result.load_state.repair_recommended is False
    assert result.load_state.repair_reason is None
    assert result.load_state.deleted_artifact_dirs == frozenset({str(deleted_dir)})
