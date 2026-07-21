"""Hint-selected folding across visible Agents-tab fold owners."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.actions.agents._navigation_order import AgentNavigationOrderMixin
from sase.ace.tui.actions.agents._panel_hint_folding import (
    AgentPanelHintFoldingMixin,
    FoldHintTarget,
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
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager
from sase.ace.tui.widgets import HintInputBar


def _agent(name: str, tribe: str | None, **overrides: Any) -> Agent:
    fields: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": f"/r/{name}/project.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 7, 16, 12, 0, 0),
        "raw_suffix": name,
        "agent_name": name,
        "tribe": tribe,
    }
    fields.update(overrides)
    return Agent(**fields)


def _agents() -> list[Agent]:
    return [
        _agent("no_tribe", None),
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
        collapsed_panels: set[PanelKey] | None = None,
        fold_counts: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 1
        self.current_attempt_number: int | None = 7
        self._agents = list(agents if agents is not None else _agents())
        self._agent_panels_grouped = merged
        self._collapsed_panel_keys = set(
            collapsed_panels
            if collapsed_panels is not None
            else ({"beta"} if not merged else set())
        )
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tribe_panels=merged,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._grouping_mode = GroupingMode.STANDARD
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._fold_counts = dict(fold_counts or {})
        self._fold_manager = FoldStateManager()
        self._expanded_panel_focus = False
        self._current_group_key: tuple[str, ...] | None = ("kept",)
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self._panel_index_cache: tuple[Any, bool, Any] | None = None
        self._hint_mode_active = False
        self._hint_mode_hints_for: str | None = None
        self._panel_fold_hint_mode_active = False
        self._panel_fold_hint_snapshot: tuple[FoldHintTarget, ...] = ()
        self._panel_fold_hint_to_target: dict[int, FoldHintTarget] = {}
        self._panel_fold_target_to_hint: dict[FoldHintTarget, int] = {}
        self._entry_jump_mode_active = False
        self.refresh_calls = 0
        self.footer_refresh_calls = 0
        self.persistence_intents: list[tuple[PanelKey, bool]] = []
        self.group_persistence_intents: list[
            tuple[PanelKey, tuple[str, ...], bool]
        ] = []
        self.notifications: list[str] = []

    def arm_hints(self) -> None:
        targets = self._enumerate_panel_fold_hint_targets()
        self._panel_fold_hint_mode_active = True
        self._hint_mode_active = True
        self._hint_mode_hints_for = "folds"
        self._panel_fold_hint_snapshot = targets
        self._panel_fold_hint_to_target = dict(enumerate(targets, start=1))
        self._panel_fold_target_to_hint = {
            target: hint for hint, target in self._panel_fold_hint_to_target.items()
        }

    def hint_for(self, target: FoldHintTarget) -> int:
        return self._panel_fold_target_to_hint[target]

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
            merge_tribe_panels=self._agent_panels_grouped,
        )
        self._panel_index_cache = (self._agents, self._agent_panels_grouped, index)
        return index

    def _panel_keys_per_agent(self) -> list[PanelKey]:
        return panel_key_per_agent(
            self._agents,
            merge_tribe_panels=self._agent_panels_grouped,
        )

    def _invalidate_agent_panel_cache(self) -> None:
        self._panel_index_cache = None
        self._nav_stops_cache = None

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        assert list_changed is True
        self.refresh_calls += 1
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            self._panel_group.focused_key,
            merge_tribe_panels=self._agent_panels_grouped,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )

    def _persist_panel_fold_change(self, key: PanelKey, *, collapsed: bool) -> None:
        self.persistence_intents.append((key, collapsed))

    def _persist_group_fold_change(
        self,
        group_key: tuple[str, ...],
        *,
        collapsed: bool,
        panel_key: PanelKey,
    ) -> None:
        self.group_persistence_intents.append((panel_key, group_key, collapsed))

    def _refocus_existing_hint_bar(self) -> bool:
        return False

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise LookupError

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refresh_calls += 1


def test_hint_enumeration_is_visual_and_dedupes_workflow_fold_owner() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    child = _agent(
        "step",
        "alpha",
        raw_suffix="step",
        parent_workflow="flow",
        parent_timestamp="flow",
        step_type="agent",
    )
    other = _agent("other", "beta")
    app = _StubApp(
        agents=[parent, child, other],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0), "step": (1, 0)},
    )

    targets = app._enumerate_panel_fold_hint_targets()

    assert targets[0] == ("panel", "alpha")
    assert targets.count(("agent", "alpha", 0, "flow")) == 1
    assert not any(target[0] == "agent" and target[3] == "step" for target in targets)
    assert targets.index(("agent", "alpha", 0, "flow")) < targets.index(
        ("panel", "beta")
    )
    assert len(targets) == len(set(targets))


def test_hint_enumeration_includes_clan_and_family_fold_owners() -> None:
    clan = _agent(
        "crew",
        "alpha",
        raw_suffix=None,
        is_clan_container=True,
        agent_clan="crew",
    )
    family = _agent("family", "alpha", plan_chain_root=True)
    member = _agent(
        "family.member",
        "alpha",
        parent_timestamp="family",
    )
    family.followup_agents = [member]
    app = _StubApp(
        agents=[clan, family, member],
        collapsed_panels=set(),
        fold_counts={"family": (1, 0)},
    )

    targets = app._enumerate_panel_fold_hint_targets()

    assert ("agent", "alpha", 0, "clan:crew") in targets
    assert ("agent", "alpha", 1, "family") in targets


def test_mixed_panel_group_and_agent_submission_is_atomic() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    child = _agent(
        "step",
        "alpha",
        raw_suffix="step",
        parent_workflow="flow",
        parent_timestamp="flow",
        step_type="agent",
    )
    other = _agent("other", "beta")
    app = _StubApp(
        agents=[parent, child, other],
        collapsed_panels={"beta"},
        fold_counts={"flow": (1, 0)},
    )
    app.arm_hints()
    group_target = next(
        target
        for target in app._panel_fold_hint_snapshot
        if target[0] == "group" and target[1] == "alpha"
    )
    selected = [
        app.hint_for(("panel", "beta")),
        app.hint_for(group_target),
        app.hint_for(("agent", "alpha", 0, "flow")),
    ]

    app._process_panel_fold_hint_input(" ".join(str(hint) for hint in selected))

    assert app._collapsed_panel_keys == set()
    assert app._group_fold_registry.for_panel("alpha").is_collapsed(group_target[2])
    assert app._fold_manager.get("flow") == FoldLevel.EXPANDED
    assert app.refresh_calls == 1
    assert app.persistence_intents == [("beta", False)]
    assert app.group_persistence_intents == [("alpha", group_target[2], True)]
    assert app.notifications[-1] == "Folds toggled: 2 expanded, 1 collapsed"


def test_invalid_submission_keeps_mode_open_and_changes_nothing() -> None:
    app = _StubApp()
    app.arm_hints()
    before = set(app._collapsed_panel_keys)

    app._process_panel_fold_hint_input("1 nope 99 3-2")

    assert app._collapsed_panel_keys == before
    assert app._panel_fold_hint_mode_active is True
    assert app._hint_mode_active is True
    assert app.refresh_calls == 0
    assert "malformed: nope, 3-2" in app.notifications[-1]
    assert "unavailable: 99" in app.notifications[-1]


def test_stale_visible_target_snapshot_aborts_whole_submission() -> None:
    app = _StubApp()
    app.arm_hints()
    before = set(app._collapsed_panel_keys)
    first_hint = min(app._panel_fold_hint_to_target)
    app._agents = [agent for agent in app._agents if agent.tribe != "beta"]
    app._invalidate_agent_panel_cache()

    app._process_panel_fold_hint_input(str(first_hint))

    assert app._collapsed_panel_keys == before
    assert app._panel_fold_hint_mode_active is False
    assert app.refresh_calls == 1  # teardown removes every stale overlay
    assert app.notifications[-1] == "Visible folds changed; retry fold selection"


def test_teardown_clears_transient_maps_before_repaint() -> None:
    app = _StubApp()
    app.arm_hints()

    app._teardown_panel_fold_hint_mode()

    assert app._panel_fold_hint_mode_active is False
    assert app._panel_fold_hint_snapshot == ()
    assert app._panel_fold_hint_to_target == {}
    assert app._panel_fold_target_to_hint == {}
    assert app._hint_mode_active is False
    assert app._hint_mode_hints_for is None
    assert app.refresh_calls == 1


class _MountTarget:
    is_attached = True

    def __init__(self) -> None:
        self.bar: HintInputBar | None = None

    def mount(self, bar: HintInputBar) -> None:
        self.bar = bar


class _EntryApp(AgentFoldingMixin, _StubApp):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.mount_target = _MountTarget()

    def _refocus_existing_hint_bar(self) -> bool:
        return self.mount_target.bar is not None

    def query_one(self, selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#agent-detail-container":
            return self.mount_target
        if selector == "#hint-input-bar" and self.mount_target.bar is not None:
            return self.mount_target.bar
        raise LookupError


def test_entry_snapshots_all_visible_targets_and_reentry_reuses_bar() -> None:
    app = _EntryApp()

    app.action_expand_all_folds()

    assert app._panel_fold_hint_snapshot == app._enumerate_panel_fold_hint_targets()
    assert app._panel_fold_hint_snapshot[0] == ("panel", None)
    assert ("panel", "alpha") in app._panel_fold_hint_snapshot
    assert ("panel", "beta") in app._panel_fold_hint_snapshot
    assert app.mount_target.bar is not None
    assert app.mount_target.bar.mode == "panels"
    assert app.refresh_calls == 1
    assert app.footer_refresh_calls == 1

    first_bar = app.mount_target.bar
    app.action_expand_all_folds()
    assert app.mount_target.bar is first_bar
    assert app.refresh_calls == 1
    assert app.footer_refresh_calls == 1


def test_capital_l_does_not_expand_a_collapsed_focused_panel() -> None:
    app = _EntryApp(focused_key="beta")
    before = set(app._collapsed_panel_keys)

    app.action_expand_all_folds()

    assert app._panel_fold_hint_mode_active is True
    assert app._collapsed_panel_keys == before


def test_merged_and_single_panel_layouts_still_hint_in_panel_folds() -> None:
    merged = _EntryApp(merged=True)
    merged.action_toggle_selected_agent_panels()
    assert merged._panel_fold_hint_mode_active is True
    assert all(target[0] != "panel" for target in merged._panel_fold_hint_snapshot)

    single = _EntryApp(
        agents=[_agent("only", None)],
        focused_key=None,
        collapsed_panels=set(),
    )
    single.action_toggle_selected_agent_panels()
    assert single._panel_fold_hint_mode_active is True
    assert ("panel", None) in single._panel_fold_hint_snapshot


def test_display_maps_reuse_panel_banner_and_agent_channels() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    other = _agent("other", "beta")
    app = _StubApp(
        agents=[parent, other],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0)},
    )
    app.arm_hints()

    agent_hints, banner_hints, panel_hints = app._panel_fold_hint_display_maps()

    assert agent_hints[0] == str(app.hint_for(("agent", "alpha", 0, "flow")))
    assert panel_hints[("panel", "alpha")] == str(app.hint_for(("panel", "alpha")))
    group_target = next(
        target
        for target in app._panel_fold_hint_snapshot
        if target[0] == "group" and target[1] == "alpha"
    )
    assert banner_hints[("banner", 0, group_target[2])] == str(
        app.hint_for(group_target)
    )
