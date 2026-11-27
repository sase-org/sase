"""Agents-tab `l` jumps to a clan's lone failed member."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui._agent_jump_clan_helpers import ClanJumpHarness
from tests.ace.tui._member_jump_navigation_helpers import make_agent

_STOPPED = datetime(2026, 7, 18, 12, 5, 0)


class ClanLJumpHarness(AgentFoldingMixin, ClanJumpHarness):
    """Folding dispatcher over the production-shaped member-jump harness."""

    def __init__(self, complete, container) -> None:  # type: ignore[no-untyped-def]
        self._panel_focus = None
        super().__init__(complete, container)
        self.current_idx = next(
            index
            for index, agent in enumerate(self._agents)
            if agent.identity == container.identity
        )

    def _resolve_focused_panel(self):  # type: ignore[no-untyped-def]
        return self._panel_focus


def _make_clan(
    statuses: list[str],
    *,
    harness_cls: type[ClanLJumpHarness] = ClanLJumpHarness,
) -> tuple[ClanLJumpHarness, object, list[object]]:
    members = []
    for index, status in enumerate(statuses):
        member = make_agent(f"member-{index}", clan="research")
        member.status = status
        member.status_bucket = None
        members.append(member)
    from sase.ace.tui.models._agent_tree import project_clan_tree

    complete = project_clan_tree(members)
    container = next(agent for agent in complete if agent.is_clan_container)
    app = harness_cls(complete, container)
    return app, container, members


def _make_failed_session(*, clan: str | None = None):  # type: ignore[no-untyped-def]
    session = make_agent("alpha", clan=clan, session="alpha", role="root")
    session.status = "FAILED"
    session.status_bucket = "Failed"
    session.stop_time = _STOPPED
    code = make_agent("alpha--code", clan=clan, session="alpha", role="code")
    code.status = "FAILED"
    code.status_bucket = "Failed"
    code.stop_time = _STOPPED
    code.parent_timestamp = session.raw_suffix
    session.followup_agents = [code]
    session.runtime_children = [code]
    return session, code


def _clan_key(container) -> str:  # type: ignore[no-untyped-def]
    key = agent_fold_key(container)
    assert key is not None
    return key


def _selected(app):  # type: ignore[no-untyped-def]
    return app._agents[app.current_idx]


def test_collapsed_clan_with_one_failed_jumps_to_member() -> None:
    app, container, _ = _make_clan(["FAILED", "DONE", "WAITING"])
    key = _clan_key(container)
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    failed = next(
        agent
        for agent in app._agents_with_children
        if not agent.is_clan_container and agent.status == "FAILED"
    )
    assert _selected(app).identity == failed.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_expanded_clan_with_one_failed_selects_without_fold_change() -> None:
    app, container, _ = _make_clan(["FAILED", "DONE", "WAITING"])
    key = _clan_key(container)
    app._fold_manager.expand(key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )
    before = dict(app._fold_manager._states)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    failed = next(
        agent
        for agent in app._agents_with_children
        if not agent.is_clan_container and agent.status == "FAILED"
    )
    assert _selected(app).identity == failed.identity
    assert dict(app._fold_manager._states) == before
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_running_member_wins_over_failed_member() -> None:
    app, container, _ = _make_clan(["FAILED", "RUNNING", "DONE"])
    key = _clan_key(container)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    running = next(
        agent
        for agent in app._agents_with_children
        if not agent.is_clan_container and agent.status == "RUNNING"
    )
    assert _selected(app).identity == running.identity
    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_two_failed_keeps_today_behavior() -> None:
    app, container, _ = _make_clan(["FAILED", "FAILED", "DONE"])
    key = _clan_key(container)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()
    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    assert _selected(app).identity == container.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before

    before = dict(app._fold_manager._states)
    app.action_expand_or_layout()
    assert dict(app._fold_manager._states) == before
    assert _selected(app).identity == container.identity


def test_clan_with_failed_session_jumps_to_session_then_failed_turn() -> None:
    session, code = _make_failed_session(clan="research")
    done = make_agent("member-done", clan="research")
    done.status = "DONE"
    done.status_bucket = "Done"
    rows = [session, code, done]
    complete = project_clan_tree(rows)
    container = next(agent for agent in complete if agent.is_clan_container)
    app = ClanLJumpHarness(complete, container)
    clan_key = _clan_key(container)
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    target = app._resolve_member_jump_target()
    assert target is not None
    assert target.label == "failed member"
    assert target.row.identity == session.identity
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert _selected(app).identity == session.identity
    assert app._fold_manager.get(clan_key) is not FoldLevel.COLLAPSED
    session_key = agent_fold_key(session)
    assert session_key is not None
    assert app._fold_manager.get(session_key) is FoldLevel.COLLAPSED
    assert all(agent.agent_name != "alpha--code" for agent in app._agents)
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1

    app.action_expand_or_layout()

    target = next(
        agent
        for agent in app._agents_with_children
        if agent.agent_name == "alpha--code"
    )
    assert _selected(app).identity == target.identity
    assert app._fold_manager.get(session_key) is not FoldLevel.COLLAPSED
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 2
    assert app.notifications == []


def _make_session_app():  # type: ignore[no-untyped-def]
    session, code = _make_failed_session()
    rows = [session, code]
    app = ClanLJumpHarness(rows, session)
    return app, session, code


def test_collapsed_failed_session_jumps_to_failed_turn() -> None:
    from sase.ace.tui.models._agent_tree import agent_fold_key as fold_key

    app, session, code = _make_session_app()
    key = fold_key(session)
    assert key is not None
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    assert _selected(app).identity == code.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_expanded_failed_session_selects_failed_turn_without_fold_change() -> None:
    from sase.ace.tui.models._agent_tree import agent_fold_key as fold_key

    app, session, code = _make_session_app()
    key = fold_key(session)
    assert key is not None
    app._fold_manager.expand(key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == session.identity
    )
    before = dict(app._fold_manager._states)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert _selected(app).identity == code.identity
    assert dict(app._fold_manager._states) == before
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []
