"""Tab switching, persistence, keys, strip, and perf tests (sase-1bc.6.1.3).

Covers the synchronous switch with per-tab memory, startup selection
order, the emptied-tab latch, the machine-disappearance fallback, the
off-thread persistence round-trip, key cycling/pick gating, and the
minimal strip refresh — in both flag states.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing.ace_page import _extract_state
from sase.ace.tui.actions.agents._agent_tabs import (
    AgentTabsMixin,
    strip_visible_for_owner,
)
from sase.ace.tui.actions.agents._agent_tabs_catalog import catalog_view_for_owner
from sase.ace.tui.actions.agents._agent_tabs_switch import (
    _key_for_strip_id,
    _strip_id_for_key,
)
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent
from sase.ace.tui.models.agent_tab_index import (
    build_agent_tab_index,
    _index_cache,
)
from sase.ace.tui.models.agent_tab_persistence import (
    load_active_agent_tab,
    save_active_agent_tab,
)
from sase.core.agent_tab import AgentTabCatalogEntry, DEFAULT_AGENT_TAB_KEY, AgentTabKey
from sase.feature_flags import override_flags


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Any:
    _index_cache.clear()
    yield
    _index_cache.clear()


def _view(token: Any = ("switch-test",)) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=False,
        machine_order=(),
        pinned_by_alias={},
        named_order={},
        token=token,
    )


def _machine_view(
    *,
    machine_mode: bool = True,
    machine_order: tuple[tuple[str, str], ...] = (("machine-id", "apollo"),),
) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=machine_mode,
        machine_order=machine_order,
        pinned_by_alias={
            alias: installation_id for installation_id, alias in machine_order
        },
        named_order={},
        token=("switch-machine-test", machine_mode, machine_order),
    )


def _row(
    suffix: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
    start_time: datetime | None = None,
    parent_timestamp: str | None = None,
    tribe: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status=status,
        start_time=start_time,
        raw_suffix=suffix,
        agent_tab=tab,
        parent_timestamp=parent_timestamp,
        tribe=tribe,
    )


class _TabOwner(AgentTabsMixin):
    """Minimal owner driving the switch mixin without the full app."""

    def __init__(self, rows: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(rows)
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._jk_perf = None
        self.notices: list[str] = []
        self._ensure_agent_tabs_state()

    def _rescope_agents_to_active_tab(self) -> None:
        self._agents = _scoped_agents_for_owner(self, list(self._agents_query_result))

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        """Fail closed: no list panel or strip is mounted in unit tests."""
        raise LookupError("no widget")

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Collect toasts instead of showing them."""
        self.notices.append(str(message))

    def reindex(self, rows: list[Agent]) -> None:
        """Install *rows* as the roster and rebuild the tab index."""
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agent_tab_index = build_agent_tab_index(list(rows), _view())


_SASE = AgentTabKey.named("sase")


def _two_tab_owner() -> _TabOwner:
    owner = _TabOwner([_row("a"), _row("b", tab="sase"), _row("c", tab="sase")])
    owner.reindex(owner._agents_with_children)
    return owner


def test_switch_noop_flag_off() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=False):
        assert owner._switch_agents_tab(_SASE, reason="cycle") is False
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert owner._agent_tab_strip_visible() is False


def test_switch_noop_same_key() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert owner._switch_agents_tab(DEFAULT_AGENT_TAB_KEY) is False


def test_cycle_wraps_across_tabs() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert owner._agent_tab_strip_visible() is True
        owner._cycle_agents_tab(1)
        assert owner._active_agent_tab == _SASE
        assert [r.raw_suffix for r in owner._agents] == ["b", "c"]
        owner._cycle_agents_tab(1)
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert [r.raw_suffix for r in owner._agents] == ["a"]
        owner._cycle_agents_tab(-1)
        assert owner._active_agent_tab == _SASE


def test_cycle_noop_when_strip_hidden() -> None:
    owner = _TabOwner([_row("a")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        assert owner._agent_tab_strip_visible() is False
        owner._cycle_agents_tab(1)
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_per_tab_selection_restore_by_identity() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        owner._agents = [owner._agents_with_children[0]]
        owner.current_idx = 0
        owner._switch_agents_tab(_SASE, reason="cycle")
        assert owner.current_idx == 0
        assert owner._agents[owner.current_idx].raw_suffix == "b"
        # Select the second sase row, switch away, and switch back.
        owner.current_idx = 1
        owner._agents_last_idx = 1
        owner._agents_last_identity = owner._agents[1].identity
        owner._switch_agents_tab(DEFAULT_AGENT_TAB_KEY, reason="cycle")
        assert owner._agents[owner.current_idx].raw_suffix == "a"
        owner._switch_agents_tab(_SASE, reason="cycle")
        assert owner._agents[owner.current_idx].raw_suffix == "c"


def test_first_visit_starts_at_row_zero_after_multirow_source() -> None:
    owner = _TabOwner(
        [_row("main-0"), _row("main-1"), _row("main-2"), _row("sase-0", tab="sase")]
    )
    owner.reindex(owner._agents_with_children)
    owner.current_idx = 2
    with override_flags(agent_tabs=True):
        owner._switch_agents_tab(_SASE, reason="cycle")
        assert owner.current_idx == 0
        assert [row.raw_suffix for row in owner._agents] == ["sase-0"]


class _PanelTabOwner(_TabOwner):
    """Tab owner with tribe panels and a real-shaped panel-group sync."""

    def __init__(self, rows: list[Agent]) -> None:
        super().__init__(rows)
        self._expanded_panel_focus = False
        self._agent_panels_grouped = False
        self._collapsed_panel_keys: set[Any] = set()
        self._panel_group = AgentPanelGroup.from_agents(self._agents)

    def _panel_keys_per_agent(self) -> list[Any]:
        return panel_key_per_agent(
            self._agents, merge_tribe_panels=self._agent_panels_grouped
        )

    def _sync_panel_group(self) -> set[Any]:
        prev_focused = self._panel_group.focused_key
        self._panel_group = AgentPanelGroup.from_agents(self._agents, prev_focused)
        known = set(self._panel_group.panel_keys)
        if prev_focused not in known or not self._panel_group.panel_keys:
            self._expanded_panel_focus = False
        return set()

    def _rescope_agents_to_active_tab(self) -> None:
        self._agents = _scoped_agents_for_owner(self, list(self._agents_query_result))
        self._sync_panel_group()


def test_first_visit_does_not_inherit_source_tab_panel_focus() -> None:
    """A never-visited tab selects row 0's panel, not the source tab's focus."""
    rows = [
        _row("a0", tribe="alpha"),
        _row("a1", tribe="beta"),
        _row("b0", tab="sase", tribe="alpha"),
        _row("b1", tab="sase", tribe="beta"),
    ]
    owner = _PanelTabOwner(rows)
    owner.reindex(rows)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(owner, list(rows))
        owner._panel_group = AgentPanelGroup.from_agents(owner._agents)
        owner.current_idx = 1
        owner._agents_last_idx = 1
        owner._agents_last_identity = owner._agents[1].identity
        owner._panel_group.focused_idx = owner._panel_group.panel_keys.index("beta")
        owner._expanded_panel_focus = True

        owner._switch_agents_tab(_SASE, reason="cycle")

        assert owner.current_idx == 0
        assert owner._agents[0].raw_suffix == "b0"
        row_zero_panel = owner._panel_keys_per_agent()[0]
        assert owner._panel_group.focused_key == row_zero_panel
        assert owner._expanded_panel_focus is False


def test_selection_fallback_uses_target_tabs_remembered_row_index() -> None:
    owner = _TabOwner(
        [
            _row("main-0"),
            _row("main-1"),
            _row("sase-0", tab="sase"),
            _row("sase-1", tab="sase"),
            _row("sase-2", tab="sase"),
        ]
    )
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._switch_agents_tab(_SASE, reason="cycle")
        owner.current_idx = 2
        owner._agents_last_idx = 2
        owner._agents_last_identity = owner._agents[2].identity
        owner._switch_agents_tab(DEFAULT_AGENT_TAB_KEY, reason="cycle")
        assert owner.current_idx == 0

        remaining = [
            row for row in owner._agents_with_children if row.raw_suffix != "sase-2"
        ]
        owner.reindex(remaining)
        owner._switch_agents_tab(_SASE, reason="cycle")
        assert owner.current_idx == 1
        assert owner._agents[owner.current_idx].raw_suffix == "sase-1"


def test_restore_remembers_focused_panel_and_scroll_anchor() -> None:
    owner = _two_tab_owner()
    owner._panel_group = SimpleNamespace(panel_keys=["main", "sase"], focused_idx=0)
    owner._agent_tab_memory[_SASE] = (None, 0, "sase", 17)
    scroll = SimpleNamespace(scroll_y=0)

    def query_one(selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#agent-list-panel":
            return scroll
        raise LookupError("no widget")

    owner.query_one = query_one  # type: ignore[method-assign]
    with override_flags(agent_tabs=True):
        owner._switch_agents_tab(_SASE, reason="cycle")
        assert owner._panel_group.focused_idx == 1
        assert scroll.scroll_y == 17


def test_selection_falls_back_to_nearest_row() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        owner._switch_agents_tab(_SASE, reason="cycle")
        owner.current_idx = 1
        owner._agents_last_idx = 1
        owner._agents_last_identity = owner._agents[1].identity
        owner._switch_agents_tab(DEFAULT_AGENT_TAB_KEY, reason="cycle")
        # Drop the remembered sase row, then switch back: the cursor clamps
        # to the nearest surviving row instead of stranding.
        owner._agents_with_children = [
            r for r in owner._agents_with_children if r.raw_suffix in ("a", "b")
        ]
        owner._agents_query_result = list(owner._agents_with_children)
        owner._agent_tab_index = build_agent_tab_index(
            list(owner._agents_with_children), _view()
        )
        owner._switch_agents_tab(_SASE, reason="cycle")
        assert [r.raw_suffix for r in owner._agents] == ["b"]
        assert owner.current_idx == 0


def test_startup_selection_prefers_persisted() -> None:
    owner = _two_tab_owner()
    owner._agent_tab_loaded_key = _SASE
    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is True
        assert owner._active_agent_tab == _SASE


def test_startup_selection_defaults_to_main() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is False
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_startup_selection_attention_tab() -> None:
    owner = _TabOwner([_row("b", tab="sase", status="FAILED")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is True
        assert owner._active_agent_tab == _SASE


def test_empty_first_catalog_does_not_consume_startup_selection() -> None:
    owner = _TabOwner([])
    owner._agent_tab_index = build_agent_tab_index([], _view())
    owner._agent_tab_loaded_key = _SASE
    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is False
        assert owner._agent_tabs_reconciled_once is False

        owner.reindex([_row("main"), _row("sase", tab="sase")])
        assert owner._reconcile_active_agent_tab() is True
        assert owner._active_agent_tab == _SASE


def test_startup_selection_does_not_override_an_early_user_switch() -> None:
    owner = _two_tab_owner()
    owner._agent_tabs_user_switched = True
    owner._agent_tab_loaded_key = _SASE
    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is False
        assert owner._agent_tabs_reconciled_once is True
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_attention_startup_uses_newest_attention_root_only() -> None:
    owner = _TabOwner(
        [
            _row(
                "sase-root",
                tab="sase",
                status="RUNNING",
                start_time=datetime(2026, 1, 1),
            ),
            _row(
                "sase-child",
                tab="sase",
                status="FAILED",
                start_time=datetime(2026, 3, 1),
                parent_timestamp="sase-root",
            ),
            _row(
                "blog-root",
                tab="blog",
                status="FAILED",
                start_time=datetime(2026, 2, 1),
            ),
        ]
    )
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is True
        assert owner._active_agent_tab == AgentTabKey.named("blog")


def test_latch_keeps_emptied_tab() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        owner._agent_tabs_reconciled_once = True
        owner._agent_tab_prev_catalog_keys = (
            DEFAULT_AGENT_TAB_KEY,
            _SASE,
        )
        owner._active_agent_tab = _SASE
        # The sase roots vanish; the latch keeps sase selected and the
        # strip shows it with count 0.
        owner.reindex([_row("a")])
        assert owner._reconcile_active_agent_tab() is False
        assert owner._active_agent_tab == _SASE
        view = catalog_view_for_owner(owner)
        assert [(e.key, e.root_count) for e in view] == [
            (DEFAULT_AGENT_TAB_KEY, 1),
            (_SASE, 0),
        ]
        assert strip_visible_for_owner(owner) is True


def test_ace_page_state_includes_latched_catalog_entry() -> None:
    owner = SimpleNamespace(
        current_tab="agents",
        current_artifacts_subtab="",
        current_files_subtab="",
        current_idx=0,
        patches=[],
        query_string="",
        canonical_query_string="",
        marked_indices=set(),
        screen_stack=[],
        hide_reverted=False,
        hooks_collapsed=SimpleNamespace(value=False),
        commits_collapsed=SimpleNamespace(value=False),
        mentors_collapsed=SimpleNamespace(value=False),
        deltas_collapsed=SimpleNamespace(value=False),
        _agents=[],
        _agents_last_idx=0,
        _active_agent_tab=_SASE,
        _agent_tab_index=SimpleNamespace(
            catalog=(AgentTabCatalogEntry(DEFAULT_AGENT_TAB_KEY, "default", "main", 1),)
        ),
        _agent_tab_latched_key=_SASE,
        _agent_tab_known_labels={_SASE: "sase"},
    )
    owner._agent_tab_catalog_view = lambda: catalog_view_for_owner(owner)

    assert _extract_state(owner)["agent_tabs"] == ["main", "sase"]


def test_machine_tab_latches_when_roots_disappear_and_clears_on_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.agent_tabs_settings as settings

    machine = AgentTabKey.machine("machine-id")
    owner = _TabOwner([_row("main")])
    owner.reindex(owner._agents_with_children)
    owner._agent_tabs_reconciled_once = True
    owner._agent_tab_prev_catalog_keys = (DEFAULT_AGENT_TAB_KEY, machine)
    owner._active_agent_tab = machine
    owner._agent_tab_known_labels[machine] = "\u2328 apollo"
    monkeypatch.setattr(settings, "agent_tabs_view_config", _machine_view)

    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is False
        assert owner._active_agent_tab == machine
        assert owner._agent_tab_latched_key == machine
        assert [
            (entry.key, entry.label, entry.root_count)
            for entry in owner._agent_tab_catalog_view()
        ][-1] == (
            machine,
            "\u2328 apollo",
            0,
        )

        assert owner._switch_agents_tab(DEFAULT_AGENT_TAB_KEY, reason="cycle") is True
        assert owner._agent_tab_latched_key is None


def test_machine_fallback_toasts_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.agent_tabs_settings as settings

    machine = AgentTabKey.machine("dead-id")
    owner = _TabOwner([_row("a")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agent_tabs_reconciled_once = True
        owner._agent_tab_prev_catalog_keys = (machine,)
        owner._active_agent_tab = machine
        owner._agent_tab_known_labels[machine] = "\u2328 apollo"
        monkeypatch.setattr(
            settings,
            "agent_tabs_view_config",
            lambda: _machine_view(
                machine_mode=False,
                machine_order=(("dead-id", "apollo"),),
            ),
        )
        assert owner._reconcile_active_agent_tab() is True
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert owner.notices == ["agent tab \u2328 apollo is gone; showing main"]


def test_machine_fallback_uses_configured_alias_when_label_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.agent_tabs_settings as settings

    machine = AgentTabKey.machine("dead-id")
    owner = _TabOwner([_row("a")])
    owner.reindex(owner._agents_with_children)
    owner._agent_tabs_reconciled_once = True
    owner._agent_tab_prev_catalog_keys = (machine,)
    owner._active_agent_tab = machine
    monkeypatch.setattr(
        settings,
        "agent_tabs_view_config",
        lambda: _machine_view(
            machine_mode=False,
            machine_order=(("dead-id", "apollo"),),
        ),
    )

    with override_flags(agent_tabs=True):
        assert owner._reconcile_active_agent_tab() is True
        assert owner.notices == ["agent tab \u2328 apollo is gone; showing main"]


def test_strip_click_switches_and_ignores_unknown() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        owner._on_agents_tab_strip_clicked("named:sase")
        assert owner._active_agent_tab == _SASE
        owner._on_agents_tab_strip_clicked("named:nope")
        assert owner._active_agent_tab == _SASE


def test_strip_id_round_trip() -> None:
    assert _strip_id_for_key(DEFAULT_AGENT_TAB_KEY) == "default"
    assert _strip_id_for_key(_SASE) == "named:sase"
    assert _strip_id_for_key(AgentTabKey.machine("id-1")) == "machine:id-1"
    assert (
        _strip_id_for_key(AgentTabKey.unresolved_machine("apollo"))
        == "unresolved:apollo"
    )
    entries = catalog_view_for_owner(_two_tab_owner())
    assert _key_for_strip_id("named:sase", entries) == _SASE
    assert _key_for_strip_id("bogus", entries) is None


def test_switch_defers_persistence_off_thread() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert owner._switch_agents_tab(_SASE, reason="cycle") is True
        # The switch schedules a coalesced save but performs no I/O: with
        # no running loop the single writer never starts here.
        assert owner._agent_tab_save_pending == _SASE
        assert owner._agent_tab_save_task is None


def test_persistence_round_trip(tmp_path: Any) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "tab_state.json"
    save_active_agent_tab(_SASE, path)
    assert load_active_agent_tab(path) == _SASE
    save_active_agent_tab(DEFAULT_AGENT_TAB_KEY, path)
    assert load_active_agent_tab(path) == DEFAULT_AGENT_TAB_KEY
    machine = AgentTabKey.machine("id-9")
    save_active_agent_tab(machine, path)
    assert load_active_agent_tab(path) == machine
    # Unresolved keys are never persisted.
    missing = Path(str(tmp_path)) / "missing.json"
    save_active_agent_tab(AgentTabKey.unresolved_machine("apollo"), missing)
    assert not missing.exists()
    assert load_active_agent_tab(missing) is None
    # Malformed payloads fail open.
    bad = Path(str(tmp_path)) / "bad.json"
    bad.write_text('{"active": "named:unterminated', encoding="utf-8")
    assert load_active_agent_tab(bad) is None
    bad.write_text('{"schema_version": 999, "active": "default"}', encoding="utf-8")
    assert load_active_agent_tab(bad) is None
    bad.write_text('{"schema_version": 1, "active": "bogus"}', encoding="utf-8")
    assert load_active_agent_tab(bad) is None


def test_strip_refresh_gated_by_signature() -> None:
    owner = _two_tab_owner()
    calls: list[tuple[Any, Any]] = []

    class _Strip:
        def set_tabs(self, tabs: Any, *, active_tab: Any = None) -> None:
            calls.append((tuple(tabs), active_tab))

    owner.query_one = lambda *a, **k: _Strip()  # type: ignore[method-assign]
    with override_flags(agent_tabs=True):
        owner._refresh_agent_tab_strip()
        owner._refresh_agent_tab_strip()
        assert len(calls) == 1
        tabs, active = calls[0]
        assert [t.label for t in tabs] == ["main", "sase"]
        assert active == "default"
        owner._switch_agents_tab(_SASE, reason="cycle")
        assert len(calls) == 2
        assert calls[1][1] == "named:sase"


def test_switch_records_tab_switch_perf_sample() -> None:
    """The switch follows the JK key-to-paint pattern for perf JSONL."""

    class _Timer:
        def __init__(self) -> None:
            self.events: list[str] = []

        def mark_model_updated(self) -> None:
            self.events.append("model_updated")

        def mark_painted(self) -> None:
            self.events.append("painted")

    owner = _two_tab_owner()
    timer = _Timer()
    begun: list[tuple[str, str]] = []
    deferred: list[Any] = []
    owner._jk_perf_begin = lambda action: begun.append((action, "agents"))  # type: ignore[method-assign]
    owner._jk_perf = timer  # type: ignore[assignment]
    owner.call_after_refresh = deferred.append  # type: ignore[method-assign]
    with override_flags(agent_tabs=True):
        assert owner._switch_agents_tab(_SASE, reason="cycle") is True
        assert begun == [("agents_tab_switch", "agents")]
        assert timer.events == ["model_updated"]
        assert len(deferred) == 1


def test_pick_gating_needs_two_tabs() -> None:
    from sase.ace.tui._app_action_availability import check_app_action

    single = _TabOwner([_row("a")])
    single.reindex(single._agents_with_children)
    single.screen = None  # type: ignore[attr-defined]
    single._screen_stack = ("home",)

    def _no_prompt() -> bool:
        return False

    single._prompt_input_active = _no_prompt  # type: ignore[method-assign]
    two = _two_tab_owner()
    two.screen = None  # type: ignore[attr-defined]
    two._screen_stack = ("home",)
    two._prompt_input_active = _no_prompt  # type: ignore[method-assign]
    with override_flags(agent_tabs=True):
        assert (
            check_app_action(single, "pick_agents_tab", (), lambda _a, _p: None)
            is False
        )
        assert (
            check_app_action(two, "pick_agents_tab", (), lambda _a, _p: None)
            is not False
        )
