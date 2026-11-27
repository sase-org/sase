"""Agents-tab `l` jumps to a session's lone running monitor."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui._agent_fold_transition_helpers import make_sequential_agent_session
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


def _selected(app):  # type: ignore[no-untyped-def]
    return app._agents[app.current_idx]


def _session_key(session) -> str:  # type: ignore[no-untyped-def]
    key = agent_fold_key(session)
    assert key is not None
    return key


def _make_session_with_lone_running_monitor(
    *,
    clan: str | None = None,
    extra_members: list | None = None,
):
    session = make_agent("alpha", clan=clan, session="alpha", role="root")
    session.status = "RUNNING"
    session.status_bucket = "Running"
    session.stop_time = _STOPPED
    monitor = make_agent("alpha--mon", clan=clan, session="alpha", role="monitor")
    monitor.monitor_id = "m-lone"
    monitor.monitor_state = "running"
    monitor.status = "MONITORING"
    monitor.status_bucket = "Running"
    monitor.parent_timestamp = session.raw_suffix
    session.followup_agents = [monitor]
    session.runtime_children = [monitor]
    rows = [session, monitor, *(extra_members or [])]
    if clan is not None:
        complete = project_clan_tree(rows)
        container = next(agent for agent in complete if agent.is_clan_container)
        app = ClanLJumpHarness(complete, container)
        return app, container, session, monitor
    app = ClanLJumpHarness(rows, session)
    return app, session, session, monitor


def test_collapsed_session_with_lone_running_monitor_jumps_to_monitor() -> None:
    app, session, _, monitor = _make_session_with_lone_running_monitor()
    key = _session_key(session)
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    assert _selected(app).identity == monitor.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_expanded_session_with_lone_running_monitor_selects_without_fold_change() -> (
    None
):
    app, session, _, monitor = _make_session_with_lone_running_monitor()
    key = _session_key(session)
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

    assert _selected(app).identity == monitor.identity
    assert dict(app._fold_manager._states) == before
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_session_running_agent_turn_keeps_fold_ladder() -> None:
    projected, session, _member = make_sequential_agent_session()
    app = ClanLJumpHarness(projected, session)
    key = _session_key(session)
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert app._fold_manager.get(key) is FoldLevel.EXPANDED
    assert _selected(app).identity == session.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before

    app.action_expand_or_layout()

    assert app._fold_manager.get(key) is FoldLevel.FULLY_EXPANDED
    assert _selected(app).identity == session.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before


def test_clan_with_monitor_only_session_jumps_to_session_then_monitor() -> None:
    done = make_agent("member-done", clan="research")
    done.status = "DONE"
    done.status_bucket = "Done"
    app, container, _session, monitor = _make_session_with_lone_running_monitor(
        clan="research",
        extra_members=[done],
    )
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    session_key = _session_key(_session)
    target = app._resolve_member_jump_target()
    assert target is not None
    assert target.label == "running member"
    assert target.row.identity == _session.identity
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert _selected(app).identity == _session.identity
    assert app._fold_manager.get(clan_key) is not FoldLevel.COLLAPSED
    assert app._fold_manager.get(session_key) is FoldLevel.COLLAPSED
    assert all(agent.identity != monitor.identity for agent in app._agents)
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []
    target = app._resolve_member_jump_target()
    assert target is not None
    assert target.label == "running monitor"

    app.action_expand_or_layout()

    assert _selected(app).identity == monitor.identity
    assert app._fold_manager.get(session_key) is not FoldLevel.COLLAPSED
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 2
    assert app.notifications == []


def test_clan_jump_with_expanded_monitor_only_session_still_selects_session() -> None:
    done = make_agent("member-done", clan="research")
    done.status = "DONE"
    done.status_bucket = "Done"
    app, container, session, monitor = _make_session_with_lone_running_monitor(
        clan="research",
        extra_members=[done],
    )
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    session_key = _session_key(session)
    app._fold_manager.expand(session_key)
    app._refilter_agents()
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )

    app.action_expand_or_layout()

    assert _selected(app).identity == session.identity
    assert any(agent.identity == monitor.identity for agent in app._agents)
    assert app._fold_manager.get(clan_key) is not FoldLevel.COLLAPSED
    assert app._fold_manager.get(session_key) is not FoldLevel.COLLAPSED
    assert app.notifications == []
