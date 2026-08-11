"""Tribe-scoped single-key folding for Agents-tab fold owners."""

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
from sase.ace.tui.actions.navigation.jump_hints import build_jump_hint_maps
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.models.agent_panels import (
    AgentPanelGroup,
    PanelKey,
    panel_key_per_agent,
)
from sase.ace.tui.models.fold_state import FoldStateManager


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


class _FooterStub:
    def __init__(self) -> None:
        self.fold_hint_updates = 0
        self.fold_hint_collapse_only: bool | None = None

    def update_fold_hint_bindings(self, *, collapse_only: bool = False) -> None:
        self.fold_hint_updates += 1
        self.fold_hint_collapse_only = collapse_only


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
        self._expanded_panel_keys: set[PanelKey] = set()
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
        self._panel_fold_hint_to_target: dict[str, FoldHintTarget] = {}
        self._panel_fold_target_to_hint: dict[FoldHintTarget, str] = {}
        self._panel_fold_hint_pending_prefix = ""
        self._entry_jump_mode_active = False
        self.hint_bar_active = False
        self.refresh_calls = 0
        self.refilter_calls = 0
        self.affected_refreshes: list[set[PanelKey]] = []
        self.footer_refresh_calls = 0
        self.snap_group_focus_calls = 0
        self.group_persistence_intents: list[
            tuple[PanelKey, tuple[str, ...], bool]
        ] = []
        self.notifications: list[str] = []
        self.footer = _FooterStub()

    def arm_hints(self) -> None:
        targets = self._enumerate_panel_fold_hint_targets()
        hint_to_target, target_to_hint = build_jump_hint_maps(list(targets))
        self._panel_fold_hint_mode_active = True
        self._panel_fold_hint_snapshot = targets
        self._panel_fold_hint_to_target = hint_to_target
        self._panel_fold_target_to_hint = target_to_hint
        self._panel_fold_hint_pending_prefix = ""

    def hint_for(self, target: FoldHintTarget) -> str:
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

    def _refresh_affected_panel_widgets(self, affected_keys: set[PanelKey]) -> bool:
        self.affected_refreshes.append(set(affected_keys))
        return True

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        assert list_changed is True
        self.refresh_calls += 1
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            self._panel_group.focused_key,
            merge_tribe_panels=self._agent_panels_grouped,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )

    def _refilter_agents(self, *, refresh_content_index: bool) -> None:
        assert refresh_content_index is False
        self.refilter_calls += 1

    def _persist_group_fold_change(
        self,
        group_key: tuple[str, ...],
        *,
        collapsed: bool,
        panel_key: PanelKey,
    ) -> None:
        self.group_persistence_intents.append((panel_key, group_key, collapsed))

    def _hint_input_bar_active(self) -> bool:
        return self.hint_bar_active

    def _exit_entry_jump_mode(self) -> None:
        self._entry_jump_mode_active = False

    def _snap_focus_after_group_fold_change(self) -> None:
        self.snap_group_focus_calls += 1

    def query_one(self, selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#keybinding-footer":
            return self.footer
        raise LookupError

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refresh_calls += 1


class _EntryApp(AgentFoldingMixin, _StubApp):
    pass


def test_hint_enumeration_is_focused_panel_only_and_dedupes_workflow_owner() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    child = _agent(
        "step",
        "alpha",
        raw_suffix="step",
        parent_workflow="flow",
        parent_timestamp="flow",
        step_type="agent",
    )
    other = _agent("other-flow", "beta", workflow="other-flow")
    app = _StubApp(
        agents=[parent, child, other],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0), "step": (1, 0), "other-flow": (1, 0)},
    )

    targets = app._enumerate_panel_fold_hint_targets()

    assert targets
    assert all(target[0] != "panel" for target in targets)
    assert all(target[1] == "alpha" for target in targets)
    assert targets.count(("agent", "alpha", 0, "flow")) == 1
    assert not any(target[0] == "agent" and target[3] == "step" for target in targets)
    assert not any(
        target[0] == "agent" and target[3] == "other-flow" for target in targets
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


def test_collapsed_focused_panel_warns_without_arming() -> None:
    app = _EntryApp(focused_key="beta")

    assert app._enumerate_panel_fold_hint_targets() == ()
    app.action_expand_all_folds()

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "Selected tribe panel is collapsed"
    assert app.affected_refreshes == []


def test_expanded_focused_panel_without_fold_owners_warns(
    monkeypatch: Any,
) -> None:
    app = _EntryApp(collapsed_panels=set())
    monkeypatch.setattr(
        app,
        "_enumerate_panel_fold_hint_targets",
        lambda *, collapsible_only=False: (),
    )

    app.action_toggle_selected_agent_panels()

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "No folds in the selected tribe"


def test_one_key_toggles_one_group_fold_and_exits() -> None:
    app = _StubApp(collapsed_panels=set())
    app.arm_hints()
    group_target = next(
        target for target in app._panel_fold_hint_snapshot if target[0] == "group"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(group_target)) is True

    registry = app._group_fold_registry.for_panel("alpha")
    assert registry.is_collapsed(group_target[2])
    assert app.group_persistence_intents == [("alpha", group_target[2], True)]
    assert app.snap_group_focus_calls == 1
    assert app.refresh_calls == 1
    assert app.refilter_calls == 0
    assert app._panel_fold_hint_mode_active is False
    assert app.footer_refresh_calls == 1
    assert app.notifications[-1] == "Fold collapsed"


def test_escape_tears_down_without_mutating_fold_state() -> None:
    app = _StubApp(collapsed_panels=set())
    app.arm_hints()

    assert app._handle_panel_fold_hint_key("escape") is True

    assert app._panel_fold_hint_mode_active is False
    assert app._panel_fold_hint_snapshot == ()
    assert app._panel_fold_hint_to_target == {}
    assert app._panel_fold_target_to_hint == {}
    assert app._panel_fold_hint_pending_prefix == ""
    assert app.group_persistence_intents == []
    assert app.affected_refreshes == [{"alpha"}]
    assert app.footer_refresh_calls == 1


def test_unmapped_key_exits_without_mutating_fold_state() -> None:
    app = _StubApp(collapsed_panels=set())
    app.arm_hints()

    assert app._handle_panel_fold_hint_key("?") is True

    assert app._panel_fold_hint_mode_active is False
    assert app.group_persistence_intents == []
    assert app.refresh_calls == 0
    assert app.affected_refreshes == [{"alpha"}]


def test_two_character_hint_waits_for_prefix_then_completes() -> None:
    app = _StubApp(collapsed_panels=set())
    targets: list[FoldHintTarget] = [
        ("group", "alpha", (f"group-{index}",)) for index in range(63)
    ]
    hint_to_target, target_to_hint = build_jump_hint_maps(targets)
    app._panel_fold_hint_mode_active = True
    app._panel_fold_hint_to_target = hint_to_target
    app._panel_fold_target_to_hint = target_to_hint
    target = targets[-1]
    hint = target_to_hint[target]
    applied: list[FoldHintTarget] = []
    app._apply_panel_fold_hint_target = applied.append  # type: ignore[method-assign]

    assert len(hint) == 2
    assert app._handle_panel_fold_hint_key(hint[0]) is True
    assert app._panel_fold_hint_pending_prefix == hint[0]
    assert applied == []

    assert app._handle_panel_fold_hint_key(hint[1]) is True
    assert app._panel_fold_hint_pending_prefix == ""
    assert applied == [target]


def test_stale_visible_target_snapshot_aborts_toggle() -> None:
    app = _StubApp(collapsed_panels=set())
    app.arm_hints()
    target = app._panel_fold_hint_snapshot[0]
    hint = app.hint_for(target)
    app._agents.append(_agent("new-alpha-project", "alpha"))
    app._invalidate_agent_panel_cache()

    app._handle_panel_fold_hint_key(hint)

    assert app._panel_fold_hint_mode_active is False
    assert app.group_persistence_intents == []
    assert app.affected_refreshes == [{"alpha"}]
    assert app.notifications[-1] == "Visible folds changed; retry fold selection"


def test_entry_arms_fresh_focused_tribe_snapshot_without_hint_bar() -> None:
    app = _EntryApp(collapsed_panels=set())

    app.action_expand_all_folds()

    assert app._panel_fold_hint_snapshot == app._enumerate_panel_fold_hint_targets()
    assert app._panel_fold_hint_snapshot
    assert all(target[1] == "alpha" for target in app._panel_fold_hint_snapshot)
    assert app._hint_mode_active is False
    assert app._hint_mode_hints_for is None
    assert app.affected_refreshes == [{"alpha"}]
    assert app.footer.fold_hint_updates == 1

    previous_snapshot = app._panel_fold_hint_snapshot
    app.action_expand_all_folds()

    assert app._panel_fold_hint_snapshot == previous_snapshot
    assert app.affected_refreshes == [{"alpha"}, {"alpha"}, {"alpha"}]
    assert app.footer.fold_hint_updates == 2
    assert app.footer_refresh_calls == 1


def test_another_hint_bar_keeps_keyboard_ownership() -> None:
    app = _EntryApp(collapsed_panels=set())
    app.hint_bar_active = True

    app.action_toggle_selected_agent_panels()

    assert app._panel_fold_hint_mode_active is False
    assert app.affected_refreshes == []
    assert app.footer.fold_hint_updates == 0


def test_entry_exits_apostrophe_jump_mode_before_arming() -> None:
    app = _EntryApp(collapsed_panels=set())
    app._entry_jump_mode_active = True

    app.action_toggle_selected_agent_panels()

    assert app._entry_jump_mode_active is False
    assert app._panel_fold_hint_mode_active is True


def test_merged_and_single_panel_layouts_hint_only_in_panel_folds() -> None:
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
    assert all(target[0] != "panel" for target in single._panel_fold_hint_snapshot)


def test_display_maps_have_agent_and_banner_channels_only() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    other = _agent("other", "beta")
    app = _StubApp(
        agents=[parent, other],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0)},
    )
    app.arm_hints()

    agent_hints, banner_hints = app._panel_fold_hint_display_maps()

    assert agent_hints[0] == app.hint_for(("agent", "alpha", 0, "flow"))
    group_target = next(
        target
        for target in app._panel_fold_hint_snapshot
        if target[0] == "group" and target[1] == "alpha"
    )
    assert banner_hints[("banner", 0, group_target[2])] == app.hint_for(group_target)
