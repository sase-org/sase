"""Filter-session tests for the Admin Center Procs pane."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.config_center_session import (
    AdminCenterSessionState,
    ProcsSessionState,
)
from sase.ace.tui.modals.procs_filter_bar import ProcsFilterBar
from tests.ace.tui._procs_pane_helpers import (
    ProcsTestApp,
    open_procs_pane,
    output_plain,
    patch_other_panes,
    queue,
    task,
)


@pytest.fixture(autouse=True)
def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_other_panes(monkeypatch)


def _status_plain(bar: ProcsFilterBar) -> str:
    return bar.query_one(f"#{bar.STATUS_ID}", Static).render().plain


def _option_labels(option_list: OptionList) -> list[str]:
    return [
        option_list.get_option_at_index(index).prompt.plain
        for index in range(option_list.option_count)
    ]


async def test_slash_opens_the_bar_prefilled_with_the_committed_query() -> None:
    monitor = task("mon", label="just check-full", status="running", age_seconds=1)
    session_state = AdminCenterSessionState(procs=ProcsSessionState(query="monitor"))

    async with ProcsTestApp(queue(monitor)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=session_state)

        await pilot.press("slash")
        await pilot.pause()

        bar = pane.query_one(ProcsFilterBar)
        assert bar._editing  # type: ignore[attr-defined]
        editor = bar.query_one(f"#{bar.INPUT_ID}")
        assert editor.text == "monitor"  # type: ignore[attr-defined]


async def test_typing_narrows_rows_live_without_committing() -> None:
    monitor = task("mon", label="just check-full", status="running", age_seconds=1)
    plain = task("plain", label="sync sase-1", status="running", age_seconds=2)

    async with ProcsTestApp(queue(monitor, plain)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 2

        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:sync")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync"))
        await pilot.pause()

        assert option_list.option_count == 1
        assert "sync sase-1" in _option_labels(option_list)[0]
        # Nothing is committed while the session is still open.
        assert pane._session_state.query == ""  # type: ignore[attr-defined]


async def test_submit_commits_the_query_and_focuses_the_row_list() -> None:
    keep = task("keep", label="sync sase-1", status="running", age_seconds=1)
    drop = task("drop", label="mail sase-2", status="success", age_seconds=5)

    async with ProcsTestApp(queue(keep, drop)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:sync")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync"))
        await pilot.pause()
        bar.post_message(ProcsFilterBar.Submitted("name:sync"))
        await pilot.pause()

        assert pane._session_state.query == "name:sync"  # type: ignore[attr-defined]
        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 1
        assert not bar._editing  # type: ignore[attr-defined]
        assert bar.display is True
        assert option_list.has_focus


async def test_dismiss_restores_the_query_active_when_the_session_opened() -> None:
    keep = task("keep", label="sync sase-1", status="running", age_seconds=1)
    other = task("other", label="mail sase-2", status="success", age_seconds=5)
    session_state = AdminCenterSessionState(procs=ProcsSessionState(query="name:sync"))

    async with ProcsTestApp(queue(keep, other)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=session_state)
        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 1

        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:mail")
        bar.post_message(ProcsFilterBar.QueryChanged("name:mail"))
        await pilot.pause()
        assert option_list.option_count == 1
        assert "mail sase-2" in _option_labels(option_list)[0]

        bar.post_message(ProcsFilterBar.Dismissed())
        await pilot.pause()

        assert pane._session_state.query == "name:sync"  # type: ignore[attr-defined]
        assert "sync sase-1" in _option_labels(option_list)[0]


async def test_selection_falls_back_when_the_selected_row_is_filtered_out() -> None:
    # Rows sort most-recent-first, so ``drop`` (the smaller age) lands on the
    # default-highlighted row 0 without any extra selection bookkeeping.
    drop = task("drop", label="mail sase-2", status="success", age_seconds=1)
    keep = task("keep", label="sync sase-1", status="running", age_seconds=5)

    async with ProcsTestApp(queue(drop, keep)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        selected = pane._get_selected_task()
        assert selected is not None
        assert selected.proc_id == "drop"

        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:sync")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync"))
        await pilot.pause()

        assert pane.query_one("#procs-list", OptionList).option_count == 1
        task_obj = pane._get_selected_task()
        assert task_obj is not None
        assert task_obj.proc_id == "keep"


async def test_jump_hints_renumber_over_visible_rows_only() -> None:
    keep_a = task("keep-a", label="sync sase-1", status="running", age_seconds=1)
    drop = task("drop", label="mail sase-2", status="success", age_seconds=5)
    keep_b = task("keep-b", label="sync sase-3", status="running", age_seconds=9)

    async with ProcsTestApp(queue(keep_a, drop, keep_b)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:sync")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync"))
        bar.post_message(ProcsFilterBar.Submitted("name:sync"))
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 2
        labels = _option_labels(option_list)
        assert labels[0].startswith("[0] ")
        assert labels[1].startswith("[1] ")


async def test_no_match_empty_state_names_the_key_that_clears_it() -> None:
    row = task("only", label="sync sase-1", status="running", age_seconds=1)

    async with ProcsTestApp(queue(row)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:nope")
        bar.post_message(ProcsFilterBar.QueryChanged("name:nope"))
        bar.post_message(ProcsFilterBar.Submitted("name:nope"))
        await pilot.pause()

        assert pane.query_one("#procs-list", OptionList).option_count == 0
        text = output_plain(pane)
        assert "No procs match the filter" in text
        assert "/" in text


async def test_limit_caps_rows_and_reports_a_lower_bound_match_count() -> None:
    first = task("first", label="sync sase-1", status="running", age_seconds=1)
    second = task("second", label="sync sase-2", status="running", age_seconds=2)

    async with ProcsTestApp(queue(first, second)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:sync limit:1")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync limit:1"))
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 1
        assert "1+" in _status_plain(bar)


async def test_parse_error_reports_in_status_lane_and_leaves_rows_untouched() -> None:
    keep = task("keep", label="sync sase-1", status="running", age_seconds=1)
    other = task("other", label="mail sase-2", status="success", age_seconds=5)

    async with ProcsTestApp(queue(keep, other)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:sync")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync"))
        await pilot.pause()
        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 1

        bar.set_query("name:sync bogus:1")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync bogus:1"))
        await pilot.pause()

        assert "error" in bar.query_one(f"#{bar.STATUS_ID}").classes
        # The previously-matched rows stay untouched by the bad edit.
        assert option_list.option_count == 1
        assert "sync sase-1" in _option_labels(option_list)[0]


async def test_query_survives_admin_center_close_and_reopen() -> None:
    row = task("keep", label="sync sase-1", status="running", age_seconds=1)
    session_state = AdminCenterSessionState()

    async with ProcsTestApp(queue(row)).run_test() as pilot:
        modal, pane = await open_procs_pane(pilot, session_state=session_state)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("name:sync")
        bar.post_message(ProcsFilterBar.QueryChanged("name:sync"))
        bar.post_message(ProcsFilterBar.Submitted("name:sync"))
        await pilot.pause()
        assert session_state.procs.query == "name:sync"

        modal.dismiss(None)
        await pilot.pause()

        _, reopened = await open_procs_pane(pilot, session_state=session_state)
        assert reopened._filter_query == "name:sync"  # type: ignore[attr-defined]
        reopened_bar = reopened.query_one(ProcsFilterBar)
        assert reopened_bar.display is True


async def test_running_procs_new_output_moves_it_into_filter_on_next_tick() -> None:
    running = task("run", label="sync sase-1", status="running", age_seconds=1)

    async with ProcsTestApp(queue(running)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("out:needle")
        bar.post_message(ProcsFilterBar.QueryChanged("out:needle"))
        bar.post_message(ProcsFilterBar.Submitted("out:needle"))
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 0

        running.log.append("found the needle")
        pane._refresh_running_output()
        await pilot.pause()

        assert option_list.option_count == 1


async def test_consume_priority_tab_tracks_the_completion_menu() -> None:
    row = task("only", label="sync sase-1", status="running", age_seconds=1)

    async with ProcsTestApp(queue(row)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        pane.show_filters()
        await pilot.pause()
        bar = pane.query_one(ProcsFilterBar)
        bar.set_query("moni")
        bar.post_message(ProcsFilterBar.QueryChanged("moni"))
        await pilot.pause()

        assert pane.consume_priority_tab() is False

        await pilot.press("down")
        await pilot.pause()
        assert pane.consume_priority_tab() is True

        await pilot.press("escape")
        await pilot.pause()
        assert pane.consume_priority_tab() is False
