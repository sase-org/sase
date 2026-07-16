from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_exec import _write_done_marker_and_update_index
from sase.axe.run_agent_exec_markers import (
    clear_workflow_pdf_activity,
    update_workflow_pdf_status,
)
from sase.axe.run_agent_exec_plan_artifacts import write_plan_path_artifact


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
