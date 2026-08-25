"""Tests for selecting Agents-tab wait and fork prompt targets."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._wait_helpers import (
    resolve_agent_prompt_target_scope as _resolve_agent_prompt_target_scope,
)
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui._agent_wait_resume_helpers import (
    FakeResumeActionApp,
    make_clan_fixture,
    make_waiting_agent,
)


def _proc_shell_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.PROC_SHELL,
        "cl_name": "sase",
        "project_file": "",
        "status": "RUNNING",
        "raw_suffix": "abc123def456",
        "agent_name": "build-docs",
        "proc_id": "abc123def456",
        "proc_status": "running",
    }
    defaults.update(overrides)
    return make_waiting_agent(**defaults)


def _monitor_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_name": "alpha--mon",
        "agent_family": "alpha",
        "agent_family_role": "monitor",
        "role_suffix": "--mon",
        "status": "MONITORING",
        "monitor_id": "m-123",
        "monitor_state": "running",
    }
    defaults.update(overrides)
    return make_waiting_agent(**defaults)


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
        (None, [None], "The reserved @default panel cannot be forked"),
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
        (
            None,
            [None],
            "The reserved @default panel cannot be used as a wait target",
        ),
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


def test_fork_proc_shell_uses_exact_proc_id_with_friendly_label() -> None:
    agent = _proc_shell_agent()
    app = FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "#fork:abc123def456 ",
            "display_name": "fork(build-docs)",
            "history_sort_key": "sase",
        }
    ]


def test_fork_settled_proc_shell_is_still_a_valid_target() -> None:
    agent = _proc_shell_agent(status="DONE", proc_status="success")
    app = FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:abc123def456 "


def test_fork_proc_shell_without_proc_id_warns() -> None:
    agent = _proc_shell_agent(proc_id=None)
    app = FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == [("No proc ID found", "warning")]
    assert app.prompt_bar_calls == []


def test_fork_monitor_uses_exact_monitor_id_with_friendly_label() -> None:
    agent = _monitor_agent()
    app = FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "#fork:m-123 ",
            "display_name": "fork(alpha--mon)",
            "history_sort_key": "test_cl",
        }
    ]


def test_fork_terminal_monitor_is_still_a_valid_target() -> None:
    agent = _monitor_agent(status="MONITORED", monitor_state="completed")
    app = FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:m-123 "


def test_wait_for_proc_shell_is_rejected() -> None:
    # `#fork` resolves a proc shell, but an ordinary `%wait` resolves agent
    # artifacts only, so `%w:<proc_id>` would never release.
    agent = _proc_shell_agent()
    app = FakeResumeActionApp([agent])

    app.action_wait_for_agent()

    assert app.notifications == [
        ("A proc shell can be forked but not used as a wait target", "warning")
    ]
    assert app.prompt_bar_calls == []


def test_wait_for_monitor_is_rejected() -> None:
    agent = _monitor_agent()
    app = FakeResumeActionApp([agent])

    app.action_wait_for_agent()

    assert app.notifications == [
        ("A proc shell can be forked but not used as a wait target", "warning")
    ]
    assert app.prompt_bar_calls == []


def test_proc_shell_scope_has_no_vcs_members() -> None:
    agent = _proc_shell_agent()
    app = FakeResumeActionApp([agent])

    scope, warning = _resolve_agent_prompt_target_scope(app, action="fork")

    assert warning is None
    assert scope is not None
    assert scope.kind == "proc"
    assert scope.vcs_members == ()
