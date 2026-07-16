"""Hint-selected whole-panel folding on the Agents tab."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._navigation_order import AgentNavigationOrderMixin
from sase.ace.tui.actions.agents._panel_hint_folding import (
    AgentPanelHintFoldingMixin,
)
from sase.ace.tui.actions.agents._panel_navigation import AgentPanelNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.models.agent_panels import (
    AgentPanelGroup,
    PanelKey,
    panel_key_per_agent,
)
from sase.ace.tui.widgets import HintInputBar


def _agent(name: str, tag: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file=f"/r/{name}/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 16, 12, 0, 0),
        raw_suffix=name,
        agent_name=name,
        tag=tag,
    )


def _agents() -> list[Agent]:
    return [
        _agent("untagged", None),
        _agent("alpha-first", "alpha"),
        _agent("alpha-second", "alpha"),
        _agent("beta", "beta"),
    ]


class _StubApp(
    AgentPanelHintFoldingMixin,
    AgentPanelNavigationMixin,
    AgentNavigationOrderMixin,
):
    def __init__(
        self,
        *,
        focused_key: PanelKey = "alpha",
        merged: bool = False,
        agents: list[Agent] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 2
        self.current_attempt_number: int | None = 7
        self._agents = list(agents if agents is not None else _agents())
        self._agent_panels_grouped = merged
        self._collapsed_panel_keys: set[PanelKey] = {"beta"} if not merged else set()
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tag_panels=merged,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._grouping_mode = GroupingMode.STANDARD
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key: tuple[str, ...] | None = ("kept",)
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self._panel_index_cache: tuple[Any, bool, Any] | None = None
        self._hint_mode_active = False
        self._hint_mode_hints_for: str | None = None
        self._panel_fold_hint_mode_active = False
        self._panel_fold_hint_snapshot: tuple[PanelKey, ...] = ()
        self._panel_fold_hint_to_key: dict[int, PanelKey] = {}
        self._panel_fold_key_to_hint: dict[PanelKey, int] = {}
        self._entry_jump_mode_active = False
        self.refresh_calls = 0
        self.title_refresh_calls = 0
        self.persistence_intents: list[tuple[PanelKey, bool]] = []
        self.notifications: list[str] = []

    def arm_hints(self) -> None:
        keys = tuple(self._panel_group.panel_keys)
        self._panel_fold_hint_mode_active = True
        self._hint_mode_active = True
        self._hint_mode_hints_for = "panels"
        self._panel_fold_hint_snapshot = keys
        self._panel_fold_hint_to_key = dict(enumerate(keys, start=1))
        self._panel_fold_key_to_hint = {
            key: hint for hint, key in self._panel_fold_hint_to_key.items()
        }

    def _agent_panel_index(self) -> Any:
        cached = self._panel_index_cache
        if cached is not None and cached[:2] == (
            self._agents,
            self._agent_panels_grouped,
        ):
            return cached[2]
        index = build_agent_panel_index(
            self._agents,
            dismissable_statuses=(),
            merge_tag_panels=self._agent_panels_grouped,
        )
        self._panel_index_cache = (self._agents, self._agent_panels_grouped, index)
        return index

    def _panel_keys_per_agent(self) -> list[PanelKey]:
        return panel_key_per_agent(
            self._agents,
            merge_tag_panels=self._agent_panels_grouped,
        )

    def _invalidate_agent_panel_cache(self) -> None:
        self._panel_index_cache = None
        self._nav_stops_cache = None

    def _snap_current_idx_to_focused_panel(
        self, keys_per_agent: list[PanelKey], focused_key: PanelKey
    ) -> None:
        self.current_idx = next(
            (idx for idx, key in enumerate(keys_per_agent) if key == focused_key),
            0,
        )

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        assert list_changed is True
        self.refresh_calls += 1
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            self._panel_group.focused_key,
            merge_tag_panels=self._agent_panels_grouped,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )

    def _refresh_agent_panel_titles(self) -> None:
        self.title_refresh_calls += 1

    def _persist_panel_fold_change(self, key: PanelKey, *, collapsed: bool) -> None:
        self.persistence_intents.append((key, collapsed))

    def _refocus_existing_hint_bar(self) -> bool:
        return False

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise LookupError

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)


def test_mixed_overlapping_submission_is_atomic_and_persists_each_panel() -> None:
    app = _StubApp()
    app.arm_hints()
    app._group_fold_registry.for_panel("alpha").collapse(("nested",))
    unread = {_agents()[0].identity}
    app._unread_completed_agent_ids = set(unread)

    app._process_panel_fold_hint_input("1-2 2 3")

    assert app._collapsed_panel_keys == {None, "alpha"}
    assert app._panel_group.panel_keys == ["beta", None, "alpha"]
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 1
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app.refresh_calls == 1
    assert app.persistence_intents == [
        (None, True),
        ("alpha", True),
        ("beta", False),
    ]
    assert app._group_fold_registry.for_panel("alpha").is_collapsed(("nested",))
    assert app._unread_completed_agent_ids == unread
    assert app.notifications[-1] == "Panels toggled: 1 expanded, 2 collapsed"


def test_toggling_only_nonfocused_panels_preserves_selection_context() -> None:
    app = _StubApp()
    app.arm_hints()
    prior = (app.current_idx, app.current_attempt_number, app._current_group_key)

    app._process_panel_fold_hint_input("1 3")

    assert app._collapsed_panel_keys == {None}
    assert app._panel_group.focused_key == "alpha"
    assert (
        app.current_idx,
        app.current_attempt_number,
        app._current_group_key,
    ) == prior
    assert app.refresh_calls == 1


def test_invalid_submission_keeps_mode_open_and_changes_nothing() -> None:
    app = _StubApp()
    app.arm_hints()
    before = set(app._collapsed_panel_keys)

    app._process_panel_fold_hint_input("1 nope 9 3-2")

    assert app._collapsed_panel_keys == before
    assert app._panel_fold_hint_mode_active is True
    assert app._hint_mode_active is True
    assert app.refresh_calls == 0
    assert "malformed: nope, 3-2" in app.notifications[-1]
    assert "unavailable: 9" in app.notifications[-1]


def test_stale_panel_membership_aborts_whole_submission() -> None:
    app = _StubApp()
    app.arm_hints()
    before = set(app._collapsed_panel_keys)
    app._agents = [agent for agent in app._agents if agent.tag != "beta"]
    app._invalidate_agent_panel_cache()

    app._process_panel_fold_hint_input("1")

    assert app._collapsed_panel_keys == before
    assert app._panel_fold_hint_mode_active is False
    assert app.refresh_calls == 0
    assert app.notifications[-1] == "Agent panels changed; retry panel selection"


def test_teardown_clears_transient_maps_and_activity_before_title_refresh() -> None:
    app = _StubApp()
    app.arm_hints()

    app._teardown_panel_fold_hint_mode()

    assert app._panel_fold_hint_mode_active is False
    assert app._panel_fold_hint_snapshot == ()
    assert app._panel_fold_hint_to_key == {}
    assert app._panel_fold_key_to_hint == {}
    assert app._hint_mode_active is False
    assert app._hint_mode_hints_for is None
    assert app.title_refresh_calls == 1


class _MountTarget:
    is_attached = True

    def __init__(self) -> None:
        self.bar: HintInputBar | None = None

    def mount(self, bar: HintInputBar) -> None:
        self.bar = bar


class _EntryApp(_StubApp):
    def __init__(self) -> None:
        super().__init__()
        self.mount_target = _MountTarget()

    def _refocus_existing_hint_bar(self) -> bool:
        return self.mount_target.bar is not None

    def query_one(self, selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#agent-detail-container":
            return self.mount_target
        if selector == "#hint-input-bar" and self.mount_target.bar is not None:
            return self.mount_target.bar
        raise LookupError


def test_entry_snapshots_visible_order_and_reentry_does_not_duplicate_bar() -> None:
    app = _EntryApp()

    app.action_toggle_selected_agent_panels()

    assert app._panel_fold_hint_snapshot == (None, "alpha", "beta")
    assert app._panel_fold_hint_to_key == {1: None, 2: "alpha", 3: "beta"}
    assert app._panel_fold_key_to_hint == {None: 1, "alpha": 2, "beta": 3}
    assert app.mount_target.bar is not None
    assert app.mount_target.bar.mode == "panels"
    assert app.title_refresh_calls == 1

    first_bar = app.mount_target.bar
    app.action_toggle_selected_agent_panels()
    assert app.mount_target.bar is first_bar
    assert app.title_refresh_calls == 1


def test_entry_explains_merged_and_single_panel_noops() -> None:
    merged = _StubApp(merged=True)
    merged.action_toggle_selected_agent_panels()
    assert merged.notifications == ["Panel selection requires split tag panels"]

    single = _StubApp(agents=[_agent("only", None)], focused_key=None)
    single._collapsed_panel_keys.clear()
    single._panel_group = AgentPanelGroup.from_agents(single._agents)
    single.action_toggle_selected_agent_panels()
    assert single.notifications == ["Need at least two panels to select"]
