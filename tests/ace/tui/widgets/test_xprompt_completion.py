"""Tests for prompt-input xprompt completion."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.xprompt_completion import (
    build_xprompt_completion_candidates,
    is_xprompt_like_token,
)
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _simple_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="prompt", prompt_part="body")])


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


def test_xprompt_like_token_accepts_standalone_marker() -> None:
    assert is_xprompt_like_token("#foo") is True
    assert is_xprompt_like_token("#!foo") is True
    assert is_xprompt_like_token("#!") is True
    assert is_xprompt_like_token("foo") is False


def test_xprompt_completion_uses_kind_aware_insertions() -> None:
    prompts = {
        "commit": _simple_workflow("commit"),
        "gh": _embeddable_workflow("gh"),
        "sync": _standalone_workflow("sync"),
    }
    with patch("sase.xprompt.loader.get_all_prompts", return_value=prompts):
        candidates, shared = build_xprompt_completion_candidates("#s")

    assert shared == ""
    assert [(c.display, c.insertion, c.name) for c in candidates] == [
        ("#!sync", "#!sync", "sync")
    ]


def test_standalone_marker_filters_to_standalone_workflows() -> None:
    prompts = {
        "sync": _standalone_workflow("sync"),
        "setup": _simple_workflow("setup"),
        "send": _embeddable_workflow("send"),
    }
    with patch("sase.xprompt.loader.get_all_prompts", return_value=prompts):
        candidates, shared = build_xprompt_completion_candidates("#!s")

    assert shared == ""
    assert [(c.display, c.insertion, c.name) for c in candidates] == [
        ("#!sync", "#!sync", "sync")
    ]


def test_xprompt_completion_finds_builtin_cd_workflow() -> None:
    candidates, _ = build_xprompt_completion_candidates("#c")
    by_name = {candidate.name: candidate for candidate in candidates}

    assert "cd" in by_name
    assert by_name["cd"].display == "#cd"
    assert by_name["cd"].insertion == "#cd"
