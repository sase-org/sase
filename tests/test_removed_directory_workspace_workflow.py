"""Negative coverage for the removed directory workspace workflow."""

from __future__ import annotations


def test_directory_workflow_is_not_registered_workspace_provider() -> None:
    import sase.workspace_provider._registry as registry

    registry._manager = None
    registry.get_all_workflow_metadata.cache_clear()

    from sase.workspace_provider import get_ref_patterns, get_workflow_names

    assert "cd" not in get_workflow_names()
    assert "cd" not in get_ref_patterns()


def test_directory_workflow_is_not_builtin_xprompt() -> None:
    from sase.xprompt.loader import get_all_prompts
    from sase.xprompt.workflow_loader import get_all_workflows

    assert "cd" not in get_all_workflows(project="test")
    assert "cd" not in get_all_prompts(project="test")
