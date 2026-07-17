"""Workflow-level coverage for the built-in ``#fork`` xprompt."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.xprompt.loader import get_sase_package_xprompts_dir
from sase.xprompt.models import UNSET
from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_loader import _load_workflow_from_file
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from sase.xprompt.workflow_validator import validate_workflow


def _load_fork_workflow() -> Workflow:
    workflow = _load_workflow_from_file(get_sase_package_xprompts_dir() / "fork.yml")
    assert workflow is not None
    return workflow


def _write_completed_agent(
    home: Path,
    suffix: str,
    name: str,
    *,
    response_path: Path,
) -> None:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": name}),
        encoding="utf-8",
    )
    (artifacts_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "response_path": str(response_path)}),
        encoding="utf-8",
    )


def test_fork_workflow_name_input_is_optional() -> None:
    """The real ``fork.yml`` allows embedded ``#fork`` without a name."""
    workflow = _load_fork_workflow()

    validate_workflow(workflow)
    name_input = workflow.get_input_by_name("name")
    assert name_input is not None
    assert name_input.default is None
    assert name_input.repeatable is True
    assert all(
        input_arg.default is not UNSET
        for input_arg in workflow.inputs
        if not input_arg.is_step_input
    )


def test_embedded_bare_resume_loads_resolved_chat_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedded bare ``#fork`` resolves a chat path, then loads that transcript."""
    monkeypatch.setenv("HOME", str(tmp_path))
    chat_path = tmp_path / "previous-chat.md"
    chat_text = "Previous agent transcript from resolver output."
    chat_path.write_text(chat_text, encoding="utf-8")
    _write_completed_agent(
        tmp_path,
        "20260504010101",
        "builder",
        response_path=chat_path,
    )

    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent="Review\n#fork\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, embedded_workflows, pre_step_count = (
            executor._expand_embedded_workflows_in_prompt("Review\n#fork\nContinue")
        )

    assert pre_step_count == 2
    assert embedded_workflows == []
    assert chat_text in expanded_prompt
    assert "# Previous Conversation" in expanded_prompt
    assert "Review" in expanded_prompt
    assert "Continue" in expanded_prompt
