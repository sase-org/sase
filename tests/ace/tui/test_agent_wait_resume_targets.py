"""Tests for selecting Agents-tab wait and fork prompt targets."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._wait_helpers import (
    resolve_agent_prompt_target_scope as _resolve_agent_prompt_target_scope,
)
from tests.ace.tui._agent_wait_resume_helpers import (
    FakeResumeActionApp,
    make_clan_fixture,
    make_waiting_agent,
)


def test_fork_agent_tale_done_family_root_uses_family_name() -> None:
    agent = make_waiting_agent(
        status="TALE DONE",
        agent_name="aww-plan",
        agent_family="aww",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "#fork:aww ",
            "display_name": "fork(aww)",
            "history_sort_key": "test_cl",
        }
    ]


def test_fork_agent_plan_done_family_root_uses_family_name() -> None:
    agent = make_waiting_agent(
        status="PLAN DONE",
        agent_name="planner-plan",
        agent_family="planner",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:planner "


@pytest.mark.parametrize("status", ["RUNNING", "DONE"])
def test_fork_agent_clan_prefills_scope_for_active_and_done(status: str) -> None:
    container, first, second = make_clan_fixture(status=status)
    app = FakeResumeActionApp([container, first, second])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "#fork:builders ",
            "display_name": "fork(builders)",
            "history_sort_key": "builders",
        }
    ]


def test_clan_fork_scope_uses_only_selected_generation_in_display_order() -> None:
    container, first, second = make_clan_fixture()
    other_generation = make_waiting_agent(
        cl_name="branch_old",
        raw_suffix="20230101120200",
        status="DONE",
        agent_name="old",
        agent_clan="builders",
        agent_clan_generation="gen-0",
    )
    duplicate = first
    app = FakeResumeActionApp([container, second, other_generation, first, duplicate])

    scope, warning = _resolve_agent_prompt_target_scope(app, action="fork")

    assert warning is None
    assert scope is not None
    assert [member.agent for member in scope.vcs_members] == [second, first]


def test_clan_fork_inherits_only_unanimous_vcs_context() -> None:
    container, first, second = make_clan_fixture()
    for agent in (first, second):
        agent.cl_name = "myproj"
        agent.get_raw_xprompt_content = lambda: "#git:myproj do work"  # type: ignore[assignment]
    app = FakeResumeActionApp([container, first, second])

    app.action_fork_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "#git:myproj #fork:builders "


@pytest.mark.parametrize("status", ["RUNNING", "DONE"])
def test_wait_for_clan_prefills_scope_for_active_and_done(status: str) -> None:
    container, first, second = make_clan_fixture(status=status)
    app = FakeResumeActionApp([container, first, second])

    app.action_wait_for_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "%w:builders ",
            "display_name": "wait(builders)",
            "history_sort_key": "builders",
        }
    ]


def test_wait_for_clan_inherits_only_unanimous_vcs_context() -> None:
    container, first, second = make_clan_fixture()
    for agent in (first, second):
        agent.cl_name = "myproj"
        agent.get_raw_xprompt_content = lambda: "#git:myproj do work"  # type: ignore[assignment]
    app = FakeResumeActionApp([container, first, second])

    app.action_wait_for_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "#git:myproj %w:builders "


def test_wait_for_clan_omits_mixed_vcs_context() -> None:
    container, first, second = make_clan_fixture()
    first.get_raw_xprompt_content = lambda: "#git:myproj do work"  # type: ignore[assignment]
    second.get_raw_xprompt_content = lambda: "#git:myproj do work"  # type: ignore[assignment]
    app = FakeResumeActionApp([container, first, second])

    app.action_wait_for_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "%w:builders "


@pytest.mark.parametrize("collapsed", [False, True])
def test_fork_agent_named_tribe_prefills_expanded_or_collapsed(
    collapsed: bool,
) -> None:
    first = make_waiting_agent(
        cl_name="branch_one",
        raw_suffix="20240101120100",
        status="RUNNING",
        agent_name="one",
    )
    second = make_waiting_agent(
        cl_name="branch_two",
        raw_suffix="20240101120200",
        status="DONE",
        agent_name="two",
    )
    app = FakeResumeActionApp([first, second])
    app.panel_focus = SimpleNamespace(panel_key="builders", collapsed=collapsed)
    app.panel_keys = ["builders", "builders"]

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "#fork:@builders ",
            "display_name": "fork(@builders)",
            "history_sort_key": "@builders",
        }
    ]


@pytest.mark.parametrize("collapsed", [False, True])
def test_wait_for_named_tribe_prefills_expanded_or_collapsed(
    collapsed: bool,
) -> None:
    first = make_waiting_agent(
        cl_name="branch_one",
        raw_suffix="20240101120100",
        status="RUNNING",
        agent_name="one",
    )
    second = make_waiting_agent(
        cl_name="branch_two",
        raw_suffix="20240101120200",
        status="DONE",
        agent_name="two",
    )
    app = FakeResumeActionApp([first, second])
    app.panel_focus = SimpleNamespace(panel_key="builders", collapsed=collapsed)
    app.panel_keys = ["builders", "builders"]

    app.action_wait_for_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "%w:@builders ",
            "display_name": "wait(@builders)",
            "history_sort_key": "@builders",
        }
    ]


def test_tribe_scope_excludes_synthetic_rows_and_deduplicates_members() -> None:
    container, first, _second = make_clan_fixture()
    nested = make_waiting_agent(
        cl_name="nested",
        raw_suffix="20240101120300",
        status="DONE",
        agent_name="nested",
        parent_timestamp=first.raw_suffix,
    )
    app = FakeResumeActionApp([container, first, nested, first])
    app.panel_focus = SimpleNamespace(panel_key="builders", collapsed=False)
    app.panel_keys = ["builders"] * 4

    scope, warning = _resolve_agent_prompt_target_scope(app, action="fork")

    assert warning is None
    assert scope is not None
    assert [member.agent for member in scope.vcs_members] == [first, nested]


@pytest.mark.parametrize(
    ("panel_key", "panel_keys", "expected"),
    [
        (None, [None], "The no-tribe panel cannot be forked"),
        ("stale", ["other"], "Tribe '@stale' has no agents"),
    ],
)
def test_fork_agent_invalid_panel_warns_without_opening_prompt(
    panel_key: str | None,
    panel_keys: list[str | None],
    expected: str,
) -> None:
    agent = make_waiting_agent(agent_name="one")
    app = FakeResumeActionApp([agent])
    app.panel_focus = SimpleNamespace(panel_key=panel_key, collapsed=True)
    app.panel_keys = panel_keys

    app.action_fork_agent()

    assert app.notifications == [(expected, "warning")]
    assert app.prompt_bar_calls == []


@pytest.mark.parametrize(
    ("panel_key", "panel_keys", "expected"),
    [
        (None, [None], "The no-tribe panel cannot be used as a wait target"),
        ("stale", ["other"], "Tribe '@stale' has no agents"),
    ],
)
def test_wait_for_invalid_panel_warns_without_opening_prompt(
    panel_key: str | None,
    panel_keys: list[str | None],
    expected: str,
) -> None:
    agent = make_waiting_agent(agent_name="one")
    app = FakeResumeActionApp([agent])
    app.panel_focus = SimpleNamespace(panel_key=panel_key, collapsed=True)
    app.panel_keys = panel_keys

    app.action_wait_for_agent()

    assert app.notifications == [(expected, "warning")]
    assert app.prompt_bar_calls == []


def test_wait_for_empty_clan_warns_without_opening_prompt() -> None:
    container = make_waiting_agent(
        cl_name="builders",
        raw_suffix=None,
        agent_clan="builders",
        agent_clan_generation="gen-1",
        is_clan_container=True,
    )
    app = FakeResumeActionApp([container])

    app.action_wait_for_agent()

    assert app.notifications == [("Clan 'builders' has no agents", "warning")]
    assert app.prompt_bar_calls == []


def test_wait_for_group_banner_does_not_use_remembered_agent() -> None:
    agent = make_waiting_agent(agent_name="one")
    app = FakeResumeActionApp([agent])
    app._current_group_key = ("running",)

    app.action_wait_for_agent()

    assert app.notifications == [("No agent, clan, or tribe selected", "warning")]
    assert app.prompt_bar_calls == []


def test_fork_agent_revalidates_scope_before_opening_prompt() -> None:
    first = make_waiting_agent(agent_name="one", tribe="builders")
    app = FakeResumeActionApp([first])
    app.panel_focus = SimpleNamespace(panel_key="builders", collapsed=False)
    app.panel_keys = ["builders"]
    scope, warning = _resolve_agent_prompt_target_scope(app, action="fork")
    assert warning is None
    assert scope is not None

    app.panel_focus = SimpleNamespace(panel_key="reviewers", collapsed=False)
    app.panel_keys = ["reviewers"]
    app._complete_agent_fork_scope(scope, None)

    assert app.notifications == [
        ("Fork scope changed before the prompt opened", "warning")
    ]
    assert app.prompt_bar_calls == []


def test_fork_scope_snapshots_member_identities_at_keypress() -> None:
    container, first, second = make_clan_fixture()
    app = FakeResumeActionApp([container, first, second])
    scope, warning = _resolve_agent_prompt_target_scope(app, action="fork")
    assert warning is None
    assert scope is not None

    first.cl_name = "moved_branch"
    app._complete_agent_fork_scope(scope, None)

    assert app.notifications == [
        ("Fork scope changed before the prompt opened", "warning")
    ]
    assert app.prompt_bar_calls == []


def test_wait_target_revalidates_scope_before_opening_prompt() -> None:
    first = make_waiting_agent(agent_name="one", tribe="builders")
    app = FakeResumeActionApp([first])
    app.panel_focus = SimpleNamespace(panel_key="builders", collapsed=False)
    app.panel_keys = ["builders"]
    scope, warning = _resolve_agent_prompt_target_scope(app, action="wait")
    assert warning is None
    assert scope is not None

    app.panel_focus = SimpleNamespace(panel_key="reviewers", collapsed=False)
    app.panel_keys = ["reviewers"]
    app._complete_agent_wait_scope(scope, None)

    assert app.notifications == [
        ("Wait target changed before the prompt opened", "warning")
    ]
    assert app.prompt_bar_calls == []


@pytest.mark.parametrize("focused_scope", ["clan", "tribe"])
def test_marked_wait_target_takes_precedence_over_group_focus(
    focused_scope: str,
) -> None:
    container, first, second = make_clan_fixture()
    app = FakeResumeActionApp([container, first, second])
    app._marked_agents = {second.identity}
    if focused_scope == "tribe":
        app.panel_focus = SimpleNamespace(panel_key="builders", collapsed=True)
        app.panel_keys = ["builders", "builders", "builders"]

    app.action_wait_for_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls[0]["initial_text"] == "%w:two "


@pytest.mark.parametrize("marked_count", [1, 2])
def test_marked_wait_target_revalidates_after_prompt_preparation(
    marked_count: int,
) -> None:
    first = make_waiting_agent(
        cl_name="branch_one",
        raw_suffix="20240101120100",
        agent_name="one",
    )
    second = make_waiting_agent(
        cl_name="branch_two",
        raw_suffix="20240101120200",
        agent_name="two",
    )
    replacement = make_waiting_agent(
        cl_name="branch_three",
        raw_suffix="20240101120300",
        agent_name="three",
    )
    app = FakeResumeActionApp([first, second, replacement])
    app._marked_agents = {agent.identity for agent in (first, second)[:marked_count]}
    completions: list[Any] = []

    def defer_preparation(
        _resolver: Any,
        on_complete: Any,
        **_kwargs: object,
    ) -> None:
        completions.append(on_complete)

    app._run_prompt_vcs_preparation = defer_preparation  # type: ignore[method-assign]

    app.action_wait_for_agent()
    app._marked_agents = {replacement.identity}
    completions[0](None)

    assert app.notifications == [
        ("Marked wait targets changed before the prompt opened", "warning")
    ]
    assert app.prompt_bar_calls == []


def test_wait_prompt_scheduling_failure_is_user_visible() -> None:
    agent = make_waiting_agent(agent_name="one")
    app = FakeResumeActionApp([agent])

    def fail_to_schedule(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("worker unavailable")

    app.run_worker = fail_to_schedule  # type: ignore[attr-defined]

    app.action_wait_for_agent()

    assert app.notifications == [("Unable to prepare wait prompt", "error")]
    assert app.prompt_bar_calls == []
