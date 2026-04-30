"""Tests for the built-in cd workflow file."""

from __future__ import annotations

from sase.xprompt.loader import get_all_prompts
from sase.xprompt.reference_display import workflow_reference_insertion
from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_loader import get_all_workflows


def test_builtin_cd_workflow_loads_as_embeddable_vcs_workflow() -> None:
    workflow = get_all_workflows(project="test").get("cd")

    assert workflow is not None
    assert XPromptTag.vcs in workflow.tags
    assert workflow.wraps_all is True
    assert [step.name for step in workflow.steps] == ["setup", "inject"]
    assert workflow.steps[1].prompt_part == ""


def test_builtin_cd_workflow_is_discoverable_as_prompt_insertion() -> None:
    workflow = get_all_prompts(project="test").get("cd")

    assert workflow is not None
    assert workflow_reference_insertion("cd", workflow) == "#cd"
