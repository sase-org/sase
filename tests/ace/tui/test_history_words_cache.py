"""Tests for the app-level prompt-history word cache loader."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions._startup_history_words import (
    StartupHistoryWordsMixin,
    _load_history_prompt_words,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.history.prompt_store import PromptEntry
from sase.history.prompt_word_index import PromptWordIndex, build_prompt_word_index

_INDEX_TOKEN = (5, 24, (("2607.json", 10, 20),))
_DELETIONS_TOKEN = ("/tmp/deleted.json", -1, -1)


def _index(words: list[str]) -> PromptWordIndex:
    text = " ".join(words)
    return build_prompt_word_index(
        min_length=1,
        shard_limit=None,
        prompt_limit=None,
        shard_paths=[Path("fake-shard.json")],
        load_shard_func=lambda _path: [
            PromptEntry(
                text=text,
                timestamp="260101_000000",
                last_used="260101_000000",
            )
        ],
    )


class _HistoryCacheApp(StartupHistoryWordsMixin):
    def __init__(self) -> None:
        self._history_prompt_word_index_cache = _index(["review", "revise"])
        self._history_prompt_word_deletions_cache = frozenset()
        self._history_prompt_words_cache = ["review", "revise"]
        self._history_prompt_words_source_token = (_INDEX_TOKEN, _DELETIONS_TOKEN)
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


def test_history_word_loader_rebuilds_index_when_index_token_changes() -> None:
    new_index = _index(["recent", "words"])
    with (
        patch(
            "sase.history.prompt_word_index.prompt_word_index_source_token",
            return_value=_INDEX_TOKEN,
        ),
        patch(
            "sase.history.prompt_word_deletions.prompt_word_deletions_source_token",
            return_value=_DELETIONS_TOKEN,
        ),
        patch(
            "sase.history.prompt_word_index.build_prompt_word_index",
            return_value=new_index,
        ) as build,
        patch(
            "sase.history.prompt_word_deletions.load_deleted_prompt_words",
            return_value=["gone"],
        ) as load_deleted,
    ):
        result = _load_history_prompt_words(min_length=5, previous_token=None)

    assert result.source_token == (_INDEX_TOKEN, _DELETIONS_TOKEN)
    assert result.index is new_index
    assert result.deletions == frozenset({"gone"})
    build.assert_called_once_with(min_length=5)
    load_deleted.assert_called_once_with()


def test_history_word_loader_skips_rebuild_for_unchanged_tokens() -> None:
    with (
        patch(
            "sase.history.prompt_word_index.prompt_word_index_source_token",
            return_value=_INDEX_TOKEN,
        ),
        patch(
            "sase.history.prompt_word_deletions.prompt_word_deletions_source_token",
            return_value=_DELETIONS_TOKEN,
        ),
        patch(
            "sase.history.prompt_word_index.build_prompt_word_index",
        ) as build,
        patch(
            "sase.history.prompt_word_deletions.load_deleted_prompt_words",
        ) as load_deleted,
    ):
        result = _load_history_prompt_words(
            min_length=5,
            previous_token=(_INDEX_TOKEN, _DELETIONS_TOKEN),
        )

    assert result.source_token == (_INDEX_TOKEN, _DELETIONS_TOKEN)
    assert result.index is None
    assert result.deletions is None
    build.assert_not_called()
    load_deleted.assert_not_called()


def test_history_word_loader_reloads_only_deletions_when_index_unchanged() -> None:
    changed_deletions_token = ("/tmp/deleted.json", 50, 60)
    with (
        patch(
            "sase.history.prompt_word_index.prompt_word_index_source_token",
            return_value=_INDEX_TOKEN,
        ),
        patch(
            "sase.history.prompt_word_deletions.prompt_word_deletions_source_token",
            return_value=changed_deletions_token,
        ),
        patch(
            "sase.history.prompt_word_index.build_prompt_word_index",
        ) as build,
        patch(
            "sase.history.prompt_word_deletions.load_deleted_prompt_words",
            return_value=["review"],
        ) as load_deleted,
    ):
        result = _load_history_prompt_words(
            min_length=5,
            previous_token=(_INDEX_TOKEN, _DELETIONS_TOKEN),
        )

    assert result.source_token == (_INDEX_TOKEN, changed_deletions_token)
    assert result.index is None
    assert result.deletions == frozenset({"review"})
    build.assert_not_called()
    load_deleted.assert_called_once_with()


def test_forget_prunes_cache_and_refreshes_without_rebuilding_index() -> None:
    app = _HistoryCacheApp()
    original_index = app._history_prompt_word_index_cache

    app.forget_history_prompt_word("review")

    assert app._history_prompt_word_index_cache is original_index
    assert app._history_prompt_word_deletions_cache == {"review"}
    assert app._history_prompt_words_cache == ["revise"]
    assert app.refreshes == 1

    app.forget_history_prompt_word("review")
    assert app.refreshes == 1


@pytest.mark.asyncio
async def test_warm_rebuilds_mru_words_from_the_fresh_index() -> None:
    app = _HistoryCacheApp()
    app._history_prompt_word_index_cache = None
    app._history_prompt_words_cache = None
    app._history_prompt_words_source_token = None
    new_index = _index(["restore", "revise"])

    with (
        patch(
            "sase.history.prompt_word_index.prompt_word_index_source_token",
            return_value=_INDEX_TOKEN,
        ),
        patch(
            "sase.history.prompt_word_deletions.prompt_word_deletions_source_token",
            return_value=_DELETIONS_TOKEN,
        ),
        patch(
            "sase.history.prompt_word_index.build_prompt_word_index",
            return_value=new_index,
        ),
        patch(
            "sase.history.prompt_word_deletions.load_deleted_prompt_words",
            return_value=[],
        ),
    ):
        app.warm_history_prompt_words()
        assert app.worker_task is not None
        await app.worker_task

    assert app._history_prompt_word_index_cache is new_index
    assert app._history_prompt_words_cache == ["restore", "revise"]
    assert app.refreshes == 1
