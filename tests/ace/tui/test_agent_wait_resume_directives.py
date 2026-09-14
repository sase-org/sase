"""Tests for wait-directive spec building and wait-modal candidate selection."""

from __future__ import annotations

from sase.ace.tui.actions.agents._wait_resume import (
    _prompt_wait_spec,
    _wait_modal_candidates,
)
from sase.ace.tui.modals import WaitModalResult
from sase.xprompt.directive_edit import PromptWaitDirective, set_prompt_wait
from tests.ace.tui._agent_wait_resume_helpers import make_waiting_agent


def test_prompt_wait_spec_builds_canonical_forms() -> None:
    assert _prompt_wait_spec(
        WaitModalResult(agents=["alice", "bob"], time_token="5m")
    ) == PromptWaitDirective(agents=("alice", "bob"), time_token="5m")
    assert (
        set_prompt_wait(
            "Do work",
            _prompt_wait_spec(WaitModalResult(agents=[], time_token="5m")),
        )
        == "%wait(time=5m)\nDo work"
    )
    assert (
        set_prompt_wait(
            "Do work",
            _prompt_wait_spec(WaitModalResult(agents=["alice"], time_token=None)),
        )
        == "%wait(alice)\nDo work"
    )
    assert _prompt_wait_spec(
        WaitModalResult(
            agents=["alice"],
            time_token=None,
            priority=20,
            beads=["sase-87.2"],
        )
    ) == PromptWaitDirective(
        agents=("alice",),
        priority=20,
        beads=("sase-87.2",),
    )


def test_wait_modal_candidates_excludes_self_unnamed_and_duplicates() -> None:
    selected = make_waiting_agent(
        cl_name="selected",
        raw_suffix="20240101120000",
        agent_name="selected",
    )
    planner = make_waiting_agent(
        cl_name="planner",
        raw_suffix="20240101120100",
        agent_name="planner",
        llm_provider="claude",
        model="sonnet",
        reasoning_effort="xhigh",
    )
    duplicate = make_waiting_agent(
        cl_name="planner-2",
        raw_suffix="20240101120200",
        agent_name="planner",
    )
    unnamed = make_waiting_agent(
        cl_name="unnamed",
        raw_suffix="20240101120300",
        agent_name=None,
    )

    candidates = _wait_modal_candidates(
        selected,
        [selected, planner, duplicate, unnamed],
    )

    assert [candidate.wait_name for candidate in candidates] == ["planner"]
    assert candidates[0].model == "claude / sonnet@xhigh"


def test_strip_existing_wait_directives_removes_wait_and_time_refs() -> None:
    raw_prompt = "%w:old #t:5m %time:1430 do the thing"

    assert set_prompt_wait(raw_prompt, None) == "do the thing"
