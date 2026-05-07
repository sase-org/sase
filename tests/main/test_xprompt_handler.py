"""Tests for the ``sase xprompt`` command handler."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from sase.main.xprompt_handler import _handle_list
from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _simple_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="prompt", prompt_part="body")])


def _multi_agent_xprompt_workflow(name: str) -> Workflow:
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="prompt", prompt_part="one\n---\ntwo")],
    )


def _embeddable_workflow(name: str) -> Workflow:
    return Workflow(
        name=name,
        steps=[
            WorkflowStep(name="setup", bash="true"),
            WorkflowStep(name="prompt", prompt_part="body"),
        ],
    )


def _standalone_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="run", agent="do it")])


def test_xprompt_list_includes_kind_and_insertion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts = {
        "commit": _simple_workflow("commit"),
        "multi": _multi_agent_xprompt_workflow("multi"),
        "gh": _embeddable_workflow("gh"),
        "sync": _standalone_workflow("sync"),
    }
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=prompts),
        patch("sase.xprompt.loader.get_all_xprompts", return_value={}),
        patch("sase.xprompt.loader.get_all_workflows", return_value={}),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_list()

    assert exc_info.value.code == 0
    rows = {row["name"]: row for row in json.loads(capsys.readouterr().out)}

    assert rows["commit"]["type"] == "xprompt"
    assert rows["commit"]["kind"] == "xprompt"
    assert rows["commit"]["prefix"] == "#"
    assert rows["commit"]["insertion"] == "#commit"
    assert rows["commit"]["is_skill"] is False

    assert rows["multi"]["type"] == "xprompt"
    assert rows["multi"]["kind"] == "xprompt"
    assert rows["multi"]["prefix"] == "#!"
    assert rows["multi"]["insertion"] == "#!multi"

    assert rows["gh"]["type"] == "workflow"
    assert rows["gh"]["kind"] == "embeddable_workflow"
    assert rows["gh"]["prefix"] == "#"
    assert rows["gh"]["insertion"] == "#gh"

    assert rows["sync"]["type"] == "workflow"
    assert rows["sync"]["kind"] == "standalone_workflow"
    assert rows["sync"]["prefix"] == "#!"
    assert rows["sync"]["insertion"] == "#!sync"


def test_xprompt_list_marks_only_skill_xprompts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    skill = XPrompt(name="sase_plan", content="Plan", skill=True)
    regular = XPrompt(name="review", content="Review")
    prompts = {
        "sase_plan": _simple_workflow("sase_plan"),
        "review": _simple_workflow("review"),
        "ship": _standalone_workflow("ship"),
    }

    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=prompts),
        patch(
            "sase.xprompt.loader.get_all_xprompts",
            return_value={"sase_plan": skill, "review": regular},
        ),
        patch(
            "sase.xprompt.loader.get_all_workflows",
            return_value={"ship": prompts["ship"]},
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_list()

    assert exc_info.value.code == 0
    rows = {row["name"]: row for row in json.loads(capsys.readouterr().out)}

    assert rows["sase_plan"]["is_skill"] is True
    assert rows["review"]["is_skill"] is False
    assert rows["ship"]["is_skill"] is False
