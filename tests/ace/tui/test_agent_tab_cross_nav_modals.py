"""Cross-tab modal entry-point tests: Procs, run-log, and Node Finder chips."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._agent_tab_jump import AgentTabJumpMixin
from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.models import Agent
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
from sase.ace.tui.models.node_finder import (
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderView,
)
from sase.ace.tui.modals.node_finder_rendering import render_row_prompt
from sase.core.agent_tab import AgentTabKey, DEFAULT_AGENT_TAB_KEY
from sase.monitor_state import MONITOR_PROC_ORIGIN

from ._agent_tab_cross_nav_helpers import (
    SASE,
    cross_tab_harness_class,
    prepare_cross_tab_app,
    row,
    view,
)
from ._member_jump_navigation_helpers import JumpHarness, make_clan


def test_monitor_jump_agent_searches_child_rows() -> None:
    """The Procs monitor-jump searches the complete child roster.

    ``_monitor_jump_agent`` searches ``_agents_with_children`` so jumps
    land on rows hidden as children of the visible roster.
    """
    from sase.ace.tui.modals.procs_pane_agent_jump import _monitor_jump_agent

    hidden_child = row("child")
    hidden_child.monitor_id = "proc-1"

    class _App:
        _agents: list[Agent] = []
        _agents_with_children = [hidden_child]

    app = _App()
    assert _monitor_jump_agent(app, "proc-1") is hidden_child


class _FakeMonitorScreen:
    def __init__(self) -> None:
        self.closed = False

    def action_close(self) -> None:
        self.closed = True


class _ProcsJumpPane:
    jump_mode_active = False

    def __init__(self, app: Any, proc_id: str) -> None:
        from sase.ace.tui.modals.procs_pane_agent_jump import ProcsPaneAgentJumpMixin
        from sase.ace.tui._proc_observer_models import ObservedProc

        self.app = app
        self.screen = _FakeMonitorScreen()
        self._monitor_agent_names: dict[str, str] = {}
        self._task = ObservedProc(
            proc_id=proc_id,
            proc_type="monitor",
            cl_name="proj",
            project_file="/proj/project.yml",
            status="running",
            message="",
            started_at=datetime(2026, 9, 27, 12, 0, 0),
            origin=MONITOR_PROC_ORIGIN,
        )
        self._jump = ProcsPaneAgentJumpMixin._jump_to_monitor_agent
        self._open = ProcsPaneAgentJumpMixin.action_open_monitor_agent

    def _get_selected_task(self) -> Any:
        return self._task

    def action_open_monitor_agent(self) -> None:
        self._open(self)

    def _jump_to_monitor_agent(self, target_identity: Any) -> None:
        self._jump(self, target_identity)


def test_procs_monitor_jump_crosses_tabs(monkeypatch: Any) -> None:
    from sase.ace.tui.modals import config_center_modal

    monkeypatch.setattr(config_center_modal, "ConfigCenterModal", _FakeMonitorScreen)

    rows = [row("a"), row("b", tab="sase")]
    rows[1].monitor_id = "proc-1"
    app = prepare_cross_tab_app(rows)
    app.current_tab = "services"
    pane = _ProcsJumpPane(app, "proc-1")
    app._agents = _scoped_agents_for_owner(app, list(rows))
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app.current_idx = 0
    pane.action_open_monitor_agent()
    assert pane.screen.closed is True
    assert app.current_tab == "agents"
    assert app._active_agent_tab == SASE
    assert app._agents[app.current_idx].identity == rows[1].identity


def test_run_log_modal_jump_crosses_tabs_through_fold_expanding_reveal() -> None:
    """The run-log modal's jump routes through the shared reveal ladder.

    ``action_jump_to_agent_tab`` used to scan ``app._agents`` directly after
    a pre-switch, so a target hidden under a collapsed clan fold on another
    agent tab (absent from the filtered roster entirely) left the toast
    "Agent not found on Agents tab" instead of expanding the fold.
    """
    from sase.ace.tui.models._agent_tree import agent_fold_key
    from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
    from sase.ace.tui.modals.agent_run_log_modal import AgentRunLogModal

    class _Harness(JumpHarness, AgentTabsMixin, AgentTabJumpMixin):
        def _rescope_agents_to_active_tab(self) -> None:
            folded, _ = filter_agents_by_fold_state(
                self._agents_with_children, self._fold_manager
            )
            self._agents = _scoped_agents_for_owner(self, folded)
            self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _refilter_agents(self, **kwargs: Any) -> None:
            folded, _ = filter_agents_by_fold_state(
                self._agents_with_children, self._fold_manager
            )
            self._agents = _scoped_agents_for_owner(self, folded)
            self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _save_current_tab_position(self) -> None:
            pass

    class _FakeModal:
        def __init__(self, app: Any, target: Agent) -> None:
            self.app = app
            self._target = target
            self.dismissed = False

        def _get_highlighted_agent(self) -> Agent | None:
            return self._target

        def _is_dismissed(self, _agent: Agent) -> bool:
            return False

        def dismiss(self) -> None:
            self.dismissed = True

    projected, container = make_clan(2)
    container.agent_tab = "sase"
    member = container.runtime_children[1]

    app = _Harness(projected, container)
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(projected)
    app._agents_query_result = list(projected)
    app._agent_tab_index = build_agent_tab_index(list(projected), view())

    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)

    app._refilter_agents()
    assert app._agents == []

    modal = _FakeModal(app, member)
    AgentRunLogModal.action_jump_to_agent_tab(modal)  # type: ignore[arg-type]

    assert modal.dismissed is True
    assert app._active_agent_tab == AgentTabKey.named("sase")
    assert app._agents[app.current_idx].identity == member.identity


def test_node_finder_row_renders_tab_label_chip() -> None:
    labeled = NodeFinderRow(
        role=NodeFinderRole.NODE,
        identity=("done", "proj", "b"),
        name="agent-b",
        jumpable=True,
        tab_label="sase",
    )
    unlabeled = NodeFinderRow(
        role=NodeFinderRole.NODE,
        identity=("done", "proj", "a"),
        name="agent-a",
        jumpable=True,
    )
    labeled_view = NodeFinderView(rows=(labeled,))
    unlabeled_view = NodeFinderView(rows=(unlabeled,))
    labeled_text = render_row_prompt(
        labeled_view, 0, search_mode=False, pending="", show_status=False, hint_width=1
    )
    unlabeled_text = render_row_prompt(
        unlabeled_view,
        0,
        search_mode=False,
        pending="",
        show_status=False,
        hint_width=1,
    )
    assert "[sase]" in labeled_text.plain
    assert "[sase]" not in unlabeled_text.plain
    assert unlabeled.tab_label == ""
