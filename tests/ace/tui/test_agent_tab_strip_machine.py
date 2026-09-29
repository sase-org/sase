"""Repaint-gating, accent, and machine-tab strip tests."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models.agent_tab_descriptors import (
    _split_machine_label as split_machine_label,
    descriptor_signature,
)
from sase.ace.tui.models.agent_tab_index import _index_cache
from sase.ace.tui.widgets.agent_tab_strip import (
    AgentTabDescriptor,
    agent_tab_accent_for_name,
)
from sase.core.agent_tab import AgentTabKey
from tests.ace.tui._agent_tab_strip_shared import (
    BLOG,
    SASE,
    make_descriptors,
    make_row,
    make_view,
    two_tab_owner,
)

__all__ = [
    "test_contract_version_refresh_caches_and_gates_disk",
    "test_machine_health_notes_old_contract_without_feed_issues",
    "test_machine_off_tab_extras_empty_without_machine_tabs",
    "test_machine_off_tab_extras_names_other_tab_counts",
    "test_machine_tooltip_appends_health_and_off_tab_notes",
    "test_machine_tooltip_keeps_configured_description_on_named_tabs",
    "test_named_accent_prefers_config_then_project_then_hash",
    "test_refresh_skips_widget_update_on_unchanged_signature",
    "test_repaint_signature_covers_counts_attention_health_and_arrivals",
    "test_split_machine_label",
]


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Any:
    _index_cache.clear()
    yield
    _index_cache.clear()


# --- repaint gating ------------------------------------------------------------


def test_repaint_signature_covers_counts_attention_health_and_arrivals() -> None:
    base = make_descriptors()
    active = SASE
    first = descriptor_signature(base, active, True)
    assert descriptor_signature(base, active, True) == first
    changed_count = (
        base[0],
        AgentTabDescriptor(
            key=SASE,
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
            key=SASE,
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
            key=BLOG,
            label="blog",
            accent="#5FD7FF",
            count=3,
            has_arrival=True,
        ),
    )
    assert descriptor_signature(changed_arrival, active, True) != first
    assert descriptor_signature(base, BLOG, True) != first
    assert descriptor_signature(base, active, False) != first


def test_refresh_skips_widget_update_on_unchanged_signature() -> None:
    owner = two_tab_owner()
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
    from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
    from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY

    rows = [
        make_row("a", origin_alias="apollo", origin_id="iid-apollo"),
        make_row("b", tab="sase", origin_alias="apollo", origin_id="iid-apollo"),
        make_row("c", tab="sase", origin_alias="apollo", origin_id="iid-apollo"),
        make_row("d", tab="blog", origin_alias="apollo", origin_id="iid-apollo"),
        make_row(
            "e",
            tab="sase",
            origin_alias="zeus",
            origin_id="iid-apollo",
        ),
        make_row("f", tab="sase"),
        make_row("g"),
    ]
    index = build_agent_tab_index(rows, _machine_view())
    entries = index.catalog
    assert {entry.key for entry in entries} == {
        DEFAULT_AGENT_TAB_KEY,
        _APOLLO,
        SASE,
        BLOG,
    }
    extras = machine_off_tab_extras(rows, index.key_for, entries, machine_mode=True)
    assert extras[_APOLLO] == "+4 apollo agents on other tabs: sase 3, blog 1"
    assert extras[DEFAULT_AGENT_TAB_KEY] == "+1 local agents on other tabs: sase 1"


def test_machine_off_tab_extras_empty_without_machine_tabs() -> None:
    from sase.ace.tui.models.agent_tab_descriptors import machine_off_tab_extras
    from sase.ace.tui.models.agent_tab_index import build_agent_tab_index

    rows = [make_row("a", tab="sase")]
    index = build_agent_tab_index(rows, make_view())
    extras = machine_off_tab_extras(
        rows, index.key_for, index.catalog, machine_mode=False
    )
    assert extras == {}


def test_machine_tooltip_appends_health_and_off_tab_notes() -> None:
    from sase.ace.tui.widgets._agent_tab_strip_strip import _agent_tab_tooltip

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
    from sase.ace.tui.widgets._agent_tab_strip_strip import _agent_tab_tooltip

    desc = AgentTabDescriptor(
        key=SASE,
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
    from sase.ace.tui.models.agent_tab_index import AgentTabIndex
    from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabCatalogEntry

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
