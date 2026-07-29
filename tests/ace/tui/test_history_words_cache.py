"""Tests for the app-level prompt-history word cache loader."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions._startup_history_words import (
    StartupHistoryWordsMixin,
    _load_history_prompt_words,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings


class _HistoryCacheApp(StartupHistoryWordsMixin):
    def __init__(self) -> None:
        self._history_prompt_words_cache = ["review", "revise"]
        self._history_prompt_words_source_token = (
            1000,
            5,
            (("2607.json", 10, 20),),
            ("/tmp/deleted.json", -1, -1),
        )
        self._history_prompt_words_rebuild_in_flight = False
        self._history_prompt_words_rebuild_pending = False
        self.refreshes = 0
        self.worker_task: asyncio.Task[None] | None = None

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return PromptCompletionSettings(history_word_count=1000, word_min_length=5)

    def run_worker(self, worker: Any, **_kwargs: Any) -> None:
        self.worker_task = asyncio.create_task(worker())

    def _refresh_visible_history_word_surfaces(self) -> None:
        self.refreshes += 1


def test_history_word_loader_rebuilds_when_source_token_changes() -> None:
    token = (
        1000,
        5,
        (("2607.json", 10, 20),),
        ("/tmp/deleted.json", -1, -1),
    )
    with (
        patch(
            "sase.history.prompt_words.history_words_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_words.collect_recent_prompt_words",
            return_value=["recent", "words"],
        ) as collect,
    ):
        result = _load_history_prompt_words(
            max_words=1000,
            min_length=5,
            previous_token=None,
        )

    assert result.source_token == token
    assert result.words == ["recent", "words"]
    collect.assert_called_once_with(max_words=1000, min_length=5)


def test_history_word_loader_skips_collection_for_unchanged_token() -> None:
    token = (
        1000,
        5,
        (("2607.json", 10, 20),),
        ("/tmp/deleted.json", -1, -1),
    )
    with (
        patch(
            "sase.history.prompt_words.history_words_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_words.collect_recent_prompt_words",
        ) as collect,
    ):
        result = _load_history_prompt_words(
            max_words=1000,
            min_length=5,
            previous_token=token,
        )

    assert result.source_token == token
    assert result.words is None
    collect.assert_not_called()


@pytest.mark.asyncio
async def test_forget_prunes_cache_repaints_and_forces_disk_reload() -> None:
    app = _HistoryCacheApp()
    reloaded_token = (
        1000,
        5,
        (("2607.json", 30, 40),),
        ("/tmp/deleted.json", 50, 60),
    )

    app.forget_history_prompt_word("review")

    assert app._history_prompt_words_cache == ["revise"]
    assert app._history_prompt_words_source_token is None
    assert app.refreshes == 1

    with (
        patch(
            "sase.history.prompt_words.history_words_source_token",
            return_value=reloaded_token,
        ),
        patch(
            "sase.history.prompt_words.collect_recent_prompt_words",
            return_value=["revise", "restore"],
        ) as collect,
    ):
        app.warm_history_prompt_words()
        assert app.worker_task is not None
        await app.worker_task

    assert app._history_prompt_words_source_token == reloaded_token
    assert app._history_prompt_words_cache == ["revise", "restore"]
    assert app.refreshes == 2
    collect.assert_called_once_with(max_words=1000, min_length=5)
