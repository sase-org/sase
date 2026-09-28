"""o/O layout ladder tests (sase-1bc.8).

Covers the ``AgentPanelLayout`` ladder model, the stored/remembered
owner state, anchor-preserving transitions, drill-in from All tabs, the
R6 two-segment mode, ladder titles, the info-row chip, the All-tabs
strip state, row tab chips, and roster tab chips — in both flag states.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin
from sase.ace.tui.actions.agents._panel_layout import (
    effective_panel_layout_for_owner,
    merged_panel_title_for_owner,
    multiple_agent_tabs_for_owner,
    panel_layout_merged_for_owner,
    remembered_layout_for_tab,
    set_panel_layout,
    stored_panel_layout,
    sync_panel_grouped_bool,
)
from sase.ace.tui.actions.agents._tab_scope import (
    _scoped_agents_for_owner,
    current_agent_tab_scope,
    current_agent_tab_scope_token,
)
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models import Agent
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_panel_layout import (
    AgentPanelLayout,
    available_panel_layouts,
    coerce_panel_layout,
    effective_panel_layout,
    layout_description,
    layout_info_row_label,
    layout_notify_label,
    layout_short_label,
    next_panel_layout,
    panel_layout_is_merged,
    prev_panel_layout,
)
from sase.ace.tui.models.agent_tab_index import ALL_AGENT_TABS, build_agent_tab_index
from sase.ace.tui.models.agent_tab_index import _index_cache
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey
from sase.feature_flags import override_flags


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Any:
    _index_cache.clear()
    yield
    _index_cache.clear()


def _view(token: Any = ("ladder-test",)) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=False,
        machine_order=(),
        pinned_by_alias={},
        named_order={},
        token=token,
    )


def _row(suffix: str, *, tab: str | None = None, tribe: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status="RUNNING",
        start_time=datetime(2026, 9, 28, 8, 0, 0),
        raw_suffix=suffix,
        agent_tab=tab,
        tribe=tribe,
    )


class _LadderOwner(AgentTabsMixin):
    """Minimal owner driving the ladder without the full app."""

    def __init__(self, rows: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(rows)
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._jk_perf = None
        self._agent_panels_grouped = False
        self._agent_panel_layout = AgentPanelLayout.SPLIT
        self._agent_panel_layout_by_tab = {}
        self._agent_panel_layout_last_tab = None
        self._panel_fold_hint_mode_active = False
        self._expanded_panel_focus = False
        self._current_group_key = None
        self._current_attempt_number = None
        self.notices: list[str] = []
        self._ensure_agent_tabs_state()

    def _rescope_agents_to_active_tab(self) -> None:
        self._agents = _scoped_agents_for_owner(self, list(self._agents_query_result))

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        """Fail closed: no widgets are mounted in unit tests."""
        raise LookupError("no widget")

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Collect toasts instead of showing them."""
        self.notices.append(str(message))

    def reindex(self, rows: list[Agent]) -> None:
        """Install *rows* as the roster and rebuild the tab index."""
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agent_tab_index = build_agent_tab_index(list(rows), _view())


def _two_tab_owner() -> _LadderOwner:
    owner = _LadderOwner(
        [
            _row("a", tribe="alpha"),
            _row("b", tab="sase", tribe="alpha"),
            _row("c", tab="sase", tribe="beta"),
        ]
    )
    owner.reindex(owner._agents_with_children)
    return owner


# --- Pure ladder model ----------------------------------------------------


def test_ladder_stepping_wraps() -> None:
    assert next_panel_layout(AgentPanelLayout.SPLIT) is AgentPanelLayout.MERGED
    assert next_panel_layout(AgentPanelLayout.MERGED) is AgentPanelLayout.ALL_TABS
    assert next_panel_layout(AgentPanelLayout.ALL_TABS) is AgentPanelLayout.SPLIT
    assert prev_panel_layout(AgentPanelLayout.SPLIT) is AgentPanelLayout.ALL_TABS
    assert prev_panel_layout(AgentPanelLayout.ALL_TABS) is AgentPanelLayout.MERGED
    assert prev_panel_layout(AgentPanelLayout.MERGED) is AgentPanelLayout.SPLIT


def test_ladder_two_segment_mode_wraps_without_all_tabs() -> None:
    available = available_panel_layouts(False)
    assert available == (AgentPanelLayout.SPLIT, AgentPanelLayout.MERGED)
    assert available_panel_layouts(True) == (
        AgentPanelLayout.SPLIT,
        AgentPanelLayout.MERGED,
        AgentPanelLayout.ALL_TABS,
    )
    assert (
        next_panel_layout(AgentPanelLayout.MERGED, available) is AgentPanelLayout.SPLIT
    )
    assert (
        prev_panel_layout(AgentPanelLayout.SPLIT, available) is AgentPanelLayout.MERGED
    )


def test_ladder_r6_stored_all_renders_as_merged() -> None:
    assert (
        effective_panel_layout(AgentPanelLayout.ALL_TABS, False)
        is AgentPanelLayout.MERGED
    )
    assert (
        effective_panel_layout(AgentPanelLayout.ALL_TABS, True)
        is AgentPanelLayout.ALL_TABS
    )
    assert (
        effective_panel_layout(AgentPanelLayout.SPLIT, False) is AgentPanelLayout.SPLIT
    )


def test_ladder_labels_and_descriptions() -> None:
    assert layout_short_label(AgentPanelLayout.SPLIT) == "Split by tribe"
    assert layout_short_label(AgentPanelLayout.MERGED) == "Merged"
    assert layout_short_label(AgentPanelLayout.ALL_TABS) == "All tabs"
    assert layout_notify_label(AgentPanelLayout.ALL_TABS) == "all tabs"
    assert layout_info_row_label(AgentPanelLayout.MERGED) == "merged"
    assert layout_info_row_label(AgentPanelLayout.ALL_TABS) == "all tabs"
    assert (
        layout_description(AgentPanelLayout.SPLIT, "sase")
        == "One panel per tribe, showing sase only."
    )
    assert (
        layout_description(AgentPanelLayout.MERGED, "sase")
        == "One panel with every agent on sase."
    )
    assert (
        layout_description(AgentPanelLayout.ALL_TABS, "sase")
        == "One panel with every agent on every tab."
    )
    assert panel_layout_is_merged(AgentPanelLayout.SPLIT) is False
    assert panel_layout_is_merged(AgentPanelLayout.MERGED) is True
    assert panel_layout_is_merged(AgentPanelLayout.ALL_TABS) is True
    assert coerce_panel_layout("merged") is AgentPanelLayout.MERGED
    assert coerce_panel_layout("bogus") is AgentPanelLayout.SPLIT
    assert coerce_panel_layout(None) is AgentPanelLayout.SPLIT


# --- Owner state -----------------------------------------------------------


def test_flag_off_ladder_collapses_to_split_merged() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=False):
        assert multiple_agent_tabs_for_owner(owner) is False
        assert stored_panel_layout(owner) is AgentPanelLayout.SPLIT
        assert effective_panel_layout_for_owner(owner) is AgentPanelLayout.SPLIT
        assert panel_layout_merged_for_owner(owner) is False
        assert current_agent_tab_scope(owner) == DEFAULT_AGENT_TAB_KEY
        assert merged_panel_title_for_owner(owner) is None
        assert set_panel_layout(owner, AgentPanelLayout.MERGED) is True
        assert owner._agent_panels_grouped is True
        assert set_panel_layout(owner, AgentPanelLayout.MERGED) is False
        assert set_panel_layout(owner, AgentPanelLayout.SPLIT) is True
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        # All tabs collapses to the merged view with the flag off.
        assert owner._agent_panel_layout is AgentPanelLayout.MERGED
        assert owner._agent_panels_grouped is True


def test_flag_on_single_tab_hides_all_tabs() -> None:
    owner = _LadderOwner([_row("a"), _row("b")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        assert multiple_agent_tabs_for_owner(owner) is False
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        assert effective_panel_layout_for_owner(owner) is AgentPanelLayout.MERGED
        assert current_agent_tab_scope(owner) == DEFAULT_AGENT_TAB_KEY
        assert merged_panel_title_for_owner(owner) is None


def test_ladder_zoom_out_keeps_selected_node() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert multiple_agent_tabs_for_owner(owner) is True
        owner.current_idx = 0
        identity = owner._agents[0].identity
        assert set_panel_layout(owner, AgentPanelLayout.MERGED) is True
        assert owner._agent_panels_grouped is True
        assert [r.raw_suffix for r in owner._agents] == ["a"]
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        assert [r.raw_suffix for r in owner._agents] == ["a", "b", "c"]
        assert current_agent_tab_scope(owner) is ALL_AGENT_TABS
        assert current_agent_tab_scope_token(owner) == "all"
        assert owner._agents[owner.current_idx].identity == identity
        assert owner.notices[-1] == "Panel layout: all tabs"


def test_ladder_zoom_in_lands_on_selected_nodes_tab() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        # Select the sase row while every tab is visible.
        owner.current_idx = 2
        identity = owner._agents[2].identity
        from sase.ace.tui.actions.agents._panel_layout import (
            _selected_agent_tab_key,
        )

        assert _selected_agent_tab_key(owner) == AgentTabKey.named("sase")
        assert set_panel_layout(owner, AgentPanelLayout.SPLIT) is True
        assert owner._active_agent_tab == AgentTabKey.named("sase")
        assert [r.raw_suffix for r in owner._agents] == ["b", "c"]
        assert owner._agents[owner.current_idx].identity == identity
        assert owner._agent_panels_grouped is False


def test_ladder_remembers_per_tab_level() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert remembered_layout_for_tab(owner, DEFAULT_AGENT_TAB_KEY) is (
            AgentPanelLayout.SPLIT
        )
        assert set_panel_layout(owner, AgentPanelLayout.MERGED) is True
        assert remembered_layout_for_tab(owner, DEFAULT_AGENT_TAB_KEY) is (
            AgentPanelLayout.MERGED
        )
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        # Entering All tabs does not clobber the remembered per-tab level.
        assert remembered_layout_for_tab(owner, DEFAULT_AGENT_TAB_KEY) is (
            AgentPanelLayout.MERGED
        )


def test_tab_choice_at_all_tabs_drills_into_remembered_level() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert set_panel_layout(owner, AgentPanelLayout.MERGED) is True
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        assert owner._switch_agents_tab(AgentTabKey.named("sase")) is True
        assert owner._active_agent_tab == AgentTabKey.named("sase")
        assert stored_panel_layout(owner) is AgentPanelLayout.SPLIT
        assert owner._agent_panels_grouped is False
        assert [r.raw_suffix for r in owner._agents] == ["b", "c"]
        # Drilling into the tab the ladder was entered from still applies,
        # restoring its remembered Merged level.
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        assert owner._switch_agents_tab(DEFAULT_AGENT_TAB_KEY) is True
        assert stored_panel_layout(owner) is AgentPanelLayout.MERGED
        assert owner._agent_panels_grouped is True
        assert [r.raw_suffix for r in owner._agents] == ["a"]


def test_cycle_at_all_tabs_drills_in() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        owner._cycle_agents_tab(1)
        assert stored_panel_layout(owner) is not AgentPanelLayout.ALL_TABS
        assert owner._agent_panels_grouped is False


def test_ladder_scope_and_titles() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert merged_panel_title_for_owner(owner) is None
        assert set_panel_layout(owner, AgentPanelLayout.MERGED) is True
        # The strip is visible with two tabs, so Merged names the tab.
        assert merged_panel_title_for_owner(owner) == "main"
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        assert merged_panel_title_for_owner(owner) == "All agents · every tab"
        assert sync_panel_grouped_bool(owner) is True


def test_all_tabs_scope_returns_every_row() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert set_panel_layout(owner, AgentPanelLayout.ALL_TABS) is True
        scoped = _scoped_agents_for_owner(owner, list(owner._agents_query_result))
        assert [r.raw_suffix for r in scoped] == ["a", "b", "c"]


# --- End-to-end ladder walk ------------------------------------------------


async def test_flag_on_oo_walks_ladder_and_oO_steps_back() -> None:
    """``oo`` steps forward along the ladder; ``oO`` steps back."""
    from sase.ace.testing import AcePage
    from textual.widgets import Static

    with override_flags(agent_tabs=True):
        async with AcePage(initial_tab="agents") as page:
            rows = [
                _row("a", tribe="alpha"),
                _row("b", tab="sase", tribe="alpha"),
                _row("c", tab="sase", tribe="beta"),
            ]
            page.app._agents = list(rows)
            page.app._agents_with_children = list(rows)
            page.app._agents_query_result = list(rows)
            page.app.current_idx = 0
            page.app._invalidate_agent_panel_cache()
            page.app._refresh_agent_tab_index()
            page.app._rescope_agents_to_active_tab()
            await page.pause()
            assert [r.raw_suffix for r in page.app._agents] == ["a"]

            await page.press("o")
            await page.expect_modal("AgentGroupingModal")
            layout_text = (
                page.app.screen.query_one("#agent-panel-layout-row", Static)
                .render()
                .plain
            )
            assert "All tabs" in layout_text
            await page.press("o")
            await page.expect_no_modal()
            await page.wait_for(lambda _s: page.app._agent_panels_grouped is True)
            assert [r.raw_suffix for r in page.app._agents] == ["a"]

            await page.press("o", "o")
            await page.expect_no_modal()
            await page.wait_for(
                lambda _s: [r.raw_suffix for r in page.app._agents] == ["a", "b", "c"]
            )
            assert stored_panel_layout(page.app) is AgentPanelLayout.ALL_TABS
            assert current_agent_tab_scope_token(page.app) == "all"

            await page.press("o", "O")
            await page.expect_no_modal()
            await page.wait_for(
                lambda _s: stored_panel_layout(page.app) is AgentPanelLayout.MERGED
            )
            # Zooming in from All tabs lands on the selected node's tab.
            assert [r.raw_suffix for r in page.app._agents] == ["a"]


# --- Titles, chips, and strip state ----------------------------------------


def test_merged_border_title_uses_tab_label() -> None:
    from sase.ace.tui.actions.agents._display_panel_titles import (
        agent_panel_border_title,
    )

    merged = agent_panel_border_title(None, 14, merge_tribe_panels=True)
    assert merged.plain == "All agents · 14"
    named = agent_panel_border_title(
        None, 14, merge_tribe_panels=True, merged_title="sase"
    )
    assert named.plain == "sase · 14"
    every = agent_panel_border_title(
        None, 40, merge_tribe_panels=True, merged_title="All agents · every tab"
    )
    assert every.plain == "All agents · every tab · 40"


def test_info_row_panel_chip() -> None:
    from unittest.mock import patch

    from tests.ace.tui.widgets._agent_info_panel_helpers import (
        collect_text,
        stable_state_kwargs,
    )
    from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel

    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_panel_layout("merged")
    assert "panels: " in collect_text(panel)
    assert "merged" in collect_text(panel)
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(panel_layout="all tabs"))  # type: ignore[arg-type]
    assert "all tabs" in collect_text(panel)
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(panel_layout=""))  # type: ignore[arg-type]
    assert "panels:" not in collect_text(panel)


def test_all_tabs_strip_state_has_no_pill() -> None:
    from sase.ace.tui.models.agent_tab_descriptors import project_agent_tab_descriptors
    from sase.ace.tui.widgets.agent_tab_strip import AgentTabStrip

    rows = [_row("a"), _row("b", tab="sase")]
    index = build_agent_tab_index(rows, _view())
    descriptors = project_agent_tab_descriptors(
        tuple(index.catalog), rows, index.key_for, active_key=None
    )
    strip = AgentTabStrip(descriptors, None, _probe_only=True)
    plain = strip._build_content("full").plain
    assert "▐" not in plain and "▌" not in plain
    assert "sase" in plain and "main" in plain


def test_row_prefix_renders_tab_chip_before_tribe() -> None:
    from sase.ace.tui.widgets._agent_list_render_agent_prefix import (
        append_agent_row_prefix,
    )

    agent = _row("a", tab="sase", tribe="backend")
    prefix = append_agent_row_prefix(
        agent,
        is_selected=False,
        tribe_label="backend",
        tab_chip=("sase", "bold #AF87FF"),
    )
    plain = prefix.plain
    assert "[sase]" in plain
    assert plain.index("[sase]") < plain.index("@backend")
    bare = append_agent_row_prefix(agent, is_selected=False, tribe_label="backend")
    assert "[sase]" not in bare.plain


def test_tab_chip_helper_only_chips_named_tabs() -> None:
    from sase.ace.tui.widgets.agent_tab_strip import agent_tab_chip_for_key

    chip = agent_tab_chip_for_key(AgentTabKey.named("sase"))
    assert chip is not None and chip[0] == "sase"
    assert agent_tab_chip_for_key(DEFAULT_AGENT_TAB_KEY) is None
    assert agent_tab_chip_for_key(AgentTabKey.machine("install-id")) is None


def test_roster_entries_carry_off_tab_chips() -> None:
    from sase.ace.tui.models.agent_tribe_summary import (
        build_agent_tribe_summary_snapshot,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_tribe_roster import (
        tribe_roster_entries,
    )

    rows = [_row("a", tribe="alpha"), _row("b", tab="sase", tribe="alpha")]
    snapshot = build_agent_tribe_summary_snapshot(
        "alpha",
        rows,
        panel_collapsed=False,
        tab_chips={rows[1].identity: ("sase", "bold #AF87FF")},
    )
    entries = tribe_roster_entries(snapshot)
    by_identity = {entry.identity: entry for entry in entries}
    assert by_identity[rows[1].identity].tab_chip == ("sase", "bold #AF87FF")
    assert by_identity[rows[0].identity].tab_chip is None


def test_roster_member_fields_render_tab_chip() -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.prompt_panel._member_roster import _append_member_fields

    text = Text()
    _append_member_fields(
        text,
        label="agent",
        kind="agent",
        status="RUNNING",
        effective_bucket=None,
        model="default",
        duration="1m",
        annotations=(),
        status_counts=None,
        is_marked=False,
        is_unread=False,
        is_dismissed=False,
        tab_chip=("sase", "bold #AF87FF"),
    )
    assert "[sase]" in text.plain
