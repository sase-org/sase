"""Tests for the app-level sticky-misspellings cache loader."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions._startup_misspellings import StartupMisspellingsMixin
from sase.history.prompt_misspellings import _MisspellingSets


class _MisspellingsCacheApp(StartupMisspellingsMixin):
    def __init__(self) -> None:
        self._misspelled_words_cache: frozenset[str] | None = None
        self._allowed_misspellings_cache: frozenset[str] | None = None
        self._misspellings_source_token: Any = None
        self._misspellings_generation = 0
        self._misspellings_rebuild_in_flight = False
        self._misspellings_rebuild_pending = False
        self.refreshes = 0
        self.worker_tasks: list[asyncio.Task[None]] = []

    def run_worker(self, worker: Any, **_kwargs: Any) -> None:
        self.worker_tasks.append(asyncio.create_task(worker()))

    def _refresh_misspelling_overlays(self) -> None:
        self.refreshes += 1


@pytest.mark.asyncio
async def test_warm_publishes_and_bumps_the_generation() -> None:
    app = _MisspellingsCacheApp()
    token = ("/tmp/prompt_misspellings.json", 10, 20)

    with (
        patch(
            "sase.history.prompt_misspellings.misspellings_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_misspellings.load_misspellings",
            return_value=_MisspellingSets(
                misspelled=("recieve",),
                allowed=("Bugyi",),
            ),
        ),
    ):
        app.warm_misspellings()
        await app.worker_tasks[-1]

    assert app.misspelled_words() == frozenset({"recieve"})
    assert app._misspellings_source_token == token
    assert app._misspellings_generation == 1
    assert app.refreshes == 1


@pytest.mark.asyncio
async def test_matching_source_token_skips_the_reload() -> None:
    token = ("/tmp/prompt_misspellings.json", 10, 20)
    app = _MisspellingsCacheApp()
    app._misspelled_words_cache = frozenset({"recieve"})
    app._allowed_misspellings_cache = frozenset()
    app._misspellings_source_token = token

    with (
        patch(
            "sase.history.prompt_misspellings.misspellings_source_token",
            return_value=token,
        ),
        patch("sase.history.prompt_misspellings.load_misspellings") as load,
    ):
        app.warm_misspellings()
        await app.worker_tasks[-1]

    load.assert_not_called()
    assert app.misspelled_words() == frozenset({"recieve"})
    assert app.refreshes == 0


@pytest.mark.asyncio
async def test_optimistic_record_is_visible_before_persist_finishes() -> None:
    app = _MisspellingsCacheApp()

    with patch("sase.history.prompt_misspellings.record_misspelling") as persist:
        app.record_misspelling("recieve")

        # Visible synchronously, before the scheduled persist task has had a
        # chance to run at all.
        assert app.misspelled_words() == frozenset({"recieve"})
        assert app.refreshes == 1
        persist.assert_not_called()

        await app.worker_tasks[-1]

    persist.assert_called_once_with("recieve")


@pytest.mark.asyncio
async def test_failing_persist_leaves_the_in_memory_set_intact() -> None:
    app = _MisspellingsCacheApp()

    with patch(
        "sase.history.prompt_misspellings.record_misspelling",
        side_effect=OSError("disk full"),
    ):
        app.record_misspelling("recieve")
        await app.worker_tasks[-1]

    assert app.misspelled_words() == frozenset({"recieve"})


@pytest.mark.asyncio
async def test_store_read_failure_degrades_to_empty_set() -> None:
    app = _MisspellingsCacheApp()

    with patch(
        "sase.history.prompt_misspellings.misspellings_source_token",
        side_effect=OSError("boom"),
    ):
        app.warm_misspellings()
        await app.worker_tasks[-1]

    assert app.misspelled_words() == frozenset()
    assert app.refreshes == 1


def test_overlay_fanout_reaches_only_mounted_prompt_text_areas() -> None:
    class _FakeTextArea:
        def __init__(self, mounted: bool) -> None:
            self.is_mounted = mounted
            self.refreshed = 0

        def _refresh_misspelling_overlay(self) -> None:
            self.refreshed += 1

    mounted = _FakeTextArea(mounted=True)
    unmounted = _FakeTextArea(mounted=False)

    class _QueryApp(StartupMisspellingsMixin):
        def __init__(self) -> None:
            self._misspelled_words_cache: frozenset[str] | None = frozenset()
            self._allowed_misspellings_cache: frozenset[str] | None = frozenset()
            self._misspellings_source_token: Any = None
            self._misspellings_generation = 0
            self._misspellings_rebuild_in_flight = False
            self._misspellings_rebuild_pending = False

        def query(self, _widget_type: Any) -> list[Any]:
            return [mounted, unmounted]

    app = _QueryApp()

    app._refresh_misspelling_overlays()

    assert mounted.refreshed == 1
    assert unmounted.refreshed == 0
