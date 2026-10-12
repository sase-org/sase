"""Archive column action tests for the list, navigation, folds, paging, and containers."""

from __future__ import annotations

from sase.ace.tui.actions.agents._archive_column import (
    archive_container_members,
    archive_light_row,
)
from sase.ace.tui.actions.agents._archive_view import (
    archive_read_only_context,
    close_agents_archive_view,
    get_agents_tab_selection,
    open_agents_archive_view,
    route_archive_key,
)
from sase.ace.tui.models.agent_archive_view import (
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    ARCHIVE_ROW_NONE,
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
    clan_rows,
    history_rows,
    opened,
    selection_key,
)
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness, light_row

# --- first paint ------------------------------------------------------------


async def test_cold_open_lists_open_banners_with_core_rows_and_selects_first_run() -> (
    None
):
    harness = await opened()

    labels = harness.widget.last_labels()
    assert labels[0] == "v Today (40)"
    assert labels[1] == "u.m@t00"
    assert "v Yesterday (40)" in labels
    assert labels[-1] == "> Sep 21-27 (40)"  # older banners default folded
    assert selection_key(harness) == "u.m@t00"
    assert harness.widget.paints[-1]["cursor"] == "u.m@t00"
    assert harness.widget.paints[-1]["grouping"] == "day"
    # Only the open banners' pages were requested from the corpus.
    assert {call["group_key"] for call in harness.corpus.rows_calls} == {
        "2026-10-10",
        "2026-10-09",
    }


async def test_scope_token_is_stripped_before_every_corpus_call() -> None:
    harness = await opened()

    assert harness.corpus.queries
    assert all("in:" not in query for query in harness.corpus.queries)


async def test_small_complete_result_opens_every_banner() -> None:
    rows = [light_row(f"a{i}", day="2026-10-10") for i in range(3)] + [
        light_row(f"b{i}", day="2026-07-15") for i in range(2)
    ]
    harness = await opened(rows)

    labels = harness.widget.last_labels()
    assert labels.count("v Today (3)") == 1
    assert any(label.startswith("v July 2026") for label in labels)
    assert "u.m@b1" in labels


async def test_warm_reopen_needs_one_corpus_round_trip() -> None:
    harness = await opened()
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


async def test_open_routes_and_paints_without_a_flag() -> None:
    harness = ColumnHarness(history_rows())
    with override_flags():
        harness.note_inbox_applied()
        outcome = open_agents_archive_view(harness.owner)
        await harness.settle()

        assert outcome.status == "opened"
        assert route_archive_key(harness.owner, INTENT_DOWN) is True
        assert harness.widget.paints != []
        assert harness.corpus.summary_calls > 0


async def test_keys_fall_through_to_the_inbox_when_it_owns_the_tab() -> None:
    harness = await opened()
    close_agents_archive_view(harness.owner)

    assert route_archive_key(harness.owner, INTENT_DOWN) is False
    harness.owner.current_tab = "artifacts"
    open_agents_archive_view(harness.owner)
    assert route_archive_key(harness.owner, INTENT_DOWN) is False
    await harness.settle()


# --- navigation -------------------------------------------------------------


async def test_j_k_g_G_walk_banners_and_rows_without_wrapping() -> None:
    harness = await opened()
    owner = harness.owner

    assert route_archive_key(owner, INTENT_FIRST)
    assert selection_key(harness) == "banner:day:2026-10-10"
    assert route_archive_key(owner, INTENT_UP)
    assert selection_key(harness) == "banner:day:2026-10-10"  # clamps
    assert route_archive_key(owner, INTENT_DOWN)
    assert selection_key(harness) == "u.m@t00"
    assert route_archive_key(owner, INTENT_LAST)
    assert selection_key(harness) == "banner:week:2026-09-21"
    assert route_archive_key(owner, INTENT_DOWN)
    assert selection_key(harness) == "banner:week:2026-09-21"  # clamps
    assert route_archive_key(owner, INTENT_UP)
    assert selection_key(harness) == "u.m@y39"

    # Programmatic highlight updates only; no widget-originated echo.
    assert harness.widget.cursors[-1] == "u.m@y39"
    assert harness.widget.cursors[:2] == [
        "banner:day:2026-10-10",
        "banner:day:2026-10-10",
    ]


async def test_navigation_never_touches_inbox_state() -> None:
    harness = await opened()
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
    harness = await opened()
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
    harness = await opened()
    owner = harness.owner
    route_archive_key(owner, INTENT_LAST)
    assert selection_key(harness) == "banner:week:2026-09-21"

    route_archive_key(owner, INTENT_EXPAND)
    await harness.settle()
    labels = harness.widget.last_labels()
    assert "v Sep 21-27 (40)" in labels
    assert labels[labels.index("v Sep 21-27 (40)") + 1] == "u.m@w00"
    assert harness.archive.expanded_banners == ("week:2026-09-21",)

    # Folding a default-open banner is an explicit override that survives
    # later controller refreshes.
    route_archive_key(owner, INTENT_FIRST)
    assert selection_key(harness) == "banner:day:2026-10-10"
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
    harness = await opened()
    owner = harness.owner
    route_archive_key(owner, INTENT_DOWN)
    assert selection_key(harness) == "u.m@t01"

    route_archive_key(owner, INTENT_COLLAPSE)  # on a plain run: up to its banner
    assert selection_key(harness) == "banner:day:2026-10-10"
    route_archive_key(owner, INTENT_COLLAPSE)  # on the open banner: fold it
    assert selection_key(harness) == "banner:day:2026-10-10"
    assert not any(k == "u.m@t01" for k in harness.widget.last_labels())

    route_archive_key(owner, INTENT_ACTIVATE)  # Enter toggles it open again
    assert "v Today (40)" in harness.widget.last_labels()


async def test_l_on_an_open_banner_steps_onto_its_first_run() -> None:
    harness = await opened()
    owner = harness.owner
    route_archive_key(owner, INTENT_FIRST)

    route_archive_key(owner, INTENT_EXPAND)

    assert selection_key(harness) == "u.m@t00"


# --- paging -----------------------------------------------------------------


async def test_banner_pages_load_100_rows_and_enter_or_l_requests_the_next() -> None:
    rows = [light_row(f"p{i:03d}", hour=(i // 10) % 24 or 1) for i in range(250)]
    # Newest first, as the corpus orders them.
    rows.sort(key=lambda r: r["last_activity_at"], reverse=True)
    harness = await opened(rows)
    owner = harness.owner
    labels = harness.widget.last_labels()
    assert sum(1 for label in labels if label.startswith("u.m@")) == 100
    assert labels[-1] == "tail 150"
    assert harness.corpus.rows_calls[-1]["limit"] == 100

    route_archive_key(owner, INTENT_LAST)
    assert selection_key(harness) == "tail:day:2026-10-10"
    route_archive_key(owner, INTENT_ACTIVATE)
    await harness.settle()

    labels = harness.widget.last_labels()
    assert sum(1 for label in labels if label.startswith("u.m@")) == 200
    assert labels[-1] == "tail 50"
    assert harness.corpus.rows_calls[-1]["limit"] == 200
    # The cursor moved onto the first newly loaded row, not the old tail.
    assert selection_key(harness) == harness.widget.last_items[101].key

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
    harness = await opened(rows)
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


async def test_containers_expand_collapse_and_report_matching_members_only() -> None:
    harness = await opened(clan_rows())
    owner = harness.owner
    labels = harness.widget.last_labels()
    assert labels == [
        "v Today (2)",
        "container:clan:swarm:1",
        "u.m@solo",
    ]
    assert harness.widget.last_items[1].count == 3
    assert selection_key(harness) == "container:clan:swarm:1"
    selection = get_agents_tab_selection(owner)
    assert selection.row_kind == ARCHIVE_ROW_CONTAINER
    assert selection.light_row is not None and selection.light_row["container"] is True

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
    assert selection_key(harness) == "u.m@m2"
    route_archive_key(owner, INTENT_COLLAPSE)  # a member collapses its parent
    await harness.settle()
    assert selection_key(harness) == "container:clan:swarm:1"
    assert harness.archive.expanded_containers == ()
    assert harness.widget.last_labels()[2] == "u.m@solo"
    assert archive_container_members(owner, "clan:swarm:1") == ()


async def test_container_enter_toggles_and_workflow_children_stay_out_of_the_list() -> (
    None
):
    rows = clan_rows()
    harness = await opened(rows)
    owner = harness.owner

    route_archive_key(owner, INTENT_EXPAND)
    await harness.settle()
    assert "u.m@m1" in harness.widget.last_labels()
    route_archive_key(owner, INTENT_COLLAPSE)
    await harness.settle()
    assert "u.m@m1" not in harness.widget.last_labels()
    # No row is ever fabricated for an agent the corpus did not list.
    assert not any("child" in label for label in harness.widget.last_labels())


async def test_container_enter_does_not_toggle_expansion() -> None:
    rows = clan_rows()
    harness = await opened(rows)
    owner = harness.owner

    assert selection_key(harness) == "container:clan:swarm:1"
    assert harness.archive.expanded_containers == ()
    route_archive_key(owner, INTENT_ACTIVATE)
    await harness.settle()
    assert harness.archive.expanded_containers == ()
    assert "u.m@m1" not in harness.widget.last_labels()


async def test_h_on_expanded_container_collapses_in_place() -> None:
    harness = await opened(clan_rows())
    owner = harness.owner
    route_archive_key(owner, INTENT_EXPAND)
    await harness.settle()
    assert selection_key(harness) == "container:clan:swarm:1"
    assert harness.archive.expanded_containers == ("clan:swarm:1",)
    assert "u.m@m1" in harness.widget.last_labels()

    route_archive_key(owner, INTENT_COLLAPSE)
    await harness.settle()
    assert selection_key(harness) == "container:clan:swarm:1"
    assert harness.archive.expanded_containers == ()
    assert "u.m@m1" not in harness.widget.last_labels()
    assert archive_container_members(owner, "clan:swarm:1") == ()


__all__ = [
    "test_cold_open_lists_open_banners_with_core_rows_and_selects_first_run",
    "test_scope_token_is_stripped_before_every_corpus_call",
    "test_small_complete_result_opens_every_banner",
    "test_warm_reopen_needs_one_corpus_round_trip",
    "test_open_routes_and_paints_without_a_flag",
    "test_keys_fall_through_to_the_inbox_when_it_owns_the_tab",
    "test_j_k_g_G_walk_banners_and_rows_without_wrapping",
    "test_navigation_never_touches_inbox_state",
    "test_selection_types_distinguish_banners_runs_and_the_pulse",
    "test_l_opens_a_folded_banner_h_folds_and_user_folds_stick",
    "test_folding_parks_the_cursor_on_the_banner",
    "test_l_on_an_open_banner_steps_onto_its_first_run",
    "test_banner_pages_load_100_rows_and_enter_or_l_requests_the_next",
    "test_multi_group_banner_pages_across_its_component_days",
    "test_containers_expand_collapse_and_report_matching_members_only",
    "test_container_enter_does_not_toggle_expansion",
    "test_container_enter_toggles_and_workflow_children_stay_out_of_the_list",
    "test_h_on_expanded_container_collapses_in_place",
]
