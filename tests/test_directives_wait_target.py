"""Contract tests for `%wait(..., target=session|turn)` (phase sase-1q4.5)."""

from __future__ import annotations

import pytest

from sase.macro._exceptions import DirectiveError
from sase.macro.directive_edit import PromptWaitDirective, set_prompt_wait
from sase.macro.directives import extract_prompt_directives


def test_target_session_and_turn_extract() -> None:
    _, directives = extract_prompt_directives("%wait(planner, target=session)")
    assert directives.wait == ["planner"]
    assert dict(directives.wait_targets) == {"planner": "session"}
    assert directives.wait_for_epics_of == ["planner"]

    _, directives = extract_prompt_directives("%wait(16h, target=turn)")
    assert directives.wait == ["16h"]
    assert dict(directives.wait_targets) == {"16h": "turn"}
    assert directives.wait_for_epics_of == []


def test_target_omitted_is_not_explicit() -> None:
    _, directives = extract_prompt_directives("%wait(planner)")
    assert dict(directives.wait_targets) == {}
    _, directives = extract_prompt_directives("%wait:planner")
    assert dict(directives.wait_targets) == {}


def test_target_without_agent_is_error() -> None:
    with pytest.raises(DirectiveError, match="needs an agent target"):
        extract_prompt_directives("%wait(target=turn)")
    with pytest.raises(DirectiveError, match="needs an agent target"):
        extract_prompt_directives("%wait(time=5m, target=session)")


def test_target_invalid_value_uses_core_message() -> None:
    with pytest.raises(
        DirectiveError,
        match=r"Argument `target` expects one of session \| turn, got `Session`",
    ):
        extract_prompt_directives("%wait(planner, target=Session)")


def test_target_conflict_is_error() -> None:
    with pytest.raises(DirectiveError, match="Conflicting target= values"):
        extract_prompt_directives(
            "%wait(planner, target=turn) %wait(planner, target=session)"
        )


def test_target_turn_with_for_epic_true_is_error() -> None:
    with pytest.raises(
        DirectiveError, match=r"`target=turn` cannot combine with for_epic=true"
    ):
        extract_prompt_directives("%wait(planner, target=turn, for_epic=true)")
    with pytest.raises(
        DirectiveError, match=r"`target=turn` cannot combine with for_epic=true"
    ):
        extract_prompt_directives(
            "%wait(planner, for_epic=true) %wait(planner, target=turn)"
        )


def test_target_turn_with_for_epic_false_is_ok() -> None:
    _, directives = extract_prompt_directives(
        "%wait(planner, target=turn, for_epic=false)"
    )
    assert dict(directives.wait_targets) == {"planner": "turn"}
    assert directives.wait_for_epics_of == []


def test_target_turn_on_tribe_is_error() -> None:
    with pytest.raises(DirectiveError, match=r"`target=turn` cannot wait on `@review`"):
        extract_prompt_directives("%wait(@review, target=turn)")


def test_target_turn_skips_epic_follow_default() -> None:
    _, directives = extract_prompt_directives(
        "%wait(planner, target=turn) %wait(reviewer)"
    )
    assert directives.wait_for_epics_of == ["reviewer"]
    assert dict(directives.wait_targets) == {"planner": "turn"}


def test_target_agent_keyword() -> None:
    _, directives = extract_prompt_directives("%wait(agent=planner, target=turn)")
    assert dict(directives.wait_targets) == {"planner": "turn"}


def test_target_round_trip_through_format() -> None:
    spec = PromptWaitDirective(
        agents=("planner", "reviewer", "coder"),
        epic_follow_agents=("planner",),
        turn_target_agents=("reviewer",),
    )
    prompt = set_prompt_wait("do work", spec)
    assert "%wait(planner)" in prompt
    assert "%wait(coder, for_epic=false)" in prompt
    assert "%wait(reviewer, target=turn)" in prompt
    assert "for_epic=true" not in prompt
    _, directives = extract_prompt_directives(prompt)
    assert dict(directives.wait_targets) == {"reviewer": "turn"}
    assert directives.wait_for_epics_of == ["planner"]


def test_target_turn_group_never_carries_for_epic_true() -> None:
    spec = PromptWaitDirective(
        agents=("reviewer",),
        epic_follow_agents=("reviewer",),
        turn_target_agents=("reviewer",),
    )
    prompt = set_prompt_wait("do work", spec)
    assert prompt is not None
    assert "for_epic=true" not in prompt
    assert "%wait(reviewer, target=turn)" in prompt


def test_target_time_attaches_to_first_group() -> None:
    spec = PromptWaitDirective(
        agents=("planner", "reviewer"),
        time_token="5m",
        turn_target_agents=("reviewer",),
    )
    prompt = set_prompt_wait("do work", spec)
    assert "%wait(planner, time=5m)" in prompt
    assert "%wait(reviewer, target=turn)" in prompt


def test_preserved_turn_target_agents_keeps_prompt_and_records() -> None:
    from sase.ace.tui.actions.agents._wait_helpers import (
        preserved_turn_target_agents,
        prompt_wait_spec,
    )
    from sase.ace.tui.modals.wait_modal_types import WaitModalResult

    class _Agent:
        def get_raw_prompt_content(self) -> str:
            return "%wait(16h, target=turn)\n%wait(planner)\nDo work"

        wait_for_artifacts = [
            {"requested": "16h", "name": "16h--gate", "target": "turn"}
        ]

    assert preserved_turn_target_agents(_Agent(), ["16h", "planner"]) == ("16h",)
    result = WaitModalResult(
        agents=["16h", "planner"],
        time_token=None,
        epic_follow_agents=("16h", "planner"),
        turn_agents=["16h"],
    )
    spec = prompt_wait_spec(result, _Agent())
    assert spec is not None
    assert spec.turn_target_agents == ("16h",)
    assert spec.epic_follow_agents == ("planner",)
    session_only = prompt_wait_spec(
        WaitModalResult(
            agents=["16h", "planner"],
            time_token=None,
            turn_agents=[],
        ),
        _Agent(),
    )
    assert session_only is not None
    assert session_only.turn_target_agents == ()
