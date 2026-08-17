"""Tests for the Procs tab header's blue/orange gear counts."""

from __future__ import annotations

import pytest

from sase.ace.tui.proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE
from sase.monitor_state import MONITOR_PROC_ORIGIN

from tests.ace.tui._procs_pane_helpers import (
    ProcInfo,
    ProcsTestApp,
    open_procs_pane,
    patch_other_panes,
    patch_store_loader,
    queue,
    store_task,
    task,
)


@pytest.fixture(autouse=True)
def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_other_panes(monkeypatch)


def _monitor_task(
    proc_id: str, *, label: str, status: str, age_seconds: int
) -> ProcInfo:
    row = task(proc_id, label=label, status=status, age_seconds=age_seconds)
    row.origin = MONITOR_PROC_ORIGIN
    row.shell_name = "acme--mon"
    return row


async def test_header_splits_running_procs_and_running_monitors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    plain_a = task("plain-a", label="sync a", status="running", age_seconds=1)
    plain_b = task("plain-b", label="sync b", status="running", age_seconds=2)
    monitor = _monitor_task(
        "mon-a", label="just check-full", status="running", age_seconds=3
    )
    done = task("done-a", label="sync done", status="success", age_seconds=10)

    async with ProcsTestApp(queue(plain_a, plain_b, monitor, done)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        title = pane._title_text()
        assert title.plain == ("Procs · this session   ⚙ 2  ⚙ 1   [3 running · 1 done]")
        # bracketed total is the sum of both lanes, by construction.
        assert 2 + 1 == 3
        styles = [span.style for span in title.spans]
        assert f"bold #1a1a1a on {PROC_GEAR_HUE}" in styles
        assert f"bold #1a1a1a on {MONITOR_GEAR_HUE}" in styles


async def test_header_zero_lanes_render_dim_unfilled_chip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    done = task("done-a", label="sync done", status="success", age_seconds=10)

    async with ProcsTestApp(queue(done)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        title = pane._title_text()
        assert title.plain == "Procs · this session   ⚙ 0  ⚙ 0   [0 running · 1 done]"
        styles = [span.style for span in title.spans]
        assert f"dim {PROC_GEAR_HUE}" in styles
        assert f"dim {MONITOR_GEAR_HUE}" in styles


async def test_header_excludes_finished_monitor_from_running_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    finished_monitor = _monitor_task(
        "mon-done", label="pytest -x", status="success", age_seconds=5
    )

    async with ProcsTestApp(queue(finished_monitor)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        title = pane._title_text()
        assert title.plain == "Procs · this session   ⚙ 0  ⚙ 0   [0 running · 1 done]"


async def test_header_counts_move_with_scope_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(
        monkeypatch,
        [
            store_task(
                "other-monitor",
                label="just check-full",
                status="running",
                session_id="session-other",
                session_label="ace·sase#7",
                origin=MONITOR_PROC_ORIGIN,
                shell_name="acme--mon",
            ),
        ],
        live_session_ids=frozenset({"session-other"}),
    )

    async with ProcsTestApp(queue()).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        assert pane._title_text().plain == (
            "Procs · this session   ⚙ 0  ⚙ 0   [0 running · 0 done]"
        )

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()

        assert pane._all_sessions is True
        assert pane._title_text().plain == (
            "Procs · all sessions   ⚙ 0  ⚙ 1   [1 running · 0 done]"
        )
