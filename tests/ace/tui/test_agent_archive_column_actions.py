"""Archive column glue: paging, folds, navigation, sections, and Inbox isolation.

Drives the real controller and list model against an in-memory corpus that
follows the Rust contract (root counts in summaries, flattened ``total`` and
member rows in windows) with a fake widget and a deterministic spawn.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_column import (
    archive_container_members,
    archive_light_row,
)
from sase.ace.tui.actions.agents._archive_controller import (
    archive_corpus_snapshot,
    refresh_archive_inbox_pulse,
)
from sase.ace.tui.actions.agents._archive_view import (
    AgentArchiveColumnMixin,
    archive_read_only_context,
    close_agents_archive_view,
    get_agents_tab_selection,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
    route_archive_key,
)
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    INTENT_ACTIVATE,
    INTENT_COLLAPSE,
    INTENT_DOWN,
    INTENT_EXPAND,
    INTENT_FIRST,
    INTENT_LAST,
    INTENT_SWITCH_SECTION,
    INTENT_UP,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    ARCHIVE_ROW_NONE,
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
)
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness, light_row


def _history_rows() -> list[dict[str, Any]]:
    """120 runs: 40 today, 40 yesterday, 40 on a day two weeks back."""
    rows: list[dict[str, Any]] = []
    for day, tag in (("2026-10-10", "t"), ("2026-10-09", "y"), ("2026-09-26", "w")):
        for index in range(40):
            rows.append(light_row(f"{tag}{index:02d}", day=day, hour=23 - (index % 20)))
    return rows


async def _opened(
    rows: list[dict[str, Any]] | None = None, **kwargs: Any
) -> ColumnHarness:
    harness = ColumnHarness(rows if rows is not None else _history_rows(), **kwargs)
    harness.note_inbox_applied()
    open_agents_archive_view(harness.owner)
    await harness.settle()
    return harness


def _selection_key(harness: ColumnHarness) -> str | None:
    return harness.archive.selected_key


# The Textual handlers are the widget-facing entry points; they only use ``self``
# as the app, so a duck-typed owner can stand in for the mixin instance.
def _widget_cursor_moved(owner: Any, key: str) -> None:
    AgentArchiveColumnMixin.on_archive_list_cursor_moved(
        owner, SimpleNamespace(key=key)
    )


def _widget_item_activated(owner: Any, key: str) -> None:
    AgentArchiveColumnMixin.on_archive_list_item_activated(
        owner, SimpleNamespace(key=key)
    )


def _widget_pulse_activated(owner: Any) -> None:
    AgentArchiveColumnMixin.on_archive_pulse_activated(owner, SimpleNamespace())


# --- first paint ------------------------------------------------------------


async def test_cold_open_lists_open_banners_with_core_rows_and_selects_first_run() -> (
    None
):
    with override_flags(agents_archive_view=True):
        harness = await _opened()

        labels = harness.widget.last_labels()
        assert labels[0] == "v Today (40)"
        assert labels[1] == "u.m@t00"
        assert "v Yesterday (40)" in labels
        assert labels[-1] == "> Sep 21-27 (40)"  # older banners default folded
        assert _selection_key(harness) == "u.m@t00"
        assert harness.widget.paints[-1]["cursor"] == "u.m@t00"
        assert harness.widget.paints[-1]["grouping"] == "day"
        # Only the open banners' pages were requested from the corpus.
        assert {call["group_key"] for call in harness.corpus.rows_calls} == {
            "2026-10-10",
            "2026-10-09",
        }


async def test_scope_token_is_stripped_before_every_corpus_call() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()

        assert harness.corpus.queries
        assert all("in:" not in query for query in harness.corpus.queries)


async def test_small_complete_result_opens_every_banner() -> None:
    rows = [light_row(f"a{i}", day="2026-10-10") for i in range(3)] + [
        light_row(f"b{i}", day="2026-07-15") for i in range(2)
    ]
    with override_flags(agents_archive_view=True):
        harness = await _opened(rows)

        labels = harness.widget.last_labels()
        assert labels.count("v Today (3)") == 1
        assert any(label.startswith("v July 2026") for label in labels)
        assert "u.m@b1" in labels


async def test_warm_reopen_needs_one_corpus_round_trip() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        close_agents_archive_view(harness.owner)
        summaries = harness.corpus.summary_calls
        row_calls = len(harness.corpus.rows_calls)
        paints = len(harness.widget.paints)

        open_agents_archive_view(harness.owner)
        spawned = len(harness.spawn.coros)
        await harness.settle()

        assert spawned == 1  # summary and windows travel in one request
        assert harness.corpus.summary_calls == summaries + 1
        assert len(harness.corpus.rows_calls) == row_calls + 2
        assert len(harness.widget.paints) > paints
        assert harness.widget.last_labels()[0] == "v Today (40)"
        assert harness.widget.reveals >= 1


async def test_flag_off_routes_nothing_and_paints_nothing() -> None:
    harness = ColumnHarness(_history_rows())
    with override_flags():
        harness.note_inbox_applied()
        outcome = open_agents_archive_view(harness.owner)
        await harness.settle()

        assert outcome.status == "disabled"
        for intent in (
            INTENT_DOWN,
            INTENT_UP,
            INTENT_FIRST,
            INTENT_LAST,
            INTENT_EXPAND,
        ):
            assert route_archive_key(harness.owner, intent) is False
        assert harness.widget.paints == []
        assert harness.corpus.summary_calls == 0


async def test_keys_fall_through_to_the_inbox_when_it_owns_the_tab() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        close_agents_archive_view(harness.owner)

        assert route_archive_key(harness.owner, INTENT_DOWN) is False
        harness.owner.current_tab = "artifacts"
        open_agents_archive_view(harness.owner)
        assert route_archive_key(harness.owner, INTENT_DOWN) is False
        await harness.settle()


# --- navigation -------------------------------------------------------------


async def test_j_k_g_G_walk_banners_and_rows_without_wrapping() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner

        assert route_archive_key(owner, INTENT_FIRST)
        assert _selection_key(harness) == "banner:day:2026-10-10"
        assert route_archive_key(owner, INTENT_UP)
        assert _selection_key(harness) == "banner:day:2026-10-10"  # clamps
        assert route_archive_key(owner, INTENT_DOWN)
        assert _selection_key(harness) == "u.m@t00"
        assert route_archive_key(owner, INTENT_LAST)
        assert _selection_key(harness) == "banner:week:2026-09-21"
        assert route_archive_key(owner, INTENT_DOWN)
        assert _selection_key(harness) == "banner:week:2026-09-21"  # clamps
        assert route_archive_key(owner, INTENT_UP)
        assert _selection_key(harness) == "u.m@y39"

        # Programmatic highlight updates only; no widget-originated echo.
        assert harness.widget.cursors[-1] == "u.m@y39"
        assert harness.widget.cursors[:2] == [
            "banner:day:2026-10-10",
            "banner:day:2026-10-10",
        ]


async def test_navigation_never_touches_inbox_state() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        owner.current_idx = 7
        agents_before = owner._agents

        for intent in (INTENT_DOWN, INTENT_DOWN, INTENT_LAST, INTENT_FIRST):
            route_archive_key(owner, intent)
        route_archive_key(owner, INTENT_SWITCH_SECTION)

        assert owner.current_idx == 7
        assert owner._agents is agents_before
        assert owner._agents == []
        parked = owner._agents_archive_view.parked_inbox
        assert parked is not None and parked.scroll == 0


async def test_selection_types_distinguish_banners_runs_and_the_pulse() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner

        selection = get_agents_tab_selection(owner)
        assert selection.row_kind == ARCHIVE_ROW_AGENT
        assert selection.archive_key == "u.m@t00"
        assert selection.read_only and selection.provenance == "archive"
        assert selection.light_row is not None
        assert selection.light_row["agent_name"] == "agent-t00"
        assert archive_read_only_context(owner) is not None

        route_archive_key(owner, INTENT_FIRST)
        banner = get_agents_tab_selection(owner)
        assert banner.row_kind == ARCHIVE_ROW_NONE
        assert banner.archive_key is None and banner.agent is None
        assert archive_read_only_context(owner) is None

        route_archive_key(owner, INTENT_DOWN)
        route_archive_key(owner, INTENT_SWITCH_SECTION)
        pulse = get_agents_tab_selection(owner)
        assert pulse.row_kind == ARCHIVE_ROW_NONE and pulse.read_only
        assert archive_read_only_context(owner) is None
        assert archive_light_row(owner, "u.m@t00") is not None
        assert archive_light_row(owner, "banner:day:2026-10-10") is None


# --- folds ------------------------------------------------------------------


async def test_l_opens_a_folded_banner_h_folds_and_user_folds_stick() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        route_archive_key(owner, INTENT_LAST)
        assert _selection_key(harness) == "banner:week:2026-09-21"

        route_archive_key(owner, INTENT_EXPAND)
        await harness.settle()
        labels = harness.widget.last_labels()
        assert "v Sep 21-27 (40)" in labels
        assert labels[labels.index("v Sep 21-27 (40)") + 1] == "u.m@w00"
        assert harness.archive.expanded_banners == ("week:2026-09-21",)

        # Folding a default-open banner is an explicit override that survives
        # later controller refreshes.
        route_archive_key(owner, INTENT_FIRST)
        assert _selection_key(harness) == "banner:day:2026-10-10"
        route_archive_key(owner, INTENT_COLLAPSE)
        assert harness.archive.folded_banners == ("day:2026-10-10",)
        assert "> Today (40)" in harness.widget.last_labels()
        close_agents_archive_view(owner)
        open_agents_archive_view(owner)
        await harness.settle()
        labels = harness.widget.last_labels()
        assert "> Today (40)" in labels and "v Yesterday (40)" in labels
        assert "v Sep 21-27 (40)" in labels


async def test_folding_parks_the_cursor_on_the_banner() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        route_archive_key(owner, INTENT_DOWN)
        assert _selection_key(harness) == "u.m@t01"

        route_archive_key(owner, INTENT_COLLAPSE)  # on a plain run: up to its banner
        assert _selection_key(harness) == "banner:day:2026-10-10"
        route_archive_key(owner, INTENT_COLLAPSE)  # on the open banner: fold it
        assert _selection_key(harness) == "banner:day:2026-10-10"
        assert not any(k == "u.m@t01" for k in harness.widget.last_labels())

        route_archive_key(owner, INTENT_ACTIVATE)  # Enter toggles it open again
        assert "v Today (40)" in harness.widget.last_labels()


async def test_l_on_an_open_banner_steps_onto_its_first_run() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        route_archive_key(owner, INTENT_FIRST)

        route_archive_key(owner, INTENT_EXPAND)

        assert _selection_key(harness) == "u.m@t00"


# --- paging -----------------------------------------------------------------


async def test_banner_pages_load_100_rows_and_enter_or_l_requests_the_next() -> None:
    rows = [light_row(f"p{i:03d}", hour=(i // 10) % 24 or 1) for i in range(250)]
    # Newest first, as the corpus orders them.
    rows.sort(key=lambda r: r["last_activity_at"], reverse=True)
    with override_flags(agents_archive_view=True):
        harness = await _opened(rows)
        owner = harness.owner
        labels = harness.widget.last_labels()
        assert sum(1 for label in labels if label.startswith("u.m@")) == 100
        assert labels[-1] == "tail 150"
        assert harness.corpus.rows_calls[-1]["limit"] == 100

        route_archive_key(owner, INTENT_LAST)
        assert _selection_key(harness) == "tail:day:2026-10-10"
        route_archive_key(owner, INTENT_ACTIVATE)
        await harness.settle()

        labels = harness.widget.last_labels()
        assert sum(1 for label in labels if label.startswith("u.m@")) == 200
        assert labels[-1] == "tail 50"
        assert harness.corpus.rows_calls[-1]["limit"] == 200
        # The cursor moved onto the first newly loaded row, not the old tail.
        assert _selection_key(harness) == harness.widget.last_items[101].key

        route_archive_key(owner, INTENT_LAST)
        route_archive_key(owner, INTENT_EXPAND)  # `l` on the tail pages too
        await harness.settle()
        labels = harness.widget.last_labels()
        assert sum(1 for label in labels if label.startswith("u.m@")) == 250
        assert not any(label.startswith("tail") for label in labels)


async def test_multi_group_banner_pages_across_its_component_days() -> None:
    rows = [light_row(f"a{i:02d}", day="2026-09-30", hour=20) for i in range(60)] + [
        light_row(f"b{i:02d}", day="2026-09-29", hour=20) for i in range(70)
    ]
    with override_flags(agents_archive_view=True):
        harness = await _opened(rows)
        owner = harness.owner
        route_archive_key(owner, INTENT_FIRST)
        route_archive_key(owner, INTENT_EXPAND)  # week banner opens
        await harness.settle()

        labels = harness.widget.last_labels()
        assert labels[0] == "v Sep 28-Oct 4 (130)"
        assert sum(1 for label in labels if label.startswith("u.m@a")) == 60
        assert sum(1 for label in labels if label.startswith("u.m@b")) == 40
        assert labels[-1] == "tail 30"
        windows = [(c["group_key"], c["limit"]) for c in harness.corpus.rows_calls[-2:]]
        assert windows == [("2026-09-30", 100), ("2026-09-29", 40)]


# --- containers -------------------------------------------------------------


def _clan_rows() -> list[dict[str, Any]]:
    clan = "clan:swarm:1"
    return [
        light_row("m1", hour=22, name="swarm.one", container_key=clan),
        light_row("m2", hour=21, name="swarm.two", container_key=clan),
        light_row("m3", hour=20, name="swarm.three", container_key=clan),
        light_row("solo", hour=19, name="loner"),
    ]


async def test_containers_expand_collapse_and_report_matching_members_only() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened(_clan_rows())
        owner = harness.owner
        labels = harness.widget.last_labels()
        assert labels == [
            "v Today (2)",
            "container:clan:swarm:1",
            "u.m@solo",
        ]
        assert harness.widget.last_items[1].count == 3
        assert _selection_key(harness) == "container:clan:swarm:1"
        selection = get_agents_tab_selection(owner)
        assert selection.row_kind == ARCHIVE_ROW_CONTAINER
        assert (
            selection.light_row is not None and selection.light_row["container"] is True
        )

        route_archive_key(owner, INTENT_EXPAND)
        await harness.settle()
        assert harness.widget.last_labels() == [
            "v Today (2)",
            "container:clan:swarm:1",
            "u.m@m1",
            "u.m@m2",
            "u.m@m3",
            "u.m@solo",
        ]
        assert harness.archive.expanded_containers == ("clan:swarm:1",)
        assert harness.corpus.rows_calls[-1]["expanded"] == ("clan:swarm:1",)
        members = archive_container_members(owner, "clan:swarm:1")
        assert [m["archive_key"]["source_run_id"] for m in members] == [
            "m1",
            "m2",
            "m3",
        ]

        route_archive_key(owner, INTENT_DOWN)
        route_archive_key(owner, INTENT_DOWN)
        assert _selection_key(harness) == "u.m@m2"
        route_archive_key(owner, INTENT_COLLAPSE)  # a member collapses its parent
        await harness.settle()
        assert _selection_key(harness) == "container:clan:swarm:1"
        assert harness.archive.expanded_containers == ()
        assert harness.widget.last_labels()[2] == "u.m@solo"
        assert archive_container_members(owner, "clan:swarm:1") == ()


async def test_container_enter_toggles_and_workflow_children_stay_out_of_the_list() -> (
    None
):
    rows = _clan_rows()
    with override_flags(agents_archive_view=True):
        harness = await _opened(rows)
        owner = harness.owner

        route_archive_key(owner, INTENT_ACTIVATE)
        await harness.settle()
        assert "u.m@m1" in harness.widget.last_labels()
        route_archive_key(owner, INTENT_ACTIVATE)
        await harness.settle()
        assert "u.m@m1" not in harness.widget.last_labels()
        # No row is ever fabricated for an agent the corpus did not list.
        assert not any("child" in label for label in harness.widget.last_labels())


# --- pulse and sections -----------------------------------------------------


async def test_J_and_K_switch_pulse_and_list_focus_without_moving_the_inbox() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        owner.current_idx = 4
        key = _selection_key(harness)

        route_archive_key(owner, INTENT_SWITCH_SECTION)
        assert harness.archive.focused_section == ARCHIVE_SECTION_PULSE
        assert harness.widget.sections[-1] == ARCHIVE_SECTION_PULSE
        route_archive_key(owner, INTENT_DOWN)  # j/k stay inside the list
        route_archive_key(owner, INTENT_UP)
        assert _selection_key(harness) == key
        route_archive_key(owner, INTENT_SWITCH_SECTION)
        assert harness.archive.focused_section == ARCHIVE_SECTION_LIST
        assert harness.widget.sections[-1] == ARCHIVE_SECTION_LIST
        assert owner.current_idx == 4
        assert _selection_key(harness) == key


async def test_enter_l_or_click_on_the_pulse_returns_to_the_parked_inbox() -> None:
    with override_flags(agents_archive_view=True):
        for how in ("enter", "l", "click"):
            harness = await _opened()
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
    with override_flags(agents_archive_view=True):
        harness = await _opened()
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
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        echoes = len(harness.widget.cursors)

        _widget_cursor_moved(owner, "u.m@t05")

        assert _selection_key(harness) == "u.m@t05"
        assert len(harness.widget.cursors) == echoes  # state only: no set_cursor


async def test_click_activation_matches_the_keyboard_path() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner

        _widget_item_activated(owner, "banner:day:2026-10-10")
        assert "> Today (40)" in harness.widget.last_labels()
        _widget_item_activated(owner, "banner:day:2026-10-10")
        assert "v Today (40)" in harness.widget.last_labels()
        _widget_item_activated(owner, "u.m@t03")  # a plain run: select, nothing more
        assert _selection_key(harness) == "u.m@t03"


# --- selection survival -----------------------------------------------------


async def test_cursor_survives_a_rebuild_and_falls_to_a_neighbor_when_row_vanishes() -> (
    None
):
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        for _ in range(3):
            route_archive_key(owner, INTENT_DOWN)
        assert _selection_key(harness) == "u.m@t03"

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

        assert _selection_key(harness) == "u.m@t04"
        assert harness.widget.last_labels().count("u.m@t03") == 0

        route_archive_key(owner, INTENT_FIRST)
        request_archive_view_load(owner)
        await harness.settle()
        assert _selection_key(harness) == "banner:day:2026-10-10"  # banner cursor kept


async def test_selected_run_in_a_folded_banner_moves_to_the_banner() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner
        route_archive_key(owner, INTENT_LAST)
        route_archive_key(owner, INTENT_EXPAND)
        await harness.settle()
        route_archive_key(owner, INTENT_DOWN)
        assert _selection_key(harness) == "u.m@w00"
        route_archive_key(owner, INTENT_COLLAPSE)  # to the banner
        route_archive_key(owner, INTENT_COLLAPSE)  # fold it

        assert _selection_key(harness) == "banner:week:2026-09-21"


# --- exact arrival ----------------------------------------------------------


async def test_exact_arrival_opens_the_banner_pages_to_the_run_and_selects_it() -> None:
    rows = _history_rows()
    # A run deep inside the (default-folded) older banner, past page one.
    target = rows[-1]
    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(rows)
        harness.note_inbox_applied()
        outcome = open_agents_archive_view_with_query(
            harness.owner,
            query="in:archive name:" + target["agent_name"],
            agent_name=target["agent_name"],
        )
        await harness.settle()

        assert outcome.exact_agent_name == target["agent_name"]
        assert _selection_key(harness) == "u.m@w39"
        assert harness.archive.reveal_row is None
        assert "v Sep 21-27 (40)" in harness.widget.last_labels()
        assert "u.m@w39" in harness.widget.last_labels()


async def test_exact_arrival_pages_until_the_row_is_loaded() -> None:
    rows = [light_row(f"p{i:03d}", hour=(i // 10) % 24 or 1) for i in range(250)]
    rows.sort(key=lambda r: r["last_activity_at"], reverse=True)
    target = rows[-1]  # last row of 250: only on page three
    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(rows)
        harness.note_inbox_applied()
        open_agents_archive_view_with_query(
            harness.owner,
            query="in:archive",
            agent_name=target["agent_name"],
        )
        await harness.settle()

        key = "u.m@" + target["archive_key"]["source_run_id"]
        assert _selection_key(harness) == key
        assert harness.archive.loaded_pages == {"day:2026-10-10": 3}
        assert key in harness.widget.last_labels()


async def test_exact_arrival_expands_the_owning_container() -> None:
    rows = _clan_rows()
    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(rows)
        harness.note_inbox_applied()
        open_agents_archive_view_with_query(
            harness.owner, query="in:archive", agent_name="swarm.two"
        )
        await harness.settle()

        assert _selection_key(harness) == "u.m@m2"
        assert harness.archive.expanded_containers == ("clan:swarm:1",)
        assert "u.m@m2" in harness.widget.last_labels()


async def test_exact_arrival_for_a_row_outside_the_query_gives_up_cleanly() -> None:
    rows = _history_rows()
    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(rows)
        harness.note_inbox_applied()
        open_agents_archive_view_with_query(
            harness.owner, query="in:archive", agent_name="agent-t01"
        )
        harness.corpus.all_rows = [
            row for row in rows if row["agent_name"] != "agent-t01"
        ]
        # The looked-up row is gone from this corpus: nothing to reveal.
        await harness.settle()

        assert harness.archive.reveal_row is None
        assert _selection_key(harness) is not None


# --- statuses ---------------------------------------------------------------


async def test_rebuilding_index_lists_indexed_rows_under_a_progress_note() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened(_clan_rows(), status="rebuilding")

        labels = harness.widget.last_labels()
        assert labels[0] == "~ Archive index rebuilding — 4 runs indexed so far"
        assert "v Today (2)" in labels
        assert archive_corpus_snapshot(harness.owner).status == "rebuilding"


async def test_unavailable_index_paints_the_rebuild_hint_and_nothing_else() -> None:
    from sase.ace.tui.models.agent_archive_controller import (
        ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    )

    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(_clan_rows())
        harness.owner._archive_get_corpus = lambda **kwargs: None
        harness.note_inbox_applied()
        open_agents_archive_view(harness.owner)
        await harness.settle()

        assert harness.widget.last_labels() == [
            f"~ {ARCHIVE_INDEX_UNAVAILABLE_MESSAGE}"
        ]
        assert get_agents_tab_selection(harness.owner).row_kind == ARCHIVE_ROW_NONE


async def test_loading_state_paints_a_loading_row_before_the_gate_opens() -> None:
    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(_history_rows())
        open_agents_archive_view(harness.owner)  # Inbox has not loaded yet

        assert harness.widget.last_labels() == ["~ Loading Archive…"]
        assert harness.corpus.summary_calls == 0
        harness.note_inbox_applied()
        await harness.settle()
        assert harness.widget.last_labels()[0] == "v Today (40)"


# --- detail seam ------------------------------------------------------------


async def test_cursor_moves_debounce_the_detail_paint_and_drop_stale_work() -> None:
    painted: list[str] = []
    with override_flags(agents_archive_view=True):
        harness = await _opened()
        owner = harness.owner

        import sase.ace.tui.actions.agents._archive_column as column_mod

        original = column_mod._paint_detail_placeholder
        column_mod._paint_detail_placeholder = lambda o: painted.append("paint")
        try:
            route_archive_key(owner, INTENT_DOWN)
            owner._agent_detail_debouncer.fire()
            assert painted == ["paint"]

            route_archive_key(owner, INTENT_DOWN)
            close_agents_archive_view(owner)  # the view switched before it fired
            owner._agent_detail_debouncer.fire()
            assert painted == ["paint"]
        finally:
            column_mod._paint_detail_placeholder = original
        assert owner._agents_archive_view.active_view == AGENTS_VIEW_INBOX


async def test_view_state_exposes_archive_view_constant_for_reading_callers() -> None:
    with override_flags(agents_archive_view=True):
        harness = await _opened()

        assert harness.owner._agents_archive_view.active_view == AGENTS_VIEW_ARCHIVE
        assert harness.widget.last_items
