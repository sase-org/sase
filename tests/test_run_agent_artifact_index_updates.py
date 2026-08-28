from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import _write_done_marker_and_update_index
from sase.axe.run_agent_exec_markers import (
    clear_workflow_pdf_activity,
    update_workflow_pdf_status,
    write_done_marker_and_update_index,
)
from sase.axe.run_agent_exec_plan_artifacts import write_plan_path_artifact
from sase.axe.runner_artifacts import write_done_marker


def test_done_marker_write_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_markers."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        done_path = _write_done_marker_and_update_index(
            str(tmp_path),
            {"outcome": "completed"},
        )

    assert Path(done_path) == tmp_path / "done.json"
    assert calls == [str(tmp_path)]
    assert '"outcome": "completed"' in Path(done_path).read_text(encoding="utf-8")


def test_done_marker_write_pulses_project_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = tmp_path / "projects"
    artifacts_dir = (
        projects / "proj" / "artifacts" / "ace-run" / "202608" / "28" / "20260828120000"
    )
    artifacts_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.shells.settlement.sase_projects_dir",
        lambda: projects,
    )

    with patch(
        "sase.axe.run_agent_exec_markers."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        write_done_marker_and_update_index(
            str(artifacts_dir),
            {"outcome": "completed"},
        )

    pulse = projects / "proj" / "artifacts" / ".ace_refresh_pulse"
    assert pulse.is_file()
    assert pulse.read_text(encoding="utf-8").strip()


def test_runner_artifacts_write_done_marker_pulses_project_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = tmp_path / "projects"
    artifacts_dir = (
        projects / "proj" / "artifacts" / "ace-run" / "202608" / "28" / "20260828120000"
    )
    artifacts_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.shells.settlement.sase_projects_dir",
        lambda: projects,
    )

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        write_done_marker(
            str(artifacts_dir),
            cl_name="proj",
            project_file=str(projects / "proj" / "proj.sase"),
            timestamp="260828_120000",
            exit_code=0,
            hidden=False,
        )

    pulse = projects / "proj" / "artifacts" / ".ace_refresh_pulse"
    assert pulse.is_file()
    assert pulse.read_text(encoding="utf-8").strip()


def test_plan_path_artifact_write_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_plan_artifacts."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        write_plan_path_artifact(str(tmp_path), "/tmp/plan.md")

    assert calls == [str(tmp_path)]
    assert (tmp_path / "plan_path.json").read_text(encoding="utf-8") == (
        '{"plan_path": "/tmp/plan.md"}'
    )


def test_workflow_pdf_status_updates_artifact_index(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text('{"status": "running"}', encoding="utf-8")
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_markers."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        update_workflow_pdf_status(
            str(tmp_path),
            {"stage": "source_started", "index": 1, "total": 2, "source_path": "a.md"},
        )
        clear_workflow_pdf_activity(str(tmp_path))

    assert calls == [str(tmp_path), str(tmp_path)]
    data = state_path.read_text(encoding="utf-8")
    assert '"pdf_status"' in data
    assert '"activity"' not in data
