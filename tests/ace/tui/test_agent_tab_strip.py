"""Behavior tests for the beautiful agent tab strip (sase-1bc.7).

Covers cell-width click mapping, tier transitions, overflow selection,
picker search, badges and arrival clearing, empty causes, and repaint
gating — all against pure helpers plus a pilot-mounted strip, in both
flag states where the owner is involved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from rich.cells import cell_len
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.modals.agent_tab_picker_modal import (
    AgentTabPickerModal,
    _filter_picker_entries as filter_picker_entries,
    _picker_row_text as picker_row_text,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tab_descriptors import (
    _split_machine_label as split_machine_label,
    descriptor_signature,
    project_agent_tab_descriptors,
)
from sase.ace.tui.models.agent_tab_index import (
    AgentTabIndex,
    build_agent_tab_index,
    _index_cache,
)
from sase.ace.tui.widgets.agent_tab_strip import (
    OVERFLOW_NEXT_ID,
    OVERFLOW_PREV_ID,
    AgentTabDescriptor,
    AgentTabStrip,
    _overflow_needs_attention as overflow_needs_attention,
    _overflow_window as overflow_window,
    _tier_for_width as tier_for_width,
    agent_tab_accent_for_name,
    agent_tab_empty_state,
)
from sase.core.agent_tab import (
    AgentTabCatalogEntry,
    DEFAULT_AGENT_TAB_KEY,
    AgentTabKey,
)


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Any:
    _index_cache.clear()
    yield
    _index_cache.clear()


def _view(token: Any = ("strip-test",)) -> AgentTabsViewConfig:
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
    origin_alias: str | None = None,
    origin_id: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status=status,
        start_time=datetime(2026, 9, 28, 8, 0, 0),
        raw_suffix=suffix,
        agent_tab=tab,
        fleet_origin_alias=origin_alias,
        fleet_origin_installation_id=origin_id,
    )


_SASE = AgentTabKey.named("sase")
_BLOG = AgentTabKey.named("blog")


def _descriptors(
    active: AgentTabKey = _SASE,
    *,
    arrival_blog: bool = False,
) -> tuple[AgentTabDescriptor, ...]:
    return (
        AgentTabDescriptor(
            key=DEFAULT_AGENT_TAB_KEY,
            label="main",
            accent="#AFAFAF",
            count=2,
            is_default=True,
        ),
        AgentTabDescriptor(
            key=_SASE,
            label="sase",
            accent="#AF87FF",
            count=12,
            stopped=1,
            unread=2,
        ),
        AgentTabDescriptor(
            key=_BLOG,
            label="blog",
            accent="#5FD7FF",
            count=3,
            has_arrival=arrival_blog,
        ),
    )


# --- tier transitions -----------------------------------------------------


def test_full_compact_micro_tier_plains() -> None:
    strip = AgentTabStrip(_descriptors(), _SASE)
    assert strip._build_content("full").plain == ("main 2 ┊ ▐ sase 12 S1 U2 ▌ │ blog 3")
    assert strip._build_content("compact").plain == ("main ┊ ▐ sase 12 S1 U2 ▌ │ blog")
    micro = strip._build_content("micro").plain
    assert micro == "mai ┊ ▐sas S1▌ │ blo"


def test_compact_inactive_drops_count_and_unread_but_keeps_failed() -> None:
    descriptors = (
        AgentTabDescriptor(
            key=DEFAULT_AGENT_TAB_KEY,
            label="main",
            accent="#AFAFAF",
            count=4,
            unread=3,
            failed=1,
            is_default=True,
        ),
        AgentTabDescriptor(key=_SASE, label="sase", accent="#AF87FF", count=1),
    )
    strip = AgentTabStrip(descriptors, _SASE)
    compact = strip._build_content("compact").plain
    assert "main F1" in compact
    assert "U3" not in compact
    assert " 4" not in compact.split("┊")[0]


def test_tier_for_width_picks_richest_fit() -> None:
    descriptors = _descriptors()
    assert tier_for_width(descriptors, 200, active_key=_SASE) == "full"
    full_width = len(strip_plain(descriptors, _SASE, "full"))
    compact_width = len(strip_plain(descriptors, _SASE, "compact"))
    assert tier_for_width(descriptors, compact_width, active_key=_SASE) in (
        "full",
        "compact",
    )
    assert tier_for_width(descriptors, 1, active_key=_SASE) == "micro"
    _ = full_width


def strip_plain(
    descriptors: tuple[AgentTabDescriptor, ...],
    active: AgentTabKey,
    tier: str,
) -> str:
    return AgentTabStrip(descriptors, active)._build_content(tier).plain


# --- cell-width click mapping ---------------------------------------------


async def test_two_cell_glyph_click_ranges_are_cell_accurate() -> None:
    descriptors = (
        AgentTabDescriptor(
            key=DEFAULT_AGENT_TAB_KEY,
            label="local",
            glyph="⌨",
            accent="#5FD7FF",
            count=9,
            is_default=True,
        ),
        AgentTabDescriptor(
            key=AgentTabKey.machine("id-apollo"),
            label="apollo",
            glyph="🔥",
            accent="#5FD7FF",
            count=14,
            stopped=1,
        ),
        AgentTabDescriptor(
            key=_SASE, label="sase", accent="#AF87FF", count=12, unread=2
        ),
    )

    class _StripApp(App[None]):
        selected: str | None = None

        def compose(self) -> ComposeResult:
            yield AgentTabStrip(descriptors, _SASE, id="tabs")

        @on(AgentTabStrip.TabClicked)
        def _on_tab_clicked(self, event: AgentTabStrip.TabClicked) -> None:
            self.selected = event.tab_id

    async with _StripApp().run_test(size=(120, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", AgentTabStrip)
        await pilot.pause()
        text = strip._build_content("full")

        assert strip._line_width == cell_len(text.plain)
        start, end = strip._tab_ranges["named:sase"]
        assert end - start == cell_len("▐ sase 12 U2 ▌")

        # Chips render left-aligned, so the click lands on raw content
        # cells with no center-pad compensation.
        await pilot.click(strip, offset=(start + 1, 0))
        await pilot.pause()
        assert pilot.app.selected == "named:sase"


# --- overflow selection ----------------------------------------------------


def test_overflow_window_is_active_centered() -> None:
    descriptors = tuple(
        AgentTabDescriptor(
            key=AgentTabKey.named(f"tab{i:02d}"),
            label=f"tab{i:02d}",
            accent="#AF87FF",
            count=i,
        )
        for i in range(7)
    )
    active = AgentTabKey.named("tab03")
    visible, before, after = overflow_window(descriptors, active, max_visible=3)
    assert [desc.label for desc in visible] == ["tab02", "tab03", "tab04"]
    assert (before, after) == (2, 2)
    first, before_first, after_first = overflow_window(
        descriptors, AgentTabKey.named("tab00"), max_visible=3
    )
    assert [desc.label for desc in first] == ["tab00", "tab01", "tab02"]
    assert (before_first, after_first) == (0, 4)


def test_overflow_chips_tint_when_hidden_tabs_need_attention() -> None:
    descriptors = (
        AgentTabDescriptor(
            key=AgentTabKey.named("a"), label="a", accent="#AF87FF", count=1
        ),
        AgentTabDescriptor(
            key=AgentTabKey.named("b"), label="b", accent="#AF87FF", count=1
        ),
        AgentTabDescriptor(
            key=AgentTabKey.named("c"),
            label="c",
            accent="#AF87FF",
            count=1,
            failed=2,
        ),
    )
    visible = (descriptors[0], descriptors[1])
    prev_need, next_need = overflow_needs_attention(descriptors, visible)
    assert (prev_need, next_need) == (False, True)
    strip = AgentTabStrip(descriptors, AgentTabKey.named("a"))
    strip._overflow_before = 0
    strip._overflow_after = 1
    strip._visible_descriptors = visible
    strip._overflow_prev_attention, strip._overflow_next_attention = (
        overflow_needs_attention(descriptors, visible)
    )
    assert strip._overflow_next_attention is True


async def test_overflow_chip_click_opens_picker_request() -> None:
    descriptors = tuple(
        AgentTabDescriptor(
            key=AgentTabKey.named(f"tab{i:02d}"),
            label=f"tab{i:02d} much longer name {i}",
            accent="#AF87FF",
            count=i,
        )
        for i in range(6)
    )

    class _OverflowApp(App[None]):
        requested: str | None = None

        def compose(self) -> ComposeResult:
            yield AgentTabStrip(descriptors, AgentTabKey.named("tab02"), id="tabs")

        @on(AgentTabStrip.PickerRequested)
        def _on_picker(self, event: AgentTabStrip.PickerRequested) -> None:
            self.requested = event.direction

    async with _OverflowApp().run_test(size=(30, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", AgentTabStrip)
        await pilot.pause()
        assert (
            OVERFLOW_PREV_ID in strip._tab_ranges
            or OVERFLOW_NEXT_ID in strip._tab_ranges
        )
        chip_id = (
            OVERFLOW_NEXT_ID
            if OVERFLOW_NEXT_ID in strip._tab_ranges
            else OVERFLOW_PREV_ID
        )
        start, end = strip._tab_ranges[chip_id]
        await pilot.click(strip, offset=(start, 0))
        await pilot.pause()
        assert pilot.app.requested in ("prev", "next")


# --- status reservation ------------------------------------------------------


async def test_status_sibling_reserves_cells_for_health_text() -> None:
    class _HeaderApp(App[None]):
        def compose(self) -> ComposeResult:
            with Horizontal():
                yield AgentTabStrip(_descriptors(), _SASE, id="tabs")
                yield Static("", id="agents-fleet-status")

    async with _HeaderApp().run_test(size=(120, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", AgentTabStrip)
        await pilot.pause()
        assert strip._status_reserved_width() == 0
        pilot.app.query_one("#agents-fleet-status", Static).update(
            "apollo: stale · cached 2m ago"
        )
        await pilot.pause()
        assert (
            strip._status_reserved_width()
            == cell_len("apollo: stale · cached 2m ago") + 2
        )


# --- picker search ---------------------------------------------------------


def test_picker_search_filters_by_label() -> None:
    entries = (
        AgentTabCatalogEntry(DEFAULT_AGENT_TAB_KEY, "default", "main", 2),
        AgentTabCatalogEntry(_SASE, "named", "sase", 12),
        AgentTabCatalogEntry(_BLOG, "named", "blog", 3),
    )
    assert filter_picker_entries(entries, "") == (0, 1, 2)
    assert filter_picker_entries(entries, "sas") == (1,)
    assert filter_picker_entries(entries, "BLOG") == (2,)
    assert filter_picker_entries(entries, "zzz") == ()


def test_picker_row_shows_glyph_count_and_attention() -> None:
    entry = AgentTabCatalogEntry(_SASE, "named", "sase", 12)
    descriptor = AgentTabDescriptor(
        key=_SASE,
        label="sase",
        accent="#AF87FF",
        count=12,
        stopped=1,
        unread=2,
    )
    row = picker_row_text(entry, descriptor)
    assert row.plain == "sase  12  S1  U2"


def test_picker_modal_constructs_with_entries_only() -> None:
    entries = (
        AgentTabCatalogEntry(DEFAULT_AGENT_TAB_KEY, "default", "main", 2),
        AgentTabCatalogEntry(_SASE, "named", "sase", 12),
    )
    modal = AgentTabPickerModal(entries, DEFAULT_AGENT_TAB_KEY)
    assert modal._selected == 0
    modal_active = AgentTabPickerModal(entries, _SASE)
    assert modal_active._selected == 1


# --- badges and arrival clearing -------------------------------------------


class _TabOwner(AgentTabsMixin):
    """Minimal owner driving the tab mixin without the full app."""

    def __init__(self, rows: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(rows)
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._jk_perf = None
        self._agent_search_query = ""
        self._agent_load_state = None
        self._unread_completed_agent_ids: set[Any] = set()
        self.notices: list[str] = []
        self._ensure_agent_tabs_state()

    def _rescope_agents_to_active_tab(self) -> None:
        self._agents = _scoped_agents_for_owner(self, list(self._agents_query_result))

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        """Fail closed: no strip is mounted in unit tests."""
        raise LookupError("no widget")

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Collect toasts instead of showing them."""
        self.notices.append(str(message))

    def reindex(self, rows: list[Agent]) -> None:
        """Install *rows* as the roster and rebuild the tab index."""
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agent_tab_index = build_agent_tab_index(list(rows), _view())


def _two_tab_owner() -> _TabOwner:
    owner = _TabOwner([_row("a"), _row("b", tab="sase"), _row("c", tab="sase")])
    owner.reindex(owner._agents_with_children)
    return owner


def test_arrivals_baseline_then_mark_then_clear_on_visit() -> None:
    owner = _two_tab_owner()
    owner._reconcile_active_agent_tab()
    assert owner._agent_tab_arrivals == set()
    owner.reindex([_row("a"), _row("b", tab="sase"), _row("d", tab="blog")])
    owner._reconcile_active_agent_tab()
    assert owner._agent_tab_arrivals == {_BLOG}
    assert owner._switch_agents_tab(_BLOG, reason="test") is True
    assert owner._agent_tab_arrivals == set()


def test_query_aware_counts_while_existence_is_not() -> None:
    owner = _two_tab_owner()
    owner._reconcile_active_agent_tab()
    entries = owner._agent_tab_catalog_view()
    assert {entry.key for entry in entries} == {
        DEFAULT_AGENT_TAB_KEY,
        _SASE,
    }
    owner._agents_query_result = [
        row for row in owner._agents_with_children if row.agent_tab == "sase"
    ]
    descriptors = owner._descriptors_for_strip(entries, DEFAULT_AGENT_TAB_KEY)
    by_key = {desc.key: desc for desc in descriptors}
    assert by_key[DEFAULT_AGENT_TAB_KEY].count == 0
    assert by_key[_SASE].count == 2
    assert {desc.key for desc in descriptors} == {
        DEFAULT_AGENT_TAB_KEY,
        _SASE,
    }


def test_badges_use_stopped_failed_unread() -> None:
    owner = _TabOwner(
        [
            _row("a", tab="sase", status="QUESTION"),
            _row("b", tab="sase", status="FAILED"),
            _row("c", tab="sase", status="DONE"),
        ]
    )
    owner.reindex(owner._agents_with_children)
    owner._reconcile_active_agent_tab()
    entries = owner._agent_tab_catalog_view()
    owner._unread_completed_agent_ids = {owner._agents_with_children[2].identity}
    descriptors = owner._descriptors_for_strip(entries, DEFAULT_AGENT_TAB_KEY)
    sase_desc = next(desc for desc in descriptors if desc.key == _SASE)
    assert sase_desc.count == 3
    assert sase_desc.stopped == 1
    assert sase_desc.failed == 1
    assert sase_desc.unread == 1


# --- empty causes ------------------------------------------------------------


def test_empty_causes_cover_all_three_states() -> None:
    genuine = agent_tab_empty_state(
        scoped_count=0, tab_has_roots=False, tab_label="blog"
    )
    assert genuine is not None and genuine.kind == "empty"
    assert "blog" in genuine.title
    hidden = agent_tab_empty_state(
        scoped_count=0,
        tab_has_roots=True,
        query="status:running",
        matches_elsewhere=4,
        tab_label="sase",
    )
    assert hidden is not None and hidden.kind == "query_hides"
    assert "4" in hidden.detail and "clear" in hidden.detail.casefold()
    unavailable = agent_tab_empty_state(
        scoped_count=0,
        tab_has_roots=True,
        feed_unavailable=True,
        tab_label="apollo",
    )
    assert unavailable is not None and unavailable.kind == "feed_unavailable"
    assert "Machines" in unavailable.detail
    assert agent_tab_empty_state(scoped_count=2, tab_has_roots=True) is None


def test_owner_empty_state_names_query_hides() -> None:
    owner = _two_tab_owner()
    owner._reconcile_active_agent_tab()
    owner._switch_agents_tab(_SASE, reason="test")
    owner._agents = []
    owner._agent_search_query = "status:running"
    state = owner._active_tab_empty_state()
    assert state is not None and state.kind == "query_hides"


# --- detail cause rendering ----------------------------------------------------


class _FakeDetail:
    """Stand-in for AgentDetail recording empty-state renders."""

    def __init__(self) -> None:
        self.empty_calls = 0
        self.tab_empty: list[tuple[str, str]] = []

    def show_empty(self) -> None:
        self.empty_calls += 1

    def show_tab_empty_state(self, title: str, detail: str = "") -> None:
        self.tab_empty.append((title, detail))


def test_show_empty_cause_genuine() -> None:
    owner = _two_tab_owner()
    detail = _FakeDetail()
    owner._reconcile_active_agent_tab()
    assert owner._switch_agents_tab(_SASE, reason="test") is True
    owner._agents = []
    assert owner._show_active_tab_empty_state(detail) is True
    assert detail.tab_empty == [("No agents on sase", "")]
    assert detail.empty_calls == 0


def test_show_empty_cause_query_hides() -> None:
    owner = _two_tab_owner()
    detail = _FakeDetail()
    owner._reconcile_active_agent_tab()
    assert owner._switch_agents_tab(_SASE, reason="test") is True
    owner._agents = []
    owner._agent_search_query = "status:running"
    assert owner._show_active_tab_empty_state(detail) is True
    assert len(detail.tab_empty) == 1
    title, text = detail.tab_empty[0]
    assert "sase" in title
    assert "matches elsewhere" in text and "clear" in text.casefold()


def test_show_empty_cause_feed_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from sase.ace.tui import agent_tabs_settings as settings_mod
    from sase.ace.tui.models._fleet_agents_hosts import HostFeedIssue

    apollo_key = AgentTabKey.machine("install-apollo")
    view = AgentTabsViewConfig(
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
        pinned_by_alias={"apollo": "install-apollo"},
        named_order={},
        token=("strip-test-machine",),
    )
    monkeypatch.setattr(settings_mod, "agent_tabs_view_config", lambda: view)
    settings_mod._agent_tabs_view_config_for_token.cache_clear()  # noqa: SLF001
    try:
        owner = _TabOwner(
            [
                _row("a"),
                _row(
                    "remote",
                    origin_alias="apollo",
                    origin_id="install-apollo",
                ),
            ]
        )
        owner.reindex(owner._agents_with_children)
        detail = _FakeDetail()
        owner._reconcile_active_agent_tab()
        assert owner._switch_agents_tab(apollo_key, reason="test") is True
        owner._agents_fleet_projection = SimpleNamespace(
            host_feed_issues=(
                HostFeedIssue(
                    alias="apollo",
                    status="invalid",
                    error="handshake failed",
                    cache_age_seconds=None,
                    diagnostic=None,
                ),
            ),
            diagnostics=(),
        )
        remaining = [
            row for row in owner._agents_with_children if not row.fleet_origin_alias
        ]
        owner._agents_with_children = remaining
        owner._agents_query_result = list(remaining)
        owner._agent_tab_index = build_agent_tab_index(remaining, view)
        owner._reconcile_active_agent_tab()
        owner._rescope_agents_to_active_tab()
        assert owner._agents == []
        assert owner._show_active_tab_empty_state(detail) is True
    finally:
        settings_mod._agent_tabs_view_config_for_token.cache_clear()  # noqa: SLF001
    assert len(detail.tab_empty) == 1
    title, text = detail.tab_empty[0]
    assert "apollo" in title
    assert "Machines" in text


def test_show_empty_cause_falls_back_without_cause() -> None:
    owner = _two_tab_owner()
    detail = _FakeDetail()
    owner._reconcile_active_agent_tab()
    assert owner._show_active_tab_empty_state(detail) is False
    assert detail.tab_empty == []


def test_show_empty_cause_falls_back_without_widget_support() -> None:
    owner = _two_tab_owner()
    owner._reconcile_active_agent_tab()
    assert owner._switch_agents_tab(_SASE, reason="test") is True
    owner._agents = []
    assert owner._show_active_tab_empty_state(object()) is False


# --- repaint gating ------------------------------------------------------------


def test_repaint_signature_covers_counts_attention_health_and_arrivals() -> None:
    base = _descriptors()
    active = _SASE
    first = descriptor_signature(base, active, True)
    assert descriptor_signature(base, active, True) == first
    changed_count = (
        base[0],
        AgentTabDescriptor(
            key=_SASE,
            label="sase",
            accent="#AF87FF",
            count=13,
            stopped=1,
            unread=2,
        ),
        base[2],
    )
    assert descriptor_signature(changed_count, active, True) != first
    changed_health = (
        base[0],
        AgentTabDescriptor(
            key=_SASE,
            label="sase",
            accent="#AF87FF",
            count=12,
            stopped=1,
            unread=2,
            health="stale",
        ),
        base[2],
    )
    assert descriptor_signature(changed_health, active, True) != first
    changed_arrival = (
        base[0],
        base[1],
        AgentTabDescriptor(
            key=_BLOG,
            label="blog",
            accent="#5FD7FF",
            count=3,
            has_arrival=True,
        ),
    )
    assert descriptor_signature(changed_arrival, active, True) != first
    assert descriptor_signature(base, _BLOG, True) != first
    assert descriptor_signature(base, active, False) != first


def test_refresh_skips_widget_update_on_unchanged_signature() -> None:
    owner = _two_tab_owner()
    updates: list[Any] = []

    class _Strip:
        def set_descriptors(self, descriptors: Any, active: Any) -> None:
            updates.append((descriptors, active))

    owner._strip_for_test = _Strip()  # type: ignore[attr-defined]

    def _query_one(_selector: str) -> Any:
        return owner._strip_for_test  # type: ignore[attr-defined]

    owner.query_one = _query_one  # type: ignore[assignment]
    owner._reconcile_active_agent_tab()
    owner._refresh_agent_tab_strip()
    assert len(updates) == 1
    owner._refresh_agent_tab_strip()
    assert len(updates) == 1


# --- accents -----------------------------------------------------------------


def test_named_accent_prefers_config_then_project_then_hash() -> None:
    assert agent_tab_accent_for_name("sase", config_color="#123456") == "#123456"
    from sase.project_accents import PROJECT_ACCENTS, project_accent

    assert agent_tab_accent_for_name("sase", enabled_projects=("sase",)) == (
        project_accent("sase", among=("sase",))
    )
    hashed = agent_tab_accent_for_name("sase")
    assert hashed in PROJECT_ACCENTS


def test_split_machine_label() -> None:
    assert split_machine_label("⌨ apollo") == ("⌨", "apollo")
    assert split_machine_label("sase") == ("", "sase")
    assert split_machine_label("main") == ("", "main")


# --- machine tabs (sase-1bc.9) --------------------------------------------------

_APOLLO = AgentTabKey.machine("iid-apollo")


def _machine_view() -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=True,
        machine_order=(("iid-apollo", "apollo"),),
        pinned_by_alias={"apollo": "iid-apollo"},
        named_order={},
        token=("machine-test",),
    )


def test_machine_off_tab_extras_names_other_tab_counts() -> None:
    from sase.ace.tui.models.agent_tab_descriptors import machine_off_tab_extras

    rows = [
        _row("a", origin_alias="apollo", origin_id="iid-apollo"),
        _row("b", tab="sase", origin_alias="apollo", origin_id="iid-apollo"),
        _row("c", tab="sase", origin_alias="apollo", origin_id="iid-apollo"),
        _row("d", tab="blog", origin_alias="apollo", origin_id="iid-apollo"),
        _row(
            "e",
            tab="sase",
            origin_alias="zeus",
            origin_id="iid-apollo",
        ),
        _row("f", tab="sase"),
        _row("g"),
    ]
    index = build_agent_tab_index(rows, _machine_view())
    entries = index.catalog
    assert {entry.key for entry in entries} == {
        DEFAULT_AGENT_TAB_KEY,
        _APOLLO,
        _SASE,
        _BLOG,
    }
    extras = machine_off_tab_extras(rows, index.key_for, entries, machine_mode=True)
    assert extras[_APOLLO] == "+4 apollo agents on other tabs: sase 3, blog 1"
    assert extras[DEFAULT_AGENT_TAB_KEY] == "+1 local agents on other tabs: sase 1"


def test_machine_off_tab_extras_empty_without_machine_tabs() -> None:
    from sase.ace.tui.models.agent_tab_descriptors import machine_off_tab_extras

    rows = [_row("a", tab="sase")]
    index = build_agent_tab_index(rows, _view())
    extras = machine_off_tab_extras(
        rows, index.key_for, index.catalog, machine_mode=False
    )
    assert extras == {}


def test_machine_tooltip_appends_health_and_off_tab_notes() -> None:
    from sase.ace.tui.widgets.agent_tab_strip import _agent_tab_tooltip

    desc = AgentTabDescriptor(
        key=_APOLLO,
        label="apollo",
        glyph="⌨",
        accent="#5FD7FF",
        count=14,
        stopped=1,
        description=("apollo: stale · +4 apollo agents on other tabs: sase 3, blog 1"),
        machine_alias="apollo",
    )
    assert _agent_tab_tooltip(desc) == (
        "apollo · 14 agents · S1 · apollo: stale · "
        "+4 apollo agents on other tabs: sase 3, blog 1"
    )


def test_machine_tooltip_keeps_configured_description_on_named_tabs() -> None:
    from sase.ace.tui.widgets.agent_tab_strip import _agent_tab_tooltip

    desc = AgentTabDescriptor(
        key=_SASE,
        label="sase",
        accent="#AF87FF",
        count=12,
        description="Everything touching the sase repos.",
    )
    assert _agent_tab_tooltip(desc) == (
        "sase · 12 agents · Everything touching the sase repos."
    )


def test_machine_health_notes_old_contract_without_feed_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from sase.ace.tui import agent_tabs_settings as settings_mod
    from sase.ace.tui.actions.agents import _agent_tabs_catalog as catalog_mod

    monkeypatch.setattr(settings_mod, "agent_tabs_view_config", lambda: _machine_view())
    monkeypatch.setattr(
        catalog_mod,
        "refresh_agent_tab_contract_versions",
        lambda *, allow_disk=False: frozenset({"apollo"}),
    )
    owner = SimpleNamespace(
        _agents_fleet_projection=SimpleNamespace(host_feed_issues=(), diagnostics=()),
        _agent_tab_index=AgentTabIndex(
            (
                AgentTabCatalogEntry(DEFAULT_AGENT_TAB_KEY, "default", "main", 1),
                AgentTabCatalogEntry(_APOLLO, "machine", "⌨ apollo", 2),
            ),
            {},
            {},
        ),
        _agent_tab_latched_key=None,
        _agent_tab_known_labels={},
        _active_agent_tab=_APOLLO,
    )
    health, extras, active_text = catalog_mod.agent_tab_health_for_owner(owner)
    assert health == {}
    assert extras[_APOLLO] == "apollo: tab data unavailable (upgrade sase)"
    assert active_text == "apollo: tab data unavailable (upgrade sase)"


def test_contract_version_refresh_caches_and_gates_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents import _agent_tabs_catalog as catalog_mod

    monkeypatch.setattr(
        catalog_mod, "_CONTRACT_VERSIONS_CACHE", (0.0, frozenset({"apollo"}))
    )
    assert catalog_mod.refresh_agent_tab_contract_versions() == frozenset({"apollo"})

    calls: list[None] = []

    def _fail() -> dict[str, int]:
        calls.append(None)
        raise RuntimeError("no federation in unit tests")

    monkeypatch.setattr("sase.dispatch.launch.cached_fleet_contract_versions", _fail)
    from types import SimpleNamespace as _SimpleNamespace

    monkeypatch.setattr(catalog_mod, "time", _SimpleNamespace(monotonic=lambda: 10**9))
    assert catalog_mod.refresh_agent_tab_contract_versions(allow_disk=True) == (
        frozenset({"apollo"})
    )
    assert len(calls) == 1
