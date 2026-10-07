"""Contract tests for `%wait(..., for_epic=)` (phase sase-1h7.3)."""

from __future__ import annotations

import pytest

from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives


def test_for_epic_true_arms_target() -> None:
    _, directives = extract_prompt_directives("%wait(planner, for_epic=true)")
    assert directives.wait == ["planner"]
    assert directives.wait_for_epics_of == ["planner"]


def test_for_epic_false_and_default_never_arm() -> None:
    _, directives = extract_prompt_directives("%wait(planner, for_epic=false)")
    assert directives.wait_for_epics_of == []
    _, directives = extract_prompt_directives("%wait(planner)")
    assert directives.wait_for_epics_of == []
    _, directives = extract_prompt_directives("%wait:planner")
    assert directives.wait_for_epics_of == []


def test_for_epic_without_agent_is_error() -> None:
    with pytest.raises(DirectiveError, match="needs an agent target"):
        extract_prompt_directives("%wait(for_epic=true)")


def test_for_epic_invalid_value_is_error() -> None:
    with pytest.raises(DirectiveError, match="Invalid %wait for_epic= value 'yes'"):
        extract_prompt_directives("%wait(planner, for_epic=yes)")


def test_for_epic_conflict_is_error() -> None:
    with pytest.raises(DirectiveError, match="Conflicting for_epic= values"):
        extract_prompt_directives(
            "%wait(planner, for_epic=true) %wait(planner, for_epic=false)"
        )


def test_for_epic_plan_row_is_error() -> None:
    with pytest.raises(DirectiveError, match="cannot use for_epic=true"):
        extract_prompt_directives("%wait(planner--plan, for_epic=true)")


def test_for_epic_per_occurrence_scope() -> None:
    _, directives = extract_prompt_directives(
        "%wait(planner, for_epic=true) %wait(reviewer)"
    )
    assert directives.wait_for_epics_of == ["planner"]


def test_for_epic_explicit_overrides_default_across_occurrences() -> None:
    _, directives = extract_prompt_directives(
        "%wait(planner) %wait(planner, for_epic=true)"
    )
    assert directives.wait_for_epics_of == ["planner"]


def test_for_epic_case_insensitive_and_agent_keyword() -> None:
    _, directives = extract_prompt_directives("%wait(agent=planner, for_epic=TRUE)")
    assert directives.wait_for_epics_of == ["planner"]


def test_for_epic_plan_row_never_armed() -> None:
    _, directives = extract_prompt_directives("%wait(planner--plan)")
    assert directives.wait_for_epics_of == []


def test_for_epic_round_trip_through_format() -> None:
    from sase.macro.directive_edit import PromptWaitDirective, set_prompt_wait

    spec = PromptWaitDirective(
        agents=("planner", "reviewer"), epic_follow_agents=("planner",)
    )
    prompt = set_prompt_wait("do work", spec)
    assert "%wait(reviewer)" in prompt
    assert "%wait(planner, for_epic=true)" in prompt
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_for_epics_of == ["planner"]


def test_for_epic_markers_carry_field() -> None:
    from sase.ace.tui.actions.agents._directive_persistence import (
        wait_meta_patch_for_token,
        waiting_marker_patch_for_token,
    )

    meta = wait_meta_patch_for_token(
        wait_names=("planner",), wait_for_epics_of=("planner",)
    )
    assert dict(meta.set_values)["wait_for_epics_of"] == ["planner"]
    marker = waiting_marker_patch_for_token(
        wait_names=("planner",), wait_for_epics_of=("planner",)
    )
    assert list(marker.wait_for_epics_of) == ["planner"]


def test_for_epic_wire_round_trip() -> None:
    from sase.core.agent_scan_wire_conversion import (
        _agent_meta_from_dict,
        _waiting_marker_from_dict,
    )

    meta = _agent_meta_from_dict({"wait_for_epics_of": ["planner"]})
    assert list(meta.wait_for_epics_of) == ["planner"]
    marker = _waiting_marker_from_dict({"wait_for_epics_of": ["planner"]})
    assert list(marker.wait_for_epics_of) == ["planner"]
