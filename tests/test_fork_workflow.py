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


@pytest.mark.parametrize("reference", ["#fork:planner,coder", "#fork(planner, coder)"])
def test_embedded_multi_parent_fork_renders_provenance_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    planner_chat = tmp_path / "planner-chat.md"
    coder_chat = tmp_path / "coder-chat.md"
    planner_chat.write_text(
        "## Prompt\n\nPlan it\n\n## Response\n\nPlanner answer\n",
        encoding="utf-8",
    )
    coder_chat.write_text(
        "## Prompt\n\nCode it\n\n## Response\n\nCoder answer\n",
        encoding="utf-8",
    )
    _write_completed_agent(
        tmp_path,
        "20260504010101",
        "planner",
        response_path=planner_chat,
    )
    _write_completed_agent(
        tmp_path,
        "20260504020202",
        "coder",
        response_path=coder_chat,
    )
    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent=f"Review\n{reference}\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, embedded_workflows, pre_step_count = (
            executor._expand_embedded_workflows_in_prompt(
                f"Review\n{reference}\nContinue"
            )
        )

    assert pre_step_count == 2
    assert embedded_workflows == []
    assert expanded_prompt.count("%xprompts_enabled:false") == 1
    assert expanded_prompt.count("%xprompts_enabled:true") == 1
    assert "# Previous Conversations" in expanded_prompt
    assert "forking from 2 prior agent conversations" in expanded_prompt
    assert "## Conversation 1 of 2 — agent `planner`" in expanded_prompt
    assert "## Conversation 2 of 2 — agent `coder`" in expanded_prompt
    assert expanded_prompt.index("Planner answer") < expanded_prompt.index(
        "Coder answer"
    )
    assert expanded_prompt.endswith("# New Query\nContinue")


def test_embedded_single_parent_fork_keeps_legacy_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    chat_path = tmp_path / "previous-chat.md"
    chat_path.write_text(
        "## Prompt\n\nOld question\n\n## Response\n\nOld answer\n",
        encoding="utf-8",
    )
    _write_completed_agent(
        tmp_path,
        "20260504010101",
        "builder",
        response_path=chat_path,
    )
    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent="#fork:builder\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, _, _ = executor._expand_embedded_workflows_in_prompt(
            "#fork:builder\nContinue"
        )

    assert expanded_prompt == (
        "%xprompts_enabled:false\n"
        "# Previous Conversation\n\n"
        "**User:**\n\nOld question\n\n"
        "**Assistant:**\n\nOld answer\n\n"
        "---\n\n"
        "%xprompts_enabled:true\n"
        "# New Query\n"
        "Continue"
    )
