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


class _CommonPlaceholderCacheApp(StartupCommonPlaceholdersMixin):
    def __init__(self) -> None:
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
    with (
        patch(
            "sase.history.prompt_placeholders.seed_common_placeholders_from_history",
        ) as seed,
        patch(
            "sase.history.prompt_placeholders.common_placeholder_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_placeholders.load_common_placeholders",
            return_value=["feature flag"],
        ) as load,
    ):
        result = _load_common_placeholders(limit=100, previous_token=None)

    assert result.source_token == token
    assert result.placeholders == ["feature flag"]
    seed.assert_called_once_with(100)
    load.assert_called_once_with(100)


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
            "sase.history.prompt_placeholders.load_common_placeholders",
        ) as load,
    ):
        result = _load_common_placeholders(limit=100, previous_token=token)

    assert result.source_token == token
    assert result.placeholders is None
    seed.assert_not_called()
    load.assert_not_called()


@pytest.mark.asyncio
async def test_forget_prunes_cache_publishes_and_forces_disk_reload() -> None:
    app = _CommonPlaceholderCacheApp()
    reloaded_token = ("/tmp/prompt_placeholders.json", 30, 40)

    app.forget_common_placeholder("alpha")

    assert app._common_placeholders_cache == ["beta"]
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
            "sase.history.prompt_placeholders.load_common_placeholders",
            return_value=["beta", "gamma"],
        ) as load,
    ):
        app.warm_common_placeholders()
        assert app.worker_task is not None
        await app.worker_task

    assert app._common_placeholders_source_token == reloaded_token
    assert app._common_placeholders_cache == ["beta", "gamma"]
    assert app._common_placeholders_generation == 6
    assert app.refreshes == 2
    seed.assert_called_once_with(100)
    load.assert_called_once_with(100)
