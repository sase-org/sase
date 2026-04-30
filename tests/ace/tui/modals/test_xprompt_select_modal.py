"""Tests for the ACE xprompt selection modal."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.modals.xprompt_select_modal import XPromptSelectModal
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _simple_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="prompt", prompt_part="body")])


def _standalone_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="run", agent="do it")])


def test_xprompt_select_returns_suffix_for_existing_hash_trigger() -> None:
    prompts = {
        "commit": _simple_workflow("commit"),
        "sync": _standalone_workflow("sync"),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    assert modal._insertion_suffix("commit") == "commit"
    assert modal._insertion_suffix("sync") == "!sync"
