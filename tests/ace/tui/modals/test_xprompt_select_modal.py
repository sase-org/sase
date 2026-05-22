"""Tests for the ACE xprompt selection modal."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.modals.xprompt_select_modal import XPromptSelectModal
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _simple_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="prompt", prompt_part="body")])


def _multi_agent_xprompt_workflow(name: str) -> Workflow:
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="prompt", prompt_part="one\n---\ntwo")],
    )


def _standalone_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="run", agent="do it")])


def test_xprompt_select_returns_suffix_for_existing_hash_trigger() -> None:
    prompts = {
        "commit": _simple_workflow("commit"),
        "multi": _multi_agent_xprompt_workflow("multi"),
        "sync": _standalone_workflow("sync"),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    assert modal._insertion_suffix("commit") == "commit"
    assert modal._insertion_suffix("multi") == "!multi"
    assert modal._insertion_suffix("sync") == "!sync"


def test_xprompt_select_payload_includes_assist_entry_for_smart_args() -> None:
    prompts = {
        "review": Workflow(
            name="review",
            inputs=[InputArg(name="path", type=InputType.PATH)],
            steps=[WorkflowStep(name="prompt", prompt_part="body")],
        ),
        "sync": Workflow(
            name="sync",
            inputs=[InputArg(name="target", type=InputType.LINE)],
            steps=[WorkflowStep(name="run", agent="do it")],
        ),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    review = modal._selection_for_name("review")
    assert review.suffix == "review"
    assert review.entry is not None
    assert review.entry.insertion == "#review"
    assert [inp.name for inp in review.entry.inputs] == ["path"]

    sync = modal._selection_for_name("sync")
    assert sync.suffix == "!sync"
    assert sync.entry is not None
    assert sync.entry.insertion == "#!sync"


def test_xprompt_select_filters_and_previews_descriptions() -> None:
    prompts = {
        "review": Workflow(
            name="review",
            description="Review a selected diff.",
            inputs=[
                InputArg(
                    name="diff",
                    type=InputType.PATH,
                    description="Diff file to inspect.",
                )
            ],
            steps=[WorkflowStep(name="prompt", prompt_part="body")],
        ),
        "ship": _standalone_workflow("ship"),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    assert modal._get_filtered_names("selected diff") == ["review"]
    assert modal._get_filtered_names("file to inspect") == ["review"]
    preview = modal._all_items["review"][0]
    assert "Review a selected diff." in preview
    assert "Diff file to inspect." in preview
