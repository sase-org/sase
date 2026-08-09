"""Tests that `y` (refresh) on the Patches tab does not block the event loop.

The regression guarded here is the `y` keymap (and the timer-driven
auto-refresh) calling the synchronous `_reload_and_reposition()` on the
event-loop thread. With many project spec files on disk, `find_all_patches()`
is several seconds of I/O — during that time Textual cannot dispatch any
keypresses (j/k/tab-switch), so the TUI appears frozen.

The fix routes the Patches tab through `_reload_and_reposition_async()`, which
pushes the disk scan to a background thread via `asyncio.to_thread`. These
tests exercise that async path directly and verify the event loop stays
responsive while the load is in flight.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.patch import PatchMixin
from sase.core.query_corpus_facade import QueryCorpus


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


class _FakeRustCorpus:
    def __init__(self, length: int) -> None:
        self.length = length

    def __len__(self) -> int:
        return self.length


def _fake_query_corpus(patches: list[MagicMock]) -> QueryCorpus:
    return QueryCorpus(
        source_list_id=id(patches),
        expected_length=len(patches),
        rust_handle=_FakeRustCorpus(len(patches)),
    )


class FakeApp(PatchMixin):
    """Minimal AceApp stand-in for exercising the patch refresh path."""

    def __init__(self, patches: list[MagicMock]) -> None:
        self.patches: list = patches  # type: ignore[assignment]
        self.current_idx: int = 0
        self.parsed_query = MagicMock()
        self.query_string = ""
        self.hide_reverted = False
        self.hide_submitted = False
        self._all_patches: list = patches  # type: ignore[assignment]
        self.marked_indices: set[int] = set()
        self._hidden_reverted_count = 0
        self._hidden_submitted_count = 0
        self._patches_loading: bool = False
        self._patches_refresh_scheduled: bool = False
        self._patches_refresh_pending: bool = False
        self._query_corpus: QueryCorpus | None = None
        self._query_corpus_source_list_id: int | None = None
        self._scheduled: list[Any] = []

    def _refresh_display(self) -> None:
        pass

    def _spawn_patches_refresh_task(self) -> None:
        """Record scheduling without starting a task in narrow unit tests."""
        self._scheduled.append(self._run_patches_async_refresh)

    def notify(self, *args: Any, **kwargs: Any) -> None:
        pass

    @property
    def canonical_query_string(self) -> str:
        return ""


@pytest.mark.asyncio
async def test_reload_does_not_block_event_loop() -> None:
    """While the disk scan is in flight, other coroutines must still run.

    On the old synchronous implementation, `find_all_patches()` runs on
    the event-loop thread — so nothing else (including a navigation
    keypress) can progress until it returns. The async variant pushes the
    call to `asyncio.to_thread`, leaving the loop free.
    """
    disk_cs = [_make_cs("alpha"), _make_cs("beta"), _make_cs("gamma")]

    def slow_find_all() -> list[MagicMock]:
        # Sleeps on a worker thread; the event loop must stay responsive.
        time.sleep(0.2)
        return disk_cs

    app = FakeApp([_make_cs("alpha"), _make_cs("beta"), _make_cs("gamma")])

    with (
        patch(
            "sase.ace.patch.find_all_patches_cached",
            side_effect=slow_find_all,
        ),
        patch.object(
            PatchMixin,
            "_filter_patches",
            side_effect=lambda _all: disk_cs,
        ),
        patch(
            "sase.core.query_corpus_facade.compile_query_corpus",
            side_effect=_fake_query_corpus,
        ),
    ):
        reload_task = asyncio.create_task(app._reload_and_reposition_async())

        # Simulate a navigation keypress that fires while the disk scan is
        # still blocked in the worker thread. On the sync implementation
        # this would queue up behind the scan. On the async implementation
        # it runs immediately.
        await asyncio.sleep(0.05)
        assert not reload_task.done(), (
            "disk scan completed suspiciously fast — test cannot observe "
            "responsiveness during the load"
        )
        app.current_idx = 2  # user pressed j twice

        await reload_task

    # After the reload, the cursor should have been repositioned onto the
    # element whose name matched the *post-await* selection (gamma, index 2).
    # This proves the async path re-captured state after the await.
    assert app.patches[app.current_idx].name == "gamma"


@pytest.mark.asyncio
async def test_run_async_refresh_sets_and_clears_loading_flag() -> None:
    """The loading guard flips around the awaited load."""
    disk_cs = [_make_cs("alpha")]

    def fast_find_all() -> list[MagicMock]:
        return disk_cs

    app = FakeApp([_make_cs("alpha")])

    with (
        patch(
            "sase.ace.patch.find_all_patches_cached",
            side_effect=fast_find_all,
        ),
        patch.object(
            PatchMixin,
            "_filter_patches",
            side_effect=lambda _all: disk_cs,
        ),
        patch(
            "sase.core.query_corpus_facade.compile_query_corpus",
            side_effect=_fake_query_corpus,
        ),
    ):
        assert not app._patches_loading
        await app._run_patches_async_refresh()
        assert not app._patches_loading


@pytest.mark.asyncio
async def test_schedule_coalesces_in_flight_refreshes() -> None:
    """Re-scheduling while a refresh is running marks a pending follow-up.

    Last-request-wins: a stampede of `y` presses collapses into at most the
    in-flight load plus one follow-up.
    """
    app = FakeApp([_make_cs("alpha")])
    app._patches_loading = True

    app._schedule_patches_async_refresh()
    app._schedule_patches_async_refresh()
    app._schedule_patches_async_refresh()

    # Nothing was spawned because a refresh is already running.
    assert app._scheduled == []
    # But a single follow-up is pending.
    assert app._patches_refresh_pending is True


@pytest.mark.asyncio
async def test_schedule_when_idle_spawns_pump_free_task() -> None:
    """When no refresh is in flight, scheduling invokes the task spawner."""
    app = FakeApp([_make_cs("alpha")])

    app._schedule_patches_async_refresh()

    assert len(app._scheduled) == 1
    assert app._scheduled[0] == app._run_patches_async_refresh
    assert app._patches_refresh_pending is False
