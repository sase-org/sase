"""Trusted TaskTriage gate contract and host-side effect coverage."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.bead.task_gate import (
    TASK_TRIAGE_COMMAND_PATHS,
    TASK_TRIAGE_PREVIEW_PATH,
    _build_task_triage_gate_spec,
    _resolve_task_triage_project_cwd,
    create_task_triage_gate,
    translate_task_triage_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.registry import adapter_for_kind
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications


def _spec(*, request_id: str = "task-triage-1") -> dict[str, Any]:
    return _build_task_triage_gate_spec(
        request_id=request_id,
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        created_by="claude_coder",
        producer={"agent_name": "triage-test"},
    )


def test_task_triage_gate_builds_canonical_spec_preview_and_pending_action(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_task_triage_gate(
        request_id="task-triage-canonical",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        created_by="claude_coder",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "task_triage"
    assert request["query"] == "launch OR close"
    assert request["branches"] == [["launch"], ["close"]]
    assert request["primary_branch"] == ["launch"]
    assert request["payload"] == {
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
    }
    assert [(option["id"], option["feedback"]) for option in request["options"]] == [
        ("launch", "optional"),
        ("close", "required"),
    ]
    assert request["presentation"]["sender"] == "bead"
    assert request["presentation"]["notes"] == ["sase-task.1 — Follow up on the cache"]
    assert request["presentation"]["tags"] == ["bead", "task"]
    assert request["presentation"]["panel"] == "beads"
    assert request["presentation"]["origin_agent"] == "claude_coder"
    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "# sase-task.1 — Follow up on the cache" in preview
    assert "**Filed by:** `@claude_coder`" in preview
    assert "Make invalidation deterministic." in preview
    assert "Discovered while landing sase-bg." in preview

    [notification] = load_notifications()
    assert notification.action == "TaskTriage"
    assert notification.sender == "bead"
    assert notification.icon == "✦"
    assert notification.tags == ["bead", "task"]
    assert notification.notes == ["sase-task.1 — Follow up on the cache"]
    assert notification.action_data["panel"] == "beads"
    assert notification.action_data["origin_agent"] == "claude_coder"
    [entry] = pending_actions.read_pending_action_store()["actions"].values()
    assert entry["action_kind"] == "task_triage"
    assert adapter_for_kind("task_triage").auto_policy == "forbidden"


def test_task_triage_gate_omits_blank_origin_agent(gate_home: Path) -> None:
    del gate_home
    gate = create_task_triage_gate(
        request_id="task-triage-without-filer",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        created_by="  ",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert "origin_agent" not in request["presentation"]
    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "Filed by" not in preview
    [notification] = load_notifications()
    assert "origin_agent" not in notification.action_data


def test_task_triage_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = _spec(request_id="task-triage-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(query="close OR launch"),
            "invalid_task_triage_query",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["options"][0].update(feedback="disabled"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_task_triage_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {
                    "path": "forged.txt",
                    "role": "attachment",
                    "content": "unexpected",
                }
            ),
            "invalid_task_triage_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_task_triage_preview",
        ),
    ],
)
def test_task_triage_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def test_task_triage_launch_executes_real_command_translates_and_persists_task_id(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="task-triage-launch"))
    task = SimpleNamespace(task_id="task-bg-123")
    primary = Path("/canonical/sase")

    with (
        patch(
            "sase.bead.task_gate._resolve_task_triage_project_cwd",
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
    gate = create_gate(_spec(request_id="task-triage-close"))
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
            "sase.bead.task_gate._resolve_task_triage_project_cwd",
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
    gate = create_gate(_spec(request_id="task-triage-command-input"))
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
