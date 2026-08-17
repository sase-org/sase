"""Tests for the app-level common-placeholder cache loader."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions._startup_common_placeholders import (
    StartupCommonPlaceholdersMixin,
    _load_common_placeholders,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.history.prompt_placeholders import (
    CommonPlaceholderIndex,
    _PlaceholderEntry,
)


def _entry(text: str, *, count: int = 1) -> _PlaceholderEntry:
    return _PlaceholderEntry(
        text=text,
        count=count,
        last_used="260801_000000",
        context_uses=count,
        context={"topic": count},
    )


def _index(*texts: str, prompt_count: int = 8) -> CommonPlaceholderIndex:
    entries = tuple(_entry(text, count=index + 1) for index, text in enumerate(texts))
    return CommonPlaceholderIndex(
        entries=entries,
        prompt_count=prompt_count,
        context_frequency={"topic": prompt_count},
        max_count=max((entry.count for entry in entries), default=0),
    )


class _CommonPlaceholderCacheApp(StartupCommonPlaceholdersMixin):
    def __init__(self) -> None:
        self._common_placeholder_index_cache = _index("alpha", "beta", prompt_count=12)
        self._common_placeholders_cache = ["alpha", "beta"]
        self._common_placeholders_source_token = (
            "/tmp/prompt_placeholders.json",
            10,
            20,
        )
        self._common_placeholders_generation = 4
        self._common_placeholders_rebuild_in_flight = False
        self._common_placeholders_rebuild_pending = False
        self.refreshes = 0
        self.worker_task: asyncio.Task[None] | None = None

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return PromptCompletionSettings(common_placeholder_count=100)

    def run_worker(self, worker: Any, **_kwargs: Any) -> None:
        self.worker_task = asyncio.create_task(worker())

    def _refresh_visible_common_placeholder_surfaces(self) -> None:
        self.refreshes += 1


def test_loader_seeds_once_then_loads_on_the_first_warm() -> None:
    token = ("/tmp/prompt_placeholders.json", 10, 20)
    index = _index("feature flag")
    with (
        patch(
            "sase.history.prompt_placeholders.seed_common_placeholders_from_history",
        ) as seed,
        patch(
            "sase.history.prompt_placeholders.common_placeholder_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_placeholders.load_common_placeholder_index",
            return_value=index,
        ) as load,
    ):
        result = _load_common_placeholders(limit=100, previous_token=None)

    assert result.source_token == token
    assert result.index is index
    seed.assert_called_once_with(100)
    load.assert_called_once_with()


def test_loader_skips_the_seed_and_the_read_for_an_unchanged_token() -> None:
    token = ("/tmp/prompt_placeholders.json", 10, 20)
    with (
        patch(
            "sase.history.prompt_placeholders.seed_common_placeholders_from_history",
        ) as seed,
        patch(
            "sase.history.prompt_placeholders.common_placeholder_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_placeholders.load_common_placeholder_index",
        ) as load,
    ):
        result = _load_common_placeholders(limit=100, previous_token=token)

    assert result.source_token == token
    assert result.index is None
    seed.assert_not_called()
    load.assert_not_called()


def test_loader_applies_the_configured_limit_to_the_warm_index() -> None:
    token = ("/tmp/prompt_placeholders.json", 10, 20)
    index = _index("alpha", "beta", "gamma", prompt_count=9)
    with (
        patch(
            "sase.history.prompt_placeholders.seed_common_placeholders_from_history",
        ),
        patch(
            "sase.history.prompt_placeholders.common_placeholder_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_placeholders.load_common_placeholder_index",
            return_value=index,
        ),
    ):
        result = _load_common_placeholders(limit=2, previous_token=None)

    assert result.index is not None
    assert [entry.text for entry in result.index.entries] == ["alpha", "beta"]
    assert result.index.prompt_count == 9
    assert result.index.context_frequency == {"topic": 9}


@pytest.mark.asyncio
async def test_forget_prunes_index_publishes_and_forces_disk_reload() -> None:
    app = _CommonPlaceholderCacheApp()
    reloaded = _index("beta", "gamma")
    reloaded_token = ("/tmp/prompt_placeholders.json", 30, 40)
    warm = app.common_placeholder_index()
    assert warm is not None
    original_frequency = dict(warm.context_frequency)

    app.forget_common_placeholder("alpha")

    assert app.common_placeholders() == ["beta"]
    forgotten = app.common_placeholder_index()
    assert forgotten is not None
    assert [entry.text for entry in forgotten.entries] == ["beta"]
    assert forgotten.prompt_count == 12
    assert forgotten.context_frequency == original_frequency
    assert app._common_placeholders_source_token is None
    assert app._common_placeholders_generation == 5
    assert app.refreshes == 1

    with (
        patch(
            "sase.history.prompt_placeholders.seed_common_placeholders_from_history",
            return_value=False,
        ) as seed,
        patch(
            "sase.history.prompt_placeholders.common_placeholder_source_token",
            return_value=reloaded_token,
        ),
        patch(
            "sase.history.prompt_placeholders.load_common_placeholder_index",
            return_value=reloaded,
        ) as load,
    ):
        app.warm_common_placeholders()
        assert app.worker_task is not None
        await app.worker_task

    assert app._common_placeholders_source_token == reloaded_token
    assert app.common_placeholders() == ["beta", "gamma"]
    assert app.common_placeholder_index() is reloaded
    assert app._common_placeholders_generation == 6
    assert app.refreshes == 2
    seed.assert_called_once_with(100)
    load.assert_called_once_with()
