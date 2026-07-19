"""Whole-panel collapse behavior on the Agents tab."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._display_panel_refresh import PanelRefreshMixin
from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.actions.agents._navigation_order import AgentNavigationOrderMixin
from sase.ace.tui.actions.agents._panel_navigation import AgentPanelNavigationMixin
from sase.ace.tui.actions.agents._selection import AgentSelectionMixin
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.actions.navigation._entry_jump_mode import EntryJumpModeMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent
from sase.ace.tui.models.fold_state import FoldStateManager


class _StubApp(
    AgentFoldingMixin,
    AgentSelectionMixin,
    AgentPanelNavigationMixin,
    AgentNavigationOrderMixin,
    PanelRefreshMixin,
):
    def __init__(
        self,
        agents: list[Agent],
        *,
        focused_key: str | None = None,
        merged: bool = False,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = 7
        self._agents = agents
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._agent_panels_grouped = merged
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            focused_key,
            merge_tag_panels=merged,
        )
        self._collapsed_panel_keys: set[str | None] = set()
        self._expanded_panel_focus = False
        self._panel_selection_memory: dict[
            str | None, tuple[str, int | tuple[str, ...]]
        ] = {}
        self._current_group_key: tuple[str, ...] | None = None
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self._panel_index_cache: tuple[Any, bool, Any] | None = None
        self.refresh_calls: list[bool] = []
        self.panel_fold_changes: list[tuple[str | None, bool]] = []
        self.notifications: list[str] = []

    def _agent_panel_index(self) -> Any:
        cached = self._panel_index_cache
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] == self._agent_panels_grouped
        ):
            return cached[2]
        index = build_agent_panel_index(
            self._agents,
            dismissable_statuses=(),
            merge_tag_panels=self._agent_panels_grouped,
        )
        self._panel_index_cache = (
            self._agents,
            self._agent_panels_grouped,
            index,
        )
        return index

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tag_panels=self._agent_panels_grouped,
        )

    def _invalidate_agent_panel_cache(self) -> None:
        self._nav_stops_cache = None
        self._panel_index_cache = None

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls.append(list_changed)
        if list_changed:
            self._sync_panel_group()

    def _refresh_focused_agent_panel(self, *, old_focused_idx: int | None) -> None:
        del old_focused_idx
        self._refresh_agents_display(list_changed=False)

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        return False

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)

    def _record_agents_panel_fold_change(
        self,
        panel_key: str | None,
        *,
        collapsed: bool,
    ) -> None:
        self.panel_fold_changes.append((panel_key, collapsed))


def _agent(*, name: str, project: str, tag: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file=f"/r/{project}/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 15, 12, 0, 0),
        raw_suffix=name,
        agent_name=name,
        tag=tag,
    )


def _multi_panel_agents() -> list[Agent]:
    return [
        _agent(name="untagged", project="home", tag=None),
        _agent(name="raw-first", project="zeta", tag="alpha"),
        _agent(name="render-first", project="alpha", tag="alpha"),
        _agent(name="beta", project="beta", tag="beta"),
    ]


def test_h_selects_then_collapses_panel_and_l_expands_then_descends() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    registry = app._group_fold_registry.for_panel("alpha")
    registry.collapse(("zeta",))

    app.action_hooks_or_collapse()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is False
    assert app._panel_selection_memory["alpha"] == ("agent", 2)
    assert app._collapsed_panel_keys == set()

    app.action_hooks_or_collapse()

    assert app._collapsed_panel_keys == {"alpha"}
    assert app.current_idx == 1
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._panel_group.panel_keys == [None, "beta", "alpha"]
    assert app._panel_group.focused_key == "alpha"
    assert app._panel_group.focused_idx == 2
    assert app._panel_navigation_stops() == []
    assert app._agents_visible_order() == []
    assert app.refresh_calls == [False, True]

    app.action_expand_or_layout()

    assert app._collapsed_panel_keys == set()
    assert app._resolve_focused_panel() is not None
    assert app.current_idx == 1
    assert app._panel_navigation_stops() == []

    app.action_expand_or_layout()

    assert app._resolve_focused_panel() is None
    assert app.current_idx == 2
    assert app._agents[app.current_idx].agent_name == "render-first"
    assert app._panel_group.panel_keys == [None, "alpha", "beta"]
    assert app._panel_group.focused_key == "alpha"
    assert app._panel_group.focused_idx == 1
    assert registry.is_collapsed(("zeta",)) is True
    assert app.refresh_calls == [False, True, True, False]
    assert app.panel_fold_changes == [("alpha", True), ("alpha", False)]


def test_panel_collapse_guards_single_merged_and_repeated_actions() -> None:
    single = _StubApp([_agent(name="only", project="one", tag=None)])
    single.action_hooks_or_collapse()
    assert single._collapsed_panel_keys == set()
    assert single.refresh_calls == []

    merged = _StubApp(_multi_panel_agents(), merged=True)
    merged.action_hooks_or_collapse()
    assert merged._collapsed_panel_keys == set()
    assert merged.refresh_calls == []

    split = _StubApp(_multi_panel_agents(), focused_key="alpha")
    split.action_hooks_or_collapse()
    split.action_hooks_or_collapse()
    split.action_hooks_or_collapse()
    assert split.refresh_calls == [False, True]
    assert split.notifications == ["Panel is already collapsed"]
    split.action_expand_or_layout()
    split.action_expand_or_layout()
    assert split.refresh_calls == [False, True, True, False]


def test_selected_panel_j_and_k_cycle_without_descending() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    app._panel_selection_memory["alpha"] = ("agent", 2)
    app._collapsed_panel_keys.add("beta")
    app._sync_panel_group()
    app._expanded_panel_focus = True

    BasicNavigationMixin._navigate_agents_panel(app, 1)

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "beta"
    assert focus.collapsed is True
    assert app._panel_navigation_stops() == []

    BasicNavigationMixin._navigate_agents_panel(app, 1)

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key is None
    assert focus.collapsed is False

    BasicNavigationMixin._navigate_agents_panel(app, -1)

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "beta"
    assert focus.collapsed is True


def test_escape_from_expanded_panel_restores_remembered_banner() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    banner = ("zeta",)
    app._group_fold_registry.for_panel("alpha").collapse(banner)
    app._panel_selection_memory["alpha"] = ("banner", banner)
    app._expanded_panel_focus = True

    assert app._exit_expanded_panel_focus() is True

    assert app._resolve_focused_panel() is None
    assert app._current_group_key == banner
    assert app.current_idx == 1


def test_panel_switch_lands_on_collapsed_panel_and_l_reanchors() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key=None)
    app._collapsed_panel_keys.add("alpha")
    app._sync_panel_group()

    app.action_focus_next_agent_panel()

    assert app._panel_group.focused_key == "beta"
    assert app.current_idx == 3

    app.action_focus_next_agent_panel()

    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 1
    assert app._current_group_key is None
    assert app.refresh_calls == [False, False]

    prior = (app.current_idx, app._current_group_key)
    BasicNavigationMixin._navigate_agents_panel(app, 1)
    BasicNavigationMixin._navigate_agents_panel(app, -1)
    assert (app.current_idx, app._current_group_key) == prior

    app.action_expand_or_layout()
    app.action_expand_or_layout()
    assert app.current_idx == 2
    assert app._collapsed_panel_keys == set()
    assert app._panel_group.panel_keys == [None, "alpha", "beta"]
    assert app.refresh_calls == [False, False, False, False, True, False]


def test_restored_collapsed_panels_sort_on_panel_sync() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="beta")

    # Fold persistence installs this set before the established refilter/full
    # refresh path synchronizes the rendered panel collection.
    app._collapsed_panel_keys.update({"alpha", None})
    app._sync_panel_group()

    assert app._panel_group.panel_keys == ["beta", None, "alpha"]
    assert app._panel_group.focused_key == "beta"
    assert app._panel_group.focused_idx == 0


def test_hidden_panel_rows_are_omitted_from_cross_panel_consumers() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.add("alpha")

    visible = app._visible_agent_panel_indices()
    targets = EntryJumpModeMixin._jump_candidate_targets(app)

    assert 1 not in visible
    assert 2 not in visible
    assert ("agent", 1) not in targets
    assert ("agent", 2) not in targets
    assert ("agent", 0) in targets
    assert ("agent", 3) in targets
    assert ("panel", "alpha") in targets


def test_collapsed_panel_rows_are_opt_in_without_bypassing_group_folds() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.add("alpha")
    app._group_fold_registry.for_panel("alpha").collapse(("zeta",))

    ordinary = app._visible_agent_panel_indices()
    jumpable = app._visible_agent_panel_indices(include_collapsed_panels=True)

    assert 1 not in ordinary
    assert 2 not in ordinary
    assert 1 not in jumpable
    assert jumpable[2] == app._panel_group.panel_keys.index("alpha")


def test_panel_collapse_state_prunes_and_clears_on_grouping_toggle() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.update({"alpha", "beta"})
    app._agents = [agent for agent in app._agents if agent.tag != "beta"]
    app._invalidate_agent_panel_cache()

    app._sync_panel_group()

    assert app._collapsed_panel_keys == {"alpha"}
    app.action_toggle_agent_panel_grouping()
    assert app._collapsed_panel_keys == set()
    assert app._agent_panels_grouped is True
    assert app._resolve_focused_panel() is None
    assert app.refresh_calls == [True]


def test_expanded_panel_focus_reconciles_when_refresh_membership_churns() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    app._panel_selection_memory["alpha"] = ("agent", 2)
    app._expanded_panel_focus = True

    # Search/refilter-style churn that leaves the panel alive keeps its
    # key-based whole-panel focus and snaps the stale row anchor in-panel.
    app._agents = [agent for agent in app._agents if agent.agent_name != "raw-first"]
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is False
    assert app._agents[app.current_idx].tag == "alpha"

    # If refresh/filter churn removes that tribe, explicit focus and stale
    # selection memory are discarded. Reappearance must not resurrect focus.
    alpha_agents = [agent for agent in app._agents if agent.tag == "alpha"]
    app._agents = [agent for agent in app._agents if agent.tag != "alpha"]
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    assert app._resolve_focused_panel() is None
    assert "alpha" not in app._panel_selection_memory
    assert app._panel_group.focused_key in {None, "beta"}

    app._agents.extend(alpha_agents)
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    assert "alpha" in app._panel_group.panel_keys
    assert app._resolve_focused_panel() is None
