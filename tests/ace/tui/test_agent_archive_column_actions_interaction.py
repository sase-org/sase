"""Archive column action tests for the pulse, widget events, and selection survival."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_controller import refresh_archive_inbox_pulse
from sase.ace.tui.actions.agents._core import _AgentArchiveColumnMixin
from sase.ace.tui.actions.agents._archive_view import (
    archive_read_only_context,
    close_agents_archive_view,
    get_agents_tab_selection,
    route_archive_key,
)
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_NONE,
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
    INTENT_ACTIVATE,
    INTENT_COLLAPSE,
    INTENT_DOWN,
    INTENT_EXPAND,
    INTENT_FIRST,
    INTENT_LAST,
    INTENT_SWITCH_SECTION,
    INTENT_UP,
)
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_actions_helpers import (
    history_rows,
    opened,
    selection_key,
)


# The Textual handlers are the widget-facing entry points; they only use ``self``
# as the app, so a duck-typed owner can stand in for the mixin instance.
def _widget_cursor_moved(owner: Any, key: str) -> None:
    _AgentArchiveColumnMixin.on_archive_list_cursor_moved(
        owner, SimpleNamespace(key=key)
    )


def _widget_item_activated(owner: Any, key: str) -> None:
    _AgentArchiveColumnMixin.on_archive_list_item_activated(
        owner, SimpleNamespace(key=key)
    )


def _widget_pulse_activated(owner: Any) -> None:
    _AgentArchiveColumnMixin.on_archive_pulse_activated(owner, SimpleNamespace())


# --- pulse and sections -----------------------------------------------------


async def test_J_and_K_switch_pulse_and_list_focus_without_moving_the_inbox() -> None:
    harness = await opened()
    owner = harness.owner
    owner.current_idx = 4
    key = selection_key(harness)

    route_archive_key(owner, INTENT_SWITCH_SECTION)
    assert harness.archive.focused_section == ARCHIVE_SECTION_PULSE
    assert harness.widget.sections[-1] == ARCHIVE_SECTION_PULSE
    route_archive_key(owner, INTENT_DOWN)  # j/k stay inside the list
    route_archive_key(owner, INTENT_UP)
    assert selection_key(harness) == key
    route_archive_key(owner, INTENT_SWITCH_SECTION)
    assert harness.archive.focused_section == ARCHIVE_SECTION_LIST
    assert harness.widget.sections[-1] == ARCHIVE_SECTION_LIST
    assert owner.current_idx == 4
    assert selection_key(harness) == key


async def test_enter_l_or_click_on_the_pulse_returns_to_the_parked_inbox() -> None:
    for how in ("enter", "l", "click"):
        harness = await opened()
        owner = harness.owner
        owner.current_idx = 3
        owner._agents_archive_view.parked_inbox.scroll = 3
        route_archive_key(owner, INTENT_SWITCH_SECTION)

        if how == "enter":
            route_archive_key(owner, INTENT_ACTIVATE)
        elif how == "l":
            route_archive_key(owner, INTENT_EXPAND)
        else:
            _widget_pulse_activated(owner)

        assert owner._agents_archive_view.active_view == AGENTS_VIEW_INBOX, how
        assert owner.current_idx == 3
        # Reopening the Archive lands on its list, not the pulse.
        assert harness.archive.focused_section == ARCHIVE_SECTION_LIST


async def test_pulse_updates_live_without_rebuilding_the_list_or_resetting_detail() -> (
    None
):
    harness = await opened()
    owner = harness.owner
    paints = len(harness.widget.paints)
    scheduled = len(owner._agent_detail_debouncer.callbacks)
    pulses = len(harness.widget.pulses)

    owner._unread_completed_agent_ids = {("a", "b", "c")}
    refresh_archive_inbox_pulse(owner)

    assert len(harness.widget.paints) == paints
    assert len(owner._agent_detail_debouncer.callbacks) == scheduled
    assert len(harness.widget.pulses) == pulses + 1
    assert harness.widget.pulses[-1].unread == 1


# --- widget events and echo guards -----------------------------------------


async def test_widget_cursor_events_update_state_without_echoing_back() -> None:
    harness = await opened()
    owner = harness.owner
    echoes = len(harness.widget.cursors)

    _widget_cursor_moved(owner, "u.m@t05")

    assert selection_key(harness) == "u.m@t05"
    assert len(harness.widget.cursors) == echoes  # state only: no set_cursor


async def test_click_activation_matches_the_keyboard_path() -> None:
    harness = await opened()
    owner = harness.owner

    _widget_item_activated(owner, "banner:day:2026-10-10")
    assert "> Today (40)" in harness.widget.last_labels()
    _widget_item_activated(owner, "banner:day:2026-10-10")
    assert "v Today (40)" in harness.widget.last_labels()
    _widget_item_activated(owner, "u.m@t03")  # a plain run: select, nothing more
    assert selection_key(harness) == "u.m@t03"


# --- selection survival -----------------------------------------------------


async def test_cursor_survives_a_rebuild_and_falls_to_a_neighbor_when_row_vanishes() -> (
    None
):
    harness = await opened()
    owner = harness.owner
    for _ in range(3):
        route_archive_key(owner, INTENT_DOWN)
    assert selection_key(harness) == "u.m@t03"

    harness.corpus.all_rows = [
        row for row in harness.corpus.all_rows if row["agent_name"] != "agent-t03"
    ]
    from sase.ace.tui.actions.agents._archive_controller import (
        request_archive_view_load,
    )

    owner._archive_probe_tokens = lambda: __import__(
        "tests.ace.tui._agent_archive_column_helpers", fromlist=["tokens"]
    ).tokens(indexed_rows=1)
    request_archive_view_load(owner)
    await harness.settle()

    assert selection_key(harness) == "u.m@t04"
    assert harness.widget.last_labels().count("u.m@t03") == 0

    route_archive_key(owner, INTENT_FIRST)
    request_archive_view_load(owner)
    await harness.settle()
    assert selection_key(harness) == "banner:day:2026-10-10"  # banner cursor kept


async def test_selected_run_in_a_folded_banner_moves_to_the_banner() -> None:
    harness = await opened()
    owner = harness.owner
    route_archive_key(owner, INTENT_LAST)
    route_archive_key(owner, INTENT_EXPAND)
    await harness.settle()
    route_archive_key(owner, INTENT_DOWN)
    assert selection_key(harness) == "u.m@w00"
    route_archive_key(owner, INTENT_COLLAPSE)  # to the banner
    route_archive_key(owner, INTENT_COLLAPSE)  # fold it

    assert selection_key(harness) == "banner:week:2026-09-21"


__all__ = [
    "test_J_and_K_switch_pulse_and_list_focus_without_moving_the_inbox",
    "test_enter_l_or_click_on_the_pulse_returns_to_the_parked_inbox",
    "test_pulse_updates_live_without_rebuilding_the_list_or_resetting_detail",
    "test_widget_cursor_events_update_state_without_echoing_back",
    "test_click_activation_matches_the_keyboard_path",
    "test_cursor_survives_a_rebuild_and_falls_to_a_neighbor_when_row_vanishes",
    "test_selected_run_in_a_folded_banner_moves_to_the_banner",
]
