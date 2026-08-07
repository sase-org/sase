"""Host-side effects of the launch and close TaskTriage branches."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.bead._task_gate_actions import _resolve_task_triage_project_cwd
from sase.bead.task_gate import (
    TASK_TRIAGE_COMMAND_PATHS,
    translate_task_triage_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from tests.test_bead.task_gate_test_helpers import task_triage_spec


def test_task_triage_launch_executes_real_command_translates_and_persists_task_id(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-launch"))
    task = SimpleNamespace(task_id="task-bg-123")
    primary = Path("/canonical/sase")

    with (
        patch(
            "sase.bead._task_gate_actions._resolve_task_triage_project_cwd",
            return_value=primary,
        ) as resolve_project,
        patch(
            "sase.bead.task_launch.submit_task_launch_task",
            return_value=task,
        ) as submit,
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ["launch"],
            {},
            feedback="Keep the compatibility shim.",
            source="tui",
        )

    assert execution.response["option_results"] == [
        {"id": "launch", "result": {"action": "launch"}}
    ]
    assert execution.response["task_launch_task_id"] == "task-bg-123"
    persisted = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert persisted["task_launch_task_id"] == "task-bg-123"
    translated = translate_task_triage_response(gate.bundle_path, persisted)
    assert translated.bead_id == "sase-task.1"
    assert translated.project == "sase"
    assert translated.title == "Follow up on the cache"
    assert translated.action == "launch"
    assert translated.feedback == "Keep the compatibility shim."
    assert translated.source == "tui"
    resolve_project.assert_called_once_with("sase")
    submit.assert_called_once_with(
        "sase-task.1",
        cwd=primary,
        feedback="Keep the compatibility shim.",
        origin="ace",
    )


def test_task_triage_close_uses_canceled_resolution_reason_and_canonical_commit(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-close"))
    primary = Path("/canonical/sase")
    project = MagicMock()
    project.last_mutation_outcome = {
        "closed_ids": ["sase-task.1"],
        "already_closed_ids": [],
        "noted_ids": [],
        "cascade_closed_ids": [],
    }
    mutation = SimpleNamespace(project=project, commit=MagicMock())
    observed: dict[str, Any] = {}

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        observed["auto_commit"] = auto_commit
        observed["cwd"] = cwd
        observed["response_exists_before_mutation"] = gate.response_path.is_file()
        yield mutation

    start_cwd = Path.cwd()
    with (
        patch(
            "sase.bead._task_gate_actions._resolve_task_triage_project_cwd",
            return_value=primary,
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=mutation_scope,
        ),
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ["close"],
            {},
            feedback="No longer worth pursuing.",
            source="mobile",
        )

    assert Path.cwd() == start_cwd
    assert execution.response["option_results"] == [
        {"id": "close", "result": {"action": "close"}}
    ]
    assert observed["cwd"] == primary
    assert observed["response_exists_before_mutation"] is True
    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason="No longer worth pursuing.",
        resolution="canceled",
    )
    mutation.commit.assert_called_once_with("chore(beads): close sase-task.1")


def test_task_triage_project_resolution_requires_explicit_project_spec(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    project_dir = projects / "sase"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "sase.sase"
    project_file.write_text("PROJECT_NAME: sase\n", encoding="utf-8")
    primary = tmp_path / "primary"
    primary.mkdir()

    with (
        patch("sase.core.paths.sase_projects_dir", return_value=projects),
        patch(
            "sase.bead.task_launch._resolve_task_launch_cwd",
            return_value=primary,
        ) as resolve,
    ):
        result = _resolve_task_triage_project_cwd("sase")

    assert result == primary
    resolve.assert_called_once_with(None, agent_project_file=project_file)
    with (
        patch("sase.core.paths.sase_projects_dir", return_value=projects),
        pytest.raises(GateError) as exc_info,
    ):
        _resolve_task_triage_project_cwd("missing")
    assert exc_info.value.code == "invalid_task_project"


def test_task_triage_commands_reject_nonempty_input(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-command-input"))
    command_path = gate.bundle_path / TASK_TRIAGE_COMMAND_PATHS["launch"]

    import subprocess

    completed = subprocess.run(
        [str(command_path)],
        cwd=gate.bundle_path,
        input=b'{"unexpected": true}\n',
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert b"must be empty" in completed.stderr
