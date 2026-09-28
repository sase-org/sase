"""Cross-tab entry-point tests: revive, Files, notifications, last-launch, unread."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._revive_state import AgentReviveStateMixin
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY
from sase.feature_flags import override_flags

from ._agent_tab_cross_nav_helpers import (
    SASE,
    TabOwner,
    cross_tab_harness_class,
    prepare_cross_tab_app,
    row,
    view,
)
from ._agent_unread_navigation_helpers import UnreadJumpApp


def test_select_revived_agent_switches_tabs() -> None:
    # ``_select_revived_agent`` routes through ``_try_reveal_agent_row``, so
    # the harness needs the full reveal/fold machinery, not the minimal
    # ``TabOwner``.
    class _ReviveHarness(cross_tab_harness_class(), AgentReviveStateMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_ReviveHarness)
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._select_revived_agent(rows[1]) is True
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_select_file_agent_switches_tabs() -> None:
    from sase.ace.tui.actions.artifacts_files import ArtifactsFilesActionsMixin

    class _FilesHarness(cross_tab_harness_class(), ArtifactsFilesActionsMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_FilesHarness)
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._select_file_agent(rows[1].identity, None) is True
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_select_file_agent_unchanged_flag_off() -> None:
    """Flag-off Files open-agent still reveals through the real ladder."""
    from sase.ace.tui.actions.artifacts_files import ArtifactsFilesActionsMixin

    class _FilesHarness(
        cross_tab_harness_class(force_agent_tabs=False), ArtifactsFilesActionsMixin
    ):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_FilesHarness, force_agent_tabs=False)
    with override_flags(agent_tabs=False):
        app._agents = list(rows)
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._select_file_agent(rows[1].identity, None) is True
        assert app._agents[app.current_idx].identity == rows[1].identity
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_notification_navigate_to_agent_tab_switches_tabs() -> None:
    from sase.ace.tui.actions.agents._notification_navigation import (
        navigate_to_agent_tab,
    )

    from ._agent_tab_cross_nav_helpers import two_tab_owner

    owner = two_tab_owner()
    with override_flags(agent_tabs=True):
        assert navigate_to_agent_tab(owner, "proj") is True
        # cl_name matches both rows; the complete-roster scan finds the
        # default-tab row first, so no switch is needed here.
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        only_sase = TabOwner([row("a", tab="sase")])
        only_sase.reindex(only_sase._agents_with_children)
        only_sase._agents = []
        only_sase._active_agent_tab = DEFAULT_AGENT_TAB_KEY
        assert navigate_to_agent_tab(only_sase, "proj") is True
        assert only_sase._active_agent_tab == SASE


def test_navigate_to_agent_tab_fallback_scan_restores_tab_on_failure() -> None:
    """The identity-scan fallback (no Node Finder ladder) owns its switch.

    ``jump_to_loaded_agent`` used to be pre-switched by its callers and
    never restored the tab on failure; the fallback path now switches and
    restores itself.
    """
    from sase.ace.tui.actions.agents._notification_navigation import (
        navigate_to_agent_tab,
    )

    row_a, row_b = row("a"), row("b", tab="sase")
    row_b.pid = 42
    owner = TabOwner([row_a, row_b])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
        # The cached query result goes stale after the switch: the target
        # no longer resolves there, so the scan must restore the tab.
        owner._agents_query_result = [row_a]
        assert navigate_to_agent_tab(owner, "proj", pid=42) is False
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_handle_jump_to_agent_crosses_tabs_through_ladder() -> None:
    """``handle_jump_to_agent`` no longer pre-switches tabs itself.

    It used to call ``_ensure_agent_tab_for`` before ``jump_to_loaded_agent``,
    so the ladder's own ``_try_reveal_agent_row`` saw no pending switch.
    Dropping the pre-switch lets the ladder own the whole cross-tab jump.
    """
    from sase.ace.tui.actions.agents._notification_handlers import (
        handle_jump_to_agent,
    )
    from sase.ace.tui.actions.navigation._node_jump import NodeJumpNavigationMixin
    from sase.notifications import Notification

    class _Harness(cross_tab_harness_class(), NodeJumpNavigationMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    app._agent_search_query = ""
    app.hide_non_run_agents = False
    app._hideable_agents = []

    notification = Notification(
        id="n-jump",
        timestamp="2026-09-27T12:00:00+00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={"cl_name": "proj", "raw_suffix": "b"},
    )
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert handle_jump_to_agent(app, notification) is True
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_handle_jump_to_agent_failed_reveal_restores_tab() -> None:
    """A failed reveal through the ladder restores the tab it left.

    With the pre-switch dropped, the switch and its restore-on-failure both
    live inside ``_try_reveal_agent_row``.
    """
    from sase.ace.tui.actions.agents._notification_handlers import (
        handle_jump_to_agent,
    )
    from sase.ace.tui.actions.navigation._node_jump import NodeJumpNavigationMixin
    from sase.notifications import Notification

    class _Harness(cross_tab_harness_class(), NodeJumpNavigationMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    # Stale query result: the target no longer resolves once the tab
    # switches, so the reveal must fail and restore the previous tab.
    app._agents_query_result = [rows[0]]
    app._agent_search_query = ""
    app.hide_non_run_agents = False
    app._hideable_agents = []

    notification = Notification(
        id="n-jump",
        timestamp="2026-09-27T12:00:00+00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={"cl_name": "proj", "raw_suffix": "b"},
    )
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert handle_jump_to_agent(app, notification) is False
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_reveal_loaded_agent_switches_tabs() -> None:
    from sase.ace.tui.actions._link_follow_targets import LinkFollowTargetsMixin

    class _Harness(cross_tab_harness_class(), LinkFollowTargetsMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    app.current_tab = "artifacts"
    app._current_group_key = None
    app._expanded_panel_focus = False
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._reveal_loaded_agent(rows[1]) is True
        assert app.current_tab == "agents"
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_reveal_loaded_agent_unchanged_flag_off() -> None:
    from sase.ace.tui.actions._link_follow_targets import LinkFollowTargetsMixin

    class _Harness(
        cross_tab_harness_class(force_agent_tabs=False), LinkFollowTargetsMixin
    ):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness, force_agent_tabs=False)
    app.current_tab = "artifacts"
    app._current_group_key = None
    app._expanded_panel_focus = False
    with override_flags(agent_tabs=False):
        app._agents = list(rows)
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._reveal_loaded_agent(rows[1]) is True
        assert app.current_tab == "agents"
        assert app._agents[app.current_idx].identity == rows[1].identity
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_restore_agents_link_trail_hop_switches_tabs() -> None:
    from sase.ace.tui.actions.link_trail import LinkTrailMixin
    from sase.ace.tui.actions._link_follow_types import LinkTrailHop
    from sase.core.artifact_entry_target import ArtifactEntryTarget

    class _Harness(cross_tab_harness_class(), LinkTrailMixin):
        pass

    rows = [row("a"), row("b", tab="sase", name="builder")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    app.current_tab = "artifacts"
    hop = LinkTrailHop(
        tab="agents",
        pane_key=None,
        origin=ArtifactEntryTarget("agents", ("builder",)),
        query_source=None,
    )
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._restore_agents_link_trail_hop(hop) is True
        assert app.current_tab == "agents"
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_restore_agents_link_trail_hop_unchanged_flag_off() -> None:
    from sase.ace.tui.actions.link_trail import LinkTrailMixin
    from sase.ace.tui.actions._link_follow_types import LinkTrailHop
    from sase.core.artifact_entry_target import ArtifactEntryTarget

    class _Harness(cross_tab_harness_class(force_agent_tabs=False), LinkTrailMixin):
        pass

    rows = [row("a"), row("b", tab="sase", name="builder")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness, force_agent_tabs=False)
    app.current_tab = "artifacts"
    hop = LinkTrailHop(
        tab="agents",
        pane_key=None,
        origin=ArtifactEntryTarget("agents", ("builder",)),
        query_source=None,
    )
    with override_flags(agent_tabs=False):
        app._agents = list(rows)
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._restore_agents_link_trail_hop(hop) is True
        assert app.current_tab == "agents"
        assert app._agents[app.current_idx].identity == rows[1].identity
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_activate_member_jump_target_switches_tabs() -> None:
    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows)
    target = SimpleNamespace(role="member", member_identity=rows[1].identity)
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        app._activate_member_jump_target(target)
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_activate_member_jump_target_unchanged_flag_off() -> None:
    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, force_agent_tabs=False)
    target = SimpleNamespace(role="member", member_identity=rows[1].identity)
    with override_flags(agent_tabs=False):
        app._agents = list(rows)
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        app._activate_member_jump_target(target)
        assert app._agents[app.current_idx].identity == rows[1].identity
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_reveal_last_launch_target_switches_tabs() -> None:
    from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
        KillAndEditLastLaunchMixin,
    )

    class _Harness(cross_tab_harness_class(), KillAndEditLastLaunchMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        app._reveal_last_launch_target(rows[1].identity)
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_reveal_last_launch_target_restores_tab_on_reveal_failure() -> None:
    from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
        KillAndEditLastLaunchMixin,
    )

    class _Harness(cross_tab_harness_class(), KillAndEditLastLaunchMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    app._agents_query_result = [rows[0]]
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        app._reveal_last_launch_target(rows[1].identity)
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_reveal_last_launch_target_restores_tab_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised exception mid-reveal still restores the tab it left.

    ``_reveal_last_launch_target`` only restored the tab when the reveal
    machinery returned a failure, not when it raised; the previous tab is
    now tracked outside the try body so both paths restore it.
    """
    from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
        KillAndEditLastLaunchMixin,
    )

    class _Harness(cross_tab_harness_class(), KillAndEditLastLaunchMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch"
        ".reveal_agent_navigation_target",
        _boom,
    )

    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        app._reveal_last_launch_target(rows[1].identity)
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_reveal_last_launch_target_unchanged_flag_off() -> None:
    from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
        KillAndEditLastLaunchMixin,
    )

    class _Harness(
        cross_tab_harness_class(force_agent_tabs=False), KillAndEditLastLaunchMixin
    ):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness, force_agent_tabs=False)
    with override_flags(agent_tabs=False):
        app._agents = list(rows)
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        app._reveal_last_launch_target(rows[1].identity)
        assert app._agents[app.current_idx].identity == rows[1].identity
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def _unread_jump_app(rows: list[Agent]) -> UnreadJumpApp:
    app = UnreadJumpApp(rows, with_panels=True)
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), view())
    app._ensure_agent_tabs_state()
    app._unread_completed_agent_ids = {rows[1].identity}

    def _rescope() -> None:
        app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)

    app._rescope_agents_to_active_tab = _rescope  # type: ignore[method-assign]
    return app


def test_unread_jump_crosses_tabs() -> None:
    rows = [row("a", status="RUNNING"), row("b", tab="sase", status="DONE")]
    app = _unread_jump_app(rows)
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._jump_to_next_unread_done_agent() is True
        assert app._active_agent_tab == SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_unread_jump_unchanged_flag_off() -> None:
    rows = [row("a", status="RUNNING"), row("b", tab="sase", status="DONE")]
    app = _unread_jump_app(rows)
    with override_flags(agent_tabs=False):
        app._agents = list(rows)
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._jump_to_next_unread_done_agent() is True
        assert app._agents[app.current_idx].identity == rows[1].identity
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_unread_timed_jump_candidates_recompute_after_tab_switch() -> None:
    rows = [row("a", status="DONE"), row("b", tab="sase", status="DONE")]
    app = _unread_jump_app(rows)
    app._unread_completed_agent_ids = {rows[0].identity, rows[1].identity}
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        first = app._unread_timed_jump_candidates()
        second = app._unread_timed_jump_candidates()
        assert first is second
        app._switch_agents_tab(SASE, reason="cycle")
        after_switch = app._unread_timed_jump_candidates()
        assert after_switch is not first
