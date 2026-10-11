"""Archive column action tests for exact arrivals, status rows, and detail work."""

from __future__ import annotations

from sase.ace.tui.actions.agents._archive_controller import archive_corpus_snapshot
from sase.ace.tui.actions.agents._archive_view import (
    close_agents_archive_view,
    get_agents_tab_selection,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
    route_archive_key,
)
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_NONE,
    INTENT_DOWN,
)
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_actions_helpers import (
    clan_rows,
    history_rows,
    opened,
    selection_key,
)
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness, light_row

# --- exact arrival ----------------------------------------------------------


async def test_exact_arrival_opens_the_banner_pages_to_the_run_and_selects_it() -> None:
    rows = history_rows()
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
        assert selection_key(harness) == "u.m@w39"
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
        assert selection_key(harness) == key
        assert harness.archive.loaded_pages == {"day:2026-10-10": 3}
        assert key in harness.widget.last_labels()


async def test_exact_arrival_expands_the_owning_container() -> None:
    rows = clan_rows()
    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(rows)
        harness.note_inbox_applied()
        open_agents_archive_view_with_query(
            harness.owner, query="in:archive", agent_name="swarm.two"
        )
        await harness.settle()

        assert selection_key(harness) == "u.m@m2"
        assert harness.archive.expanded_containers == ("clan:swarm:1",)
        assert "u.m@m2" in harness.widget.last_labels()


async def test_exact_arrival_for_a_row_outside_the_query_gives_up_cleanly() -> None:
    rows = history_rows()
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
        assert selection_key(harness) is not None


# --- statuses ---------------------------------------------------------------


async def test_rebuilding_index_lists_indexed_rows_under_a_progress_note() -> None:
    with override_flags(agents_archive_view=True):
        harness = await opened(clan_rows(), status="rebuilding")

        labels = harness.widget.last_labels()
        assert labels[0] == "~ Archive index rebuilding — 4 runs indexed so far"
        assert "v Today (2)" in labels
        assert archive_corpus_snapshot(harness.owner).status == "rebuilding"


async def test_unavailable_index_paints_the_rebuild_hint_and_nothing_else() -> None:
    from sase.ace.tui.models.agent_archive_controller import (
        ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    )

    with override_flags(agents_archive_view=True):
        harness = ColumnHarness(clan_rows())
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
        harness = ColumnHarness(history_rows())
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
        harness = await opened()
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
        harness = await opened()

        assert harness.owner._agents_archive_view.active_view == AGENTS_VIEW_ARCHIVE
        assert harness.widget.last_items


__all__ = [
    "test_exact_arrival_opens_the_banner_pages_to_the_run_and_selects_it",
    "test_exact_arrival_pages_until_the_row_is_loaded",
    "test_exact_arrival_expands_the_owning_container",
    "test_exact_arrival_for_a_row_outside_the_query_gives_up_cleanly",
    "test_rebuilding_index_lists_indexed_rows_under_a_progress_note",
    "test_unavailable_index_paints_the_rebuild_hint_and_nothing_else",
    "test_loading_state_paints_a_loading_row_before_the_gate_opens",
    "test_cursor_moves_debounce_the_detail_paint_and_drop_stale_work",
    "test_view_state_exposes_archive_view_constant_for_reading_callers",
]
