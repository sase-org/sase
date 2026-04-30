"""Tests for the built-in cd workflow file."""

from __future__ import annotations

from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_loader import get_all_workflows


def test_builtin_cd_workflow_loads_as_embeddable_vcs_workflow() -> None:
    workflow = get_all_workflows(project="test").get("cd")

    assert workflow is not None
    assert XPromptTag.vcs in workflow.tags
    assert workflow.wraps_all is True
    assert [step.name for step in workflow.steps] == ["setup", "inject"]
    assert workflow.steps[1].prompt_part == ""
