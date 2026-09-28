"""Tab-scoped bulk confirmation wording tests (sase-1bc.6.1.5 / sase-1bc.6.1.6.3).

Covers the bulk scope label helper in both flag states, the cleanup panel
modal wording, the D/K confirm modal wording, the marked off-tab line
(including a clan container counted once and remote rows in N and M), the
tribe/custom selector headers, and the `,u` clear-marks toast.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._agent_tabs import (
    AgentTabsMixin,
    bulk_scope_label_for_owner,
    marked_off_tab_count_for_owner,
)
from sase.ace.tui.actions.agents._kill_cleanup_selection import (
    _custom_cleanup_header,
    _tribe_cleanup_header,
)
from sase.ace.tui.actions.agents._marking_kill import AgentMarkedKillMixin
from sase.ace.tui.actions.agents._marking_navigation import AgentMarkNavigationMixin
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.modals import AgentCleanupModal, AgentCleanupPanelState
from sase.ace.tui.modals.agent_cleanup_types import AgentCleanupPanelState as _State
from sase.ace.tui.modals.confirm_kill_modal import (
    ConfirmDismissAllModal,
    ConfirmKillAllModal,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey
from sase.feature_flags import override_flags


def _view(token: Any = ("scope-honesty-test",)) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=False,
        machine_order=(),
        pinned_by_alias={},
        named_order={},
        token=token,
    )


def _row(
    suffix: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
    pid: int | None = 4242,
    agent_clan: str | None = None,
    is_clan_container: bool = False,
    fleet_origin_alias: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status=status,
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        raw_suffix=suffix,
        pid=pid,
        agent_tab=tab,
        agent_clan=agent_clan,
        is_clan_container=is_clan_container,
        fleet_origin_alias=fleet_origin_alias,
    )


_SASE = AgentTabKey.named("sase")


class _ScopeOwner(AgentMarkedKillMixin, AgentMarkNavigationMixin, AgentTabsMixin):
    """Minimal owner driving bulk/mark flows without the full app."""

    def __init__(self, rows: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(rows)
        self._agents_with_children = list(rows)
        self._marked_agents = {row.identity for row in rows}
        self._marked_agent_order = [row.identity for row in rows]
        self._active_agent_tab = DEFAULT_AGENT_TAB_KEY
        self._agent_tab_index = build_agent_tab_index(list(rows), _view())
        self._agent_tab_latched_key = None
        self._agent_tab_known_labels: dict[Any, str] = {}
        self.pushed: list[Any] = []
        self.notices: list[str] = []
        self.remote_stops: list[list[Any]] = []
        self._ensure_agent_tabs_state()

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        """Capture pushed modals instead of mounting them."""
        self.pushed.append(modal)

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Collect toasts instead of showing them."""
        self.notices.append(str(message))

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        """Pretend the cleared-mark repaint patched the row."""
        del agent
        return True

    def _do_bulk_kill_agents(self, *args: Any, **kwargs: Any) -> bool:
        """Stand in for the durable bulk-kill machinery (never confirmed here)."""
        del args, kwargs
        return True

    def _confirm_remote_stop(self, agents: Any) -> None:
        """Capture remote-stop confirms so mixed marked sets still show the modal."""
        self.remote_stops.append(list(agents))


def _two_tab_owner() -> _ScopeOwner:
    return _ScopeOwner([_row("a"), _row("b", tab="sase")])


def _state(**overrides: Any) -> AgentCleanupPanelState:
    base = _State(
        focused_panel_label="@fix",
        panel_running_count=1,
        panel_completed_count=2,
        panel_failed_count=1,
        all_running_count=3,
        all_completed_count=4,
        all_failed_count=1,
        marked_count=2,
        group_count=5,
        tribe_count=2,
    )
    from dataclasses import replace

    return replace(base, **overrides)


# Scope label helper.


def test_scope_label_none_flag_off() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=False):
        assert bulk_scope_label_for_owner(owner) is None
        assert owner._agent_bulk_scope_label() is None  # type: ignore[attr-defined]


def test_scope_label_none_single_tab_flag_on() -> None:
    owner = _ScopeOwner([_row("a"), _row("b")])
    with override_flags(agent_tabs=True):
        assert bulk_scope_label_for_owner(owner) is None


def test_scope_label_names_active_tab_flag_on() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert bulk_scope_label_for_owner(owner) == "on main"
        owner._active_agent_tab = _SASE
        assert bulk_scope_label_for_owner(owner) == "on sase"


def test_scope_label_across_all_tabs() -> None:
    from sase.ace.tui.models.agent_tab_index import ALL_AGENT_TABS

    owner = _two_tab_owner()
    owner._active_agent_tab = ALL_AGENT_TABS  # type: ignore[assignment]
    with override_flags(agent_tabs=True):
        assert bulk_scope_label_for_owner(owner) == "across all tabs"


def test_marked_off_tab_count() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=False):
        assert marked_off_tab_count_for_owner(owner, owner._agents) == 0
    with override_flags(agent_tabs=True):
        assert marked_off_tab_count_for_owner(owner, owner._agents) == 1
        owner._active_agent_tab = _SASE
        assert marked_off_tab_count_for_owner(owner, owner._agents) == 1


# Cleanup panel modal wording.


def test_cleanup_modal_default_wording_unchanged() -> None:
    rows = {row.action: row for row in AgentCleanupModal._build_rows(_state())}
    assert rows["dismiss_all_done"].title == "Dismiss completed everywhere"
    assert rows["dismiss_all_done"].detail == "4 completed across loaded panels"
    assert rows["kill_all"].title == "Kill and dismiss everywhere"
    assert rows["kill_all"].detail == "7 affected across loaded panels"


def test_cleanup_modal_scope_wording() -> None:
    rows = {
        row.action: row
        for row in AgentCleanupModal._build_rows(_state(scope_label="on sase"))
    }
    assert rows["dismiss_all_done"].title == "Dismiss completed on sase"
    assert rows["dismiss_all_done"].detail == "4 completed on sase"
    assert rows["kill_all"].title == "Kill and dismiss on sase"
    assert rows["kill_all"].detail == "7 affected on sase"
    # Panel-scoped rows keep their own wording.
    assert rows["dismiss_panel_done"].detail == "2 completed in @fix"
    assert "loaded panels" not in rows["dismiss_all_done"].detail
    assert "everywhere" not in rows["kill_all"].title


# D/K confirm modal wording.


def test_confirm_modals_default_wording_unchanged() -> None:
    dismiss = ConfirmDismissAllModal("Dismiss: 1 sase agent")
    assert dismiss._message == "Dismiss these completed agents?"
    kill = ConfirmKillAllModal("Kill: 1 sase agent")
    assert kill._message == "Kill running agents and dismiss completed agents?"


def test_confirm_modals_scope_wording() -> None:
    dismiss = ConfirmDismissAllModal("Dismiss: 1 sase agent", "on sase")
    assert dismiss._message == "Dismiss these completed agents on sase?"
    kill = ConfirmKillAllModal("Kill: 1 sase agent", "on sase")
    assert kill._message == "Kill running agents and dismiss completed agents on sase?"


# Marked bulk modal off-tab line.


def test_marked_bulk_modal_no_off_tab_line_flag_off() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=False):
        owner._bulk_kill_marked_agents()
    assert len(owner.pushed) == 1
    assert "other tabs" not in owner.pushed[0].agent_description


def test_marked_bulk_modal_off_tab_line_flag_on() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        owner._bulk_kill_marked_agents()
    assert len(owner.pushed) == 1
    assert "1 of 2 marked agents are on other tabs" in (
        owner.pushed[0].agent_description
    )


def test_marked_bulk_modal_no_line_when_all_on_active_tab() -> None:
    owner = _two_tab_owner()
    owner._active_agent_tab = _SASE
    owner._marked_agents = {
        row.identity for row in owner._agents if row.agent_tab == "sase"
    }
    with override_flags(agent_tabs=True):
        owner._bulk_kill_marked_agents()
    assert len(owner.pushed) == 1
    assert "other tabs" not in owner.pushed[0].agent_description


def test_marked_bulk_modal_off_tab_clan_container_counts_once() -> None:
    local = _row("a")
    container = _row(
        "clan", tab="sase", agent_clan="research", is_clan_container=True, pid=None
    )
    members = [
        _row("c1", tab="sase", agent_clan="research"),
        _row("c2", tab="sase", agent_clan="research"),
        _row("c3", tab="sase", agent_clan="research"),
    ]
    owner = _ScopeOwner([local, container, *members])
    owner._marked_agents = {container.identity}
    owner._marked_agent_order = [container.identity]
    with override_flags(agent_tabs=False):
        owner._bulk_kill_marked_agents()
    assert len(owner.pushed) == 1
    assert "other tabs" not in owner.pushed[0].agent_description
    owner.pushed.clear()
    with override_flags(agent_tabs=True):
        owner._bulk_kill_marked_agents()
    assert len(owner.pushed) == 1
    assert "1 of 1 marked agents are on other tabs" in (
        owner.pushed[0].agent_description
    )


def test_marked_bulk_modal_off_tab_remote_counts_in_n_and_m() -> None:
    local = _row("a")
    remote = _row("b", tab="sase", fleet_origin_alias="apollo")
    owner = _ScopeOwner([local, remote])
    with override_flags(agent_tabs=False):
        owner._bulk_kill_marked_agents()
    assert len(owner.pushed) == 1
    assert "other tabs" not in owner.pushed[0].agent_description
    owner.pushed.clear()
    owner.remote_stops.clear()
    with override_flags(agent_tabs=True):
        owner._bulk_kill_marked_agents()
    assert len(owner.pushed) == 1
    assert "1 of 2 marked agents are on other tabs" in (
        owner.pushed[0].agent_description
    )
    assert len(owner.remote_stops) == 1


# Tribe/custom selector headers.


def test_tribe_custom_headers_default_wording_unchanged() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=False):
        assert _tribe_cleanup_header(owner, ("deploy",)) == "Tribe: @deploy"
        assert _custom_cleanup_header(owner) == "Custom selection"


def test_tribe_custom_headers_scope_wording_flag_on() -> None:
    from sase.ace.tui.models.agent_tab_index import ALL_AGENT_TABS

    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert _tribe_cleanup_header(owner, ("deploy",)) == "Tribe: @deploy on main"
        assert _custom_cleanup_header(owner) == "Custom selection on main"
        owner._active_agent_tab = _SASE
        assert _custom_cleanup_header(owner) == "Custom selection on sase"
        owner._active_agent_tab = ALL_AGENT_TABS  # type: ignore[assignment]
        assert _custom_cleanup_header(owner) == "Custom selection across all tabs"


# Clear-marks (`,u`) toast.


def test_clear_marks_toast_flag_off() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=False):
        owner._clear_agent_marks()
    assert owner.notices == ["Cleared 2 mark(s)"]


def test_clear_marks_toast_names_scope_flag_on() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        owner._clear_agent_marks()
    assert owner.notices == ["Cleared 2 mark(s) across all tabs"]
