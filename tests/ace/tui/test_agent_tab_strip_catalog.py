"""Picker, badges, empty-cause, and detail-render strip tests."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.modals.agent_tab_picker_modal import (
    AgentTabPickerModal,
    _filter_picker_entries as filter_picker_entries,
    _picker_row_text as picker_row_text,
)
from sase.ace.tui.models.agent_tab_index import _index_cache, build_agent_tab_index
from sase.ace.tui.widgets.agent_tab_strip import (
    AgentTabDescriptor,
    agent_tab_empty_state,
)
from sase.core.agent_tab import (
    DEFAULT_AGENT_TAB_KEY,
    AgentTabCatalogEntry,
    AgentTabKey,
)
from tests.ace.tui._agent_tab_strip_shared import (
    BLOG,
    SASE,
    TabOwner,
    make_row,
    two_tab_owner,
)

__all__ = [
    "test_arrivals_baseline_then_mark_then_clear_on_visit",
    "test_badges_use_stopped_failed_unread",
    "test_empty_causes_cover_all_three_states",
    "test_owner_empty_state_names_query_hides",
    "test_picker_modal_constructs_with_entries_only",
    "test_picker_row_shows_glyph_count_and_attention",
    "test_picker_search_filters_by_label",
    "test_query_aware_counts_while_existence_is_not",
    "test_show_empty_cause_falls_back_without_cause",
    "test_show_empty_cause_falls_back_without_widget_support",
    "test_show_empty_cause_feed_unavailable",
    "test_show_empty_cause_genuine",
    "test_show_empty_cause_query_hides",
]


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Any:
    _index_cache.clear()
    yield
    _index_cache.clear()


# --- picker search ---------------------------------------------------------


def test_picker_search_filters_by_label() -> None:
    entries = (
        AgentTabCatalogEntry(DEFAULT_AGENT_TAB_KEY, "default", "main", 2),
        AgentTabCatalogEntry(SASE, "named", "sase", 12),
        AgentTabCatalogEntry(BLOG, "named", "blog", 3),
    )
    assert filter_picker_entries(entries, "") == (0, 1, 2)
    assert filter_picker_entries(entries, "sas") == (1,)
    assert filter_picker_entries(entries, "BLOG") == (2,)
    assert filter_picker_entries(entries, "zzz") == ()


def test_picker_row_shows_glyph_count_and_attention() -> None:
    entry = AgentTabCatalogEntry(SASE, "named", "sase", 12)
    descriptor = AgentTabDescriptor(
        key=SASE,
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
        AgentTabCatalogEntry(SASE, "named", "sase", 12),
    )
    modal = AgentTabPickerModal(entries, DEFAULT_AGENT_TAB_KEY)
    assert modal._selected == 0
    modal_active = AgentTabPickerModal(entries, SASE)
    assert modal_active._selected == 1


# --- badges and arrival clearing -------------------------------------------


def test_arrivals_baseline_then_mark_then_clear_on_visit() -> None:
    owner = two_tab_owner()
    owner._reconcile_active_agent_tab()
    assert owner._agent_tab_arrivals == set()
    owner.reindex([make_row("a"), make_row("b", tab="sase"), make_row("d", tab="blog")])
    owner._reconcile_active_agent_tab()
    assert owner._agent_tab_arrivals == {BLOG}
    assert owner._switch_agents_tab(BLOG, reason="test") is True
    assert owner._agent_tab_arrivals == set()


def test_query_aware_counts_while_existence_is_not() -> None:
    owner = two_tab_owner()
    owner._reconcile_active_agent_tab()
    entries = owner._agent_tab_catalog_view()
    assert {entry.key for entry in entries} == {
        DEFAULT_AGENT_TAB_KEY,
        SASE,
    }
    owner._agents_query_result = [
        row for row in owner._agents_with_children if row.agent_tab == "sase"
    ]
    descriptors = owner._descriptors_for_strip(entries, DEFAULT_AGENT_TAB_KEY)
    by_key = {desc.key: desc for desc in descriptors}
    assert by_key[DEFAULT_AGENT_TAB_KEY].count == 0
    assert by_key[SASE].count == 2
    assert {desc.key for desc in descriptors} == {
        DEFAULT_AGENT_TAB_KEY,
        SASE,
    }


def test_badges_use_stopped_failed_unread() -> None:
    owner = TabOwner(
        [
            make_row("a", tab="sase", status="QUESTION"),
            make_row("b", tab="sase", status="FAILED"),
            make_row("c", tab="sase", status="DONE"),
        ]
    )
    owner.reindex(owner._agents_with_children)
    owner._reconcile_active_agent_tab()
    entries = owner._agent_tab_catalog_view()
    owner._unread_completed_agent_ids = {owner._agents_with_children[2].identity}
    descriptors = owner._descriptors_for_strip(entries, DEFAULT_AGENT_TAB_KEY)
    sase_desc = next(desc for desc in descriptors if desc.key == SASE)
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
    owner = two_tab_owner()
    owner._reconcile_active_agent_tab()
    owner._switch_agents_tab(SASE, reason="test")
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
    owner = two_tab_owner()
    detail = _FakeDetail()
    owner._reconcile_active_agent_tab()
    assert owner._switch_agents_tab(SASE, reason="test") is True
    owner._agents = []
    assert owner._show_active_tab_empty_state(detail) is True
    assert detail.tab_empty == [("No agents on sase", "")]
    assert detail.empty_calls == 0


def test_show_empty_cause_query_hides() -> None:
    owner = two_tab_owner()
    detail = _FakeDetail()
    owner._reconcile_active_agent_tab()
    assert owner._switch_agents_tab(SASE, reason="test") is True
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
        owner = TabOwner(
            [
                make_row("a"),
                make_row(
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
    owner = two_tab_owner()
    detail = _FakeDetail()
    owner._reconcile_active_agent_tab()
    assert owner._show_active_tab_empty_state(detail) is False
    assert detail.tab_empty == []


def test_show_empty_cause_falls_back_without_widget_support() -> None:
    owner = two_tab_owner()
    owner._reconcile_active_agent_tab()
    assert owner._switch_agents_tab(SASE, reason="test") is True
    owner._agents = []
    assert owner._show_active_tab_empty_state(object()) is False
