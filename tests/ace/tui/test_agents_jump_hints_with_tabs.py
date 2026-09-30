"""Jump hints stay truthful when agent tabs are on."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from rich.text import Text

from sase.ace.tui.actions.agents._fleet import AgentFleetMixin
from sase.ace.tui.actions.navigation._entry_jump_dispatch import (
    EntryJumpDispatchMixin,
)
from sase.ace.tui.actions.agents._panel_hint_folding import AgentPanelHintFoldingMixin
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.widgets.agent_list import AgentList
from sase.core.agent_tab import AgentTabKey
from tests.ace.tui._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _widget_sel,
)
from tests.ace.tui.fleet_fixture import fleet_config


class _HintFleetApp(AgentFleetMixin):
    """Minimal fleet host with hint-mode flags."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_local_with_children: list[Agent] = []
        self._agents_local_visible: list[Agent] = []
        self._agents_fleet_rows: list[Agent] = []
        self._agents_fleet_focus_rows: list[Agent] = []
        self._agents_fleet_applied_projection_signature = None
        self._agents_fleet_projection = FleetRowsProjection()
        self._agents_fleet_async_tasks: set[Any] = set()
        self._agents_fleet_refresh_generation = 1
        self._agents_fleet_hint_deferred_apply = None
        self._agents_fleet_loading = True
        self._agents_fleet_available = False
        self._agents_fleet_last_error = None
        self._agents_refresh_active_source = "unknown"
        self._entry_jump_mode_active = False
        self._panel_fold_hint_mode_active = False
        self._nav_gate = NavigationGate()
        self.header_updates = 0
        self.reproject_sources: list[str] = []
        self.timers: list[tuple[float, Any]] = []

    def _update_agents_header(self) -> None:
        self.header_updates += 1

    def _finalize_agent_list(self, *_args: object, **_kwargs: object) -> None:
        self.reproject_sources.append(self._agents_refresh_active_source)
        self._agents = list(self._agents_with_children)

    def _announce_remote_attention(self, _projection: FleetRowsProjection) -> None:
        pass

    def notify(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_timer(self, delay: float, callback: Any) -> None:
        self.timers.append((delay, callback))


def _remote_projection() -> FleetRowsProjection:
    row = Agent(
        Agent.__dataclass_fields__["agent_type"].type.RUNNING
        if False
        else __import__(
            "sase.ace.tui.models.agent", fromlist=["AgentType"]
        ).AgentType.RUNNING,
        "remote-work",
        "/fleet/apollo/project.yml",
        "RUNNING",
        None,
        agent_name="remote-work",
        fleet_origin_alias="apollo",
        fleet_logical_key="apollo:remote-work",
    )
    return FleetRowsProjection(fleet_rows=(row,), configured_host_count=1)


def test_fleet_projection_defers_while_jump_mode_active() -> None:
    app = _HintFleetApp()
    app._entry_jump_mode_active = True
    projection = _remote_projection()

    deferred = app._defer_fleet_projection_apply_if_navigating(
        projection,
        config=fleet_config(),
        generation=1,
        source="fleet_refresh",
    )

    assert deferred is True
    assert app._agents == []
    assert app._agents_fleet_hint_deferred_apply is not None
    assert app.timers == []

    app._entry_jump_mode_active = False
    app._flush_hint_deferred_fleet_projection()

    assert app._agents_fleet_hint_deferred_apply is None
    assert [row.cl_name for row in app._agents] == ["remote-work"]
    assert app.reproject_sources == ["fleet_refresh"]


def test_fleet_hint_deferral_keeps_only_newest_apply() -> None:
    app = _HintFleetApp()
    app._entry_jump_mode_active = True
    first = _remote_projection()
    app._defer_fleet_projection_apply_if_navigating(
        first, config=fleet_config(), generation=1, source="fleet_refresh"
    )
    second = FleetRowsProjection(fleet_rows=(), configured_host_count=1)
    app._defer_fleet_projection_apply_if_navigating(
        second, config=fleet_config(), generation=1, source="fleet_refresh"
    )

    stored = app._agents_fleet_hint_deferred_apply
    assert stored is not None
    assert stored[0] is second


class _JumpTabsApp(EntryJumpDispatchMixin, AgentPanelHintFoldingMixin, _DisplayDiffApp):
    """Display harness with tab stubs and dispatch support."""

    def __init__(self, agents: list[Agent], monkeypatch: Any) -> None:
        super().__init__(agents, monkeypatch)
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_hint_to_tab: dict[Any, str] = {}
        self._entry_jump_tab_to_hint: dict[Any, str] = {}
        self._entry_jump_allocation_token: object | None = None
        self._entry_jump_agent_identity_by_hint: dict[str, Any] = {}
        self._entry_jump_banner_hint_to_panel_key: dict[str, Any] = {}
        self._entry_jump_hint_to_panel: dict[Any, str] = {}
        self._entry_jump_panel_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_banner: dict[Any, str] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_target: dict[str, object] = {}
        self._entry_jump_pending_prefix = ""
        self._panel_fold_target_to_hint: dict[Any, str] = {}
        self._panel_fold_hint_scope = "tribe"
        self._tab_entries: tuple[Any, ...] = ()
        self._strip_visible = False
        self._agents_fleet_hint_deferred_apply = None
        self.footer_refreshes = 0
        self.flushed = 0
        self.switched_tabs: list[AgentTabKey] = []

    def _agent_tab_catalog_view(self) -> tuple[Any, ...]:
        return self._tab_entries

    def _agent_tab_strip_visible(self) -> bool:
        return self._strip_visible

    def _switch_agents_tab(self, key: AgentTabKey, *, reason: str = "") -> bool:
        del reason
        self.switched_tabs.append(key)
        return True

    def _refresh_agents_jump_hint_display(self) -> None:
        self.full_rebuilds += 1

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refreshes += 1

    def _flush_hint_deferred_fleet_projection(self) -> None:
        self.flushed += 1

    def _get_selected_agent(self) -> Agent | None:
        return None


def _tab_entry(key: AgentTabKey, label: str) -> Any:
    return SimpleNamespace(key=key, label=label)


def _agents_three() -> list[Agent]:
    return [
        _agent("alpha", tribe="apple", suffix="a1"),
        _agent("beta", tribe="apple", suffix="b1", status="DONE"),
        _agent("gamma", tribe="pear", suffix="g1"),
    ]


def _rows(widget: AgentList) -> list[str]:
    return [
        str(widget.get_option_at_index(i).prompt) for i in range(widget.option_count)
    ]


def _title(widget: AgentList) -> str:
    return Text.from_markup(str(widget.border_title)).plain


def test_painted_labels_equal_dispatch_after_roster_replace(
    monkeypatch: Any,
) -> None:
    app = _JumpTabsApp(_agents_three(), monkeypatch)
    app._tab_entries = ()
    app._strip_visible = False

    assert app._prepare_agents_jump_maps()
    assert app._entry_jump_mode_active is False
    app._entry_jump_mode_active = True
    before = dict(app._entry_jump_hint_to_target)

    assert before, "expected agent/panel hints without tabs"
    new_agent = _agent("aardvark", tribe="apple", suffix="z9")
    app._agents = [new_agent, *app._agents]
    app._ensure_agents_jump_maps_current()

    app._refresh_affected_panel_widgets(set(app._panel_group.panel_keys))
    painted: dict[str, Any] = {}
    for widget in app._container.children:
        if not isinstance(widget, AgentList):
            continue
        for row in _rows(widget):
            for hint in app._entry_jump_agent_identity_by_hint:
                if f"[{hint}]" in row:
                    painted[hint] = row
    assert painted, "expected painted agent hints after re-derive"
    for hint, identity in app._entry_jump_agent_identity_by_hint.items():
        assert hint in painted, f"hint {hint} not painted"
        resolved = app._resolve_agents_jump_agent_target(
            next(idx for idx, h in app._entry_jump_index_to_hint.items() if h == hint)
        )
        assert resolved is not None
        assert app._agents[resolved].identity == identity


def test_tab_chips_gain_labels_once_catalog_grows(monkeypatch: Any) -> None:
    app = _JumpTabsApp(_agents_three(), monkeypatch)
    default_key = AgentTabKey.default()
    app._tab_entries = (_tab_entry(default_key, "local"),)
    app._strip_visible = False

    assert app._prepare_agents_jump_maps()
    app._entry_jump_mode_active = True
    assert app._entry_jump_hint_to_tab == {}

    machine_key = AgentTabKey.machine("install-apollo")
    app._tab_entries = (
        _tab_entry(default_key, "local"),
        _tab_entry(machine_key, "apollo"),
    )
    app._strip_visible = True
    app._ensure_agents_jump_maps_current()

    assert set(app._entry_jump_hint_to_tab) != set()
    assert set(app._agent_tab_jump_hints) == {default_key, machine_key}
    tab_hints = sorted(app._entry_jump_hint_to_tab)
    assert len(tab_hints) == 2


def test_row_patch_keeps_title_chip(monkeypatch: Any) -> None:
    app = _JumpTabsApp(_agents_three(), monkeypatch)
    app._tab_entries = ()
    app._strip_visible = False
    assert app._prepare_agents_jump_maps()
    app._entry_jump_mode_active = True
    app._refresh_affected_panel_widgets(set(app._panel_group.panel_keys))

    pear_widget = app._widgets[_widget_sel("pear")]
    assert "[" in _title(pear_widget), _title(pear_widget)
    target = next(a for a in app._agents if a.tribe == "pear")

    assert app._try_patch_agent_row(target)

    assert "[" in _title(pear_widget), _title(pear_widget)


def test_exit_jump_mode_refreshes_footer_and_flushes(monkeypatch: Any) -> None:
    app = _JumpTabsApp(_agents_three(), monkeypatch)
    app._tab_entries = ()
    app._strip_visible = False
    assert app._prepare_agents_jump_maps()
    app._entry_jump_mode_active = True

    app._exit_entry_jump_mode()

    assert app._entry_jump_mode_active is False
    assert app.footer_refreshes >= 1
    assert app.flushed == 1
    assert app._entry_jump_agent_identity_by_hint == {}
    assert app._entry_jump_allocation_token is None


def test_identity_safe_dispatch_selects_original_identity(
    monkeypatch: Any,
) -> None:
    app = _JumpTabsApp(_agents_three(), monkeypatch)
    app._tab_entries = ()
    app._strip_visible = False
    assert app._prepare_agents_jump_maps()
    app._entry_jump_mode_active = True
    hint_for_first = app._entry_jump_index_to_hint[0]
    identity = app._entry_jump_agent_identity_by_hint[hint_for_first]

    reordered = [app._agents[1], app._agents[2], app._agents[0]]
    app._agents = list(reordered)

    resolved = app._resolve_agents_jump_agent_target(0)
    assert resolved is not None
    assert app._agents[resolved].identity == identity
    assert resolved == 2

    gone_identity = ("gone-type", "gone", None)
    app._entry_jump_agent_identity_by_hint[hint_for_first] = gone_identity
    assert app._resolve_agents_jump_agent_target(0) is None
