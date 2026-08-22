"""Live session-worker output tests for the Procs pane."""

from __future__ import annotations

import threading
from typing import cast

import pytest
from textual.containers import VerticalScroll
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.actions.proc_actions import ProcActionsMixin, TrackedProcResult
from sase.ace.tui.session_proc_reporter import SessionProcReporter
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


class _LiveSessionProcsApp(ProcActionsMixin, ProcsTestApp):
    """Procs test app that can submit a real session-local worker."""


async def test_session_worker_live_output_updates_before_completion() -> None:
    started = threading.Event()
    second = threading.Event()
    release_second = threading.Event()
    release_done = threading.Event()

    def body(reporter: SessionProcReporter) -> TrackedProcResult[None]:
        for index in range(80):
            reporter.log(f"first-{index}")
        started.set()
        assert release_second.wait(timeout=5)
        reporter.log("second line")
        second.set()
        assert release_done.wait(timeout=5)
        return TrackedProcResult(success=True, message="done")

    static = task(
        "ok",
        label="mail sase-41",
        status="success",
        age_seconds=120,
        output="Mailed PR\n",
    )

    async with _LiveSessionProcsApp(queue(static)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        app = cast(_LiveSessionProcsApp, pilot.app)
        submitted = app._submit_session_worker(
            "sync",
            body,
            display_name="live sync",
        )
        assert submitted is not None
        try:
            await wait_for(pilot, lambda: started.is_set())
            pane._refresh_running_output()

            option_list = pane.query_one("#procs-list", OptionList)
            session_index = next(
                index
                for index in range(option_list.option_count)
                if "live sync" in option_list.get_option_at_index(index).prompt.plain
            )
            option_list.highlighted = session_index
            pane._display_output(submitted)
            live = output_plain(pane)
            assert "first-0" in live
            assert "second line" not in live
            assert pane._body_cache[submitted.proc_id][0] == submitted.log.version

            other_index = 0 if session_index else 1
            option_list.highlighted = other_index
            pane._display_output(pane._get_selected_task())
            assert "Mailed PR" in output_plain(pane)

            option_list.highlighted = session_index
            pane._display_output(submitted)
            assert "first-0" in output_plain(pane)
            await pilot.pause()

            if pane._refresh_timer is not None:
                pane._refresh_timer.stop()
            pane._user_scrolled = True
            scroll = pane.query_one("#procs-output-scroll", VerticalScroll)
            pane._force_scroll_output_to(0, scroll=scroll)
            statuses = dict(pane._last_statuses)
            cached_version = pane._body_cache[submitted.proc_id][0]

            release_second.set()
            await wait_for(pilot, lambda: second.is_set())
            pane._refresh_running_output()

            live = output_plain(pane)
            assert "second line" in live
            assert pane._user_scrolled is True
            assert scroll.scroll_y == 0
            assert pane._last_statuses == statuses
            assert pane._body_cache[submitted.proc_id][0] > cached_version
            body = live.split("─")[-1]
            assert "first-0" in body
            assert "Working..." not in body
        finally:
            release_second.set()
            release_done.set()
        await wait_for(pilot, lambda: submitted.proc_id not in app._session_workers)
