"""Stopped-agent jumps into collapsed clan rows."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import CollapsedClanJumpApp
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree


def test_stopped_jump_reveals_collapsed_clan_custom_gate_member() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="research.confirm",
        status="CONFIRM",
        raw_suffix="target",
        start_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    target.status_bucket = "Stopped"
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    complete = project_clan_tree([origin, target])
    app = CollapsedClanJumpApp(complete, current_identity=origin.identity)

    assert app._jump_to_next_stopped_agent()

    clan = next(agent for agent in complete if agent.is_clan_container)
    assert app._fold_manager.get(agent_fold_key(clan)).name == "EXPANDED"
    assert app._agents[app.current_idx].identity == target.identity


def test_stopped_jump_reveals_collapsed_clan_member_without_acknowledging(
    monkeypatch,
) -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="research.question",
        status="QUESTION",
        raw_suffix="target",
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    target.questions_times = [datetime(2026, 7, 18, 12, 0, 0)]
    complete = project_clan_tree([origin, target])
    app = CollapsedClanJumpApp(complete, current_identity=origin.identity)
    app._unread_completed_agent_ids.add(target.identity)
    unread_before = set(app._unread_completed_agent_ids)
    dismiss = Mock()
    monkeypatch.setattr(
        "sase.notifications.dismiss_notifications_matching_agents", dismiss
    )

    assert app._jump_to_next_stopped_agent()

    clan = next(agent for agent in complete if agent.is_clan_container)
    assert app._fold_manager.get(agent_fold_key(clan)).name == "EXPANDED"
    assert app._agents[app.current_idx].identity == target.identity
    assert app._unread_completed_agent_ids == unread_before
    dismiss.assert_not_called()
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None, "default")]


def test_stopped_jump_expands_only_clan_with_newest_stopped_member() -> None:
    older = make_agent(name="alpha.plan", status="PLAN", raw_suffix="older")
    older.agent_clan = "alpha"
    older.agent_clan_generation = "alpha-generation"
    older.plan_times = [datetime(2026, 7, 18, 11, 0, 0)]
    newer = make_agent(name="beta.question", status="QUESTION", raw_suffix="newer")
    newer.agent_clan = "beta"
    newer.agent_clan_generation = "beta-generation"
    newer.questions_times = [datetime(2026, 7, 18, 12, 0, 0)]
    complete = project_clan_tree([older, newer])
    app = CollapsedClanJumpApp(complete)

    assert app._jump_to_next_stopped_agent()

    states = {
        clan.agent_clan: app._fold_manager.get(agent_fold_key(clan)).name
        for clan in complete
        if clan.is_clan_container
    }
    assert states == {"alpha": "COLLAPSED", "beta": "EXPANDED"}
    assert app._agents[app.current_idx].identity == newer.identity


def test_stopped_jump_orders_visible_and_hidden_rows_and_wraps() -> None:
    hidden = make_agent(
        name="research.question", status="QUESTION", raw_suffix="hidden"
    )
    hidden.agent_clan = "research"
    hidden.agent_clan_generation = "generation"
    hidden.questions_times = [datetime(2026, 7, 18, 12, 0, 0)]
    visible = make_agent(name="visible.plan", status="PLAN", raw_suffix="visible")
    visible.plan_times = [datetime(2026, 7, 18, 11, 0, 0)]
    complete = project_clan_tree([hidden, visible])
    app = CollapsedClanJumpApp(complete, current_identity=visible.identity)

    assert app._jump_to_next_stopped_agent()
    assert app._agents[app.current_idx].identity == hidden.identity
    assert app.refilter_calls == 1

    assert app._jump_to_next_stopped_agent()
    assert app._agents[app.current_idx].identity == visible.identity
    assert app._jump_to_next_stopped_agent()
    assert app._agents[app.current_idx].identity == hidden.identity
    assert app.refilter_calls == 1


def test_stopped_jump_reveals_collapsed_clan_and_tribe_panel() -> None:
    target = make_agent(
        name="research.question",
        status="QUESTION",
        raw_suffix="target",
        tribe="epic",
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    target.questions_times = [datetime(2026, 7, 18, 12, 0, 0)]
    complete = project_clan_tree([target])
    app = CollapsedClanJumpApp(complete, collapsed_panels={"epic"})

    assert app._jump_to_next_stopped_agent()

    clan = next(agent for agent in complete if agent.is_clan_container)
    assert app._fold_manager.get(agent_fold_key(clan)).name == "EXPANDED"
    assert app._collapsed_panel_keys == set()
    assert app._panel_group.focused_key == "epic"
    assert app._agents[app.current_idx].identity == target.identity


def test_stopped_jump_stale_reveal_does_not_change_selection() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="research.question", status="QUESTION", raw_suffix="target"
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    complete = project_clan_tree([origin, target])
    app = CollapsedClanJumpApp(complete, current_identity=origin.identity)
    app.stale_identity = target.identity

    assert not app._jump_to_next_stopped_agent()

    assert app._agents[app.current_idx].identity == origin.identity


def test_stopped_jump_skips_clan_projection_without_stopped_candidates() -> None:
    target = make_agent(name="research.done", status="DONE", raw_suffix="target")
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    app = CollapsedClanJumpApp(project_clan_tree([target]))
    prospective = Mock(wraps=app._prospective_clan_member_panels)
    app._prospective_clan_member_panels = prospective  # type: ignore[method-assign]

    assert not app._jump_to_next_stopped_agent()

    prospective.assert_not_called()
