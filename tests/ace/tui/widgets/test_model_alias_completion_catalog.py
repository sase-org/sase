"""Catalog loading tests for ``=alias`` prompt model completion.

Split from ``test_model_alias_completion``; shared helpers live in
``_model_alias_completion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets._file_completion_workers import (
    ModelCompletionCatalogWorkerResult,
)
from sase.ace.tui.widgets.model_alias_completion import (
    MODEL_ALIAS_COMPLETION_KIND,
    MODEL_ALIAS_MODE_SUBTITLE,
    is_model_alias_completion_placeholder,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from tests._xprompt_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
)

from ._model_alias_completion_shared import (
    ColdModelAliasCompletionTestApp,
    ModelAliasCompletionTestApp,
    alias_entries,
)

__all__ = [
    "clear_model_completion_cache",
    "test_cold_model_alias_catalog_shows_loading_without_blocking_keys",
    "test_loading_model_alias_row_is_not_selectable",
    "test_model_alias_catalog_cache_miss_after_loaded_reschedules",
    "test_model_alias_catalog_failure_can_retry_from_unavailable_row",
    "test_model_alias_catalog_request_does_not_revive_inactive_stack_pane",
    "test_model_alias_catalog_worker_refreshes_matching_request",
    "test_model_alias_catalog_worker_rejects_stale_prompt_state",
]


async def test_loading_model_alias_row_is_not_selectable() -> None:
    app = ModelAliasCompletionTestApp(entries=None)
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("=")
        ta.cursor_location = (0, 1)

        with patch.object(type(ta), "_schedule_model_completion_catalog_load") as load:
            assert ta._try_model_alias_completion() is True

        load.assert_called_once_with()
        assert is_model_alias_completion_placeholder(ta._file_completion_candidates[0])
        assert ta._file_completion_candidates[0].display == "Loading model aliases…"
        assert bar._subtitle_base != MODEL_ALIAS_MODE_SUBTITLE

        await pilot.press("ctrl+f")

        assert ta.text == "="
        assert app.submitted == []
        assert ta._file_completion_active is True
        assert ta._insert_g_prefix_pending is False

        await pilot.press("enter")

        assert ta.text == "="
        assert app.submitted == ["="]
        assert ta._file_completion_active is False


async def test_cold_model_alias_catalog_shows_loading_without_blocking_keys() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True) as run_worker:
        async with app.run_test() as pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False

            await pilot.press("=")

            assert ta._file_completion_active is True
            assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
            assert is_model_alias_completion_placeholder(
                ta._file_completion_candidates[0]
            )
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )

            await pilot.press("x")
            await pilot.press("ctrl+f")

            assert ta.text == "=x"
            assert app.submitted == []
            assert ta._file_completion_active is True
            assert ta._insert_g_prefix_pending is False

    assert any(
        kwargs.get("group") == "prompt-model-catalog" and kwargs.get("thread") is True
        for _args, kwargs in run_worker.call_args_list
    )


async def test_model_alias_catalog_worker_refreshes_matching_request() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("=l")
            ta.cursor_location = (0, 2)

            assert ta._try_model_alias_completion() is True

            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=alias_entries(),
                        available=True,
                    )
                )

            refresh.assert_called_once_with()


async def test_model_alias_catalog_worker_rejects_stale_prompt_state() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("=l")
            ta.cursor_location = (0, 2)

            assert ta._try_model_alias_completion() is True

            ta.load_text("=s")
            ta.cursor_location = (0, 2)
            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=alias_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()
            assert ta._model_completion_catalog_loaded is True
            assert ta._model_completion_catalog_available is True


async def test_model_alias_catalog_failure_can_retry_from_unavailable_row() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("=")
            ta.cursor_location = (0, 1)

            assert ta._try_model_alias_completion() is True
            ta._apply_model_completion_catalog_result(
                ModelCompletionCatalogWorkerResult(rows=(), available=False)
            )

            assert ta._model_completion_catalog_available is False
            assert ta._file_completion_candidates[0].display == (
                "Model aliases unavailable"
            )

            ta._model_completion_catalog_inflight = False
            with patch.object(
                type(ta),
                "_schedule_model_completion_catalog_load",
            ) as retry:
                assert ta._try_model_alias_completion(force=True) is True

            retry.assert_called_once_with(force=True)
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )


async def test_model_alias_catalog_cache_miss_after_loaded_reschedules() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_loaded = True
            ta._model_completion_catalog_available = True
            ta._model_completion_catalog_inflight = False
            ta.load_text("=")
            ta.cursor_location = (0, 1)

            with patch.object(
                type(ta),
                "_schedule_model_completion_catalog_load",
            ) as load:
                assert ta._try_model_alias_completion() is True

            load.assert_called_once_with()
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )


async def test_model_alias_catalog_request_does_not_revive_inactive_stack_pane() -> (
    None
):
    app = ColdModelAliasCompletionTestApp(initial_panes=["top", "=l"])
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            bottom = bar.active_text_area()
            bottom._model_completion_catalog_inflight = False

            assert bottom._try_model_alias_completion() is True
            assert bottom._model_completion_catalog_request is not None

            bar.focus_relative(-1)
            await pilot.pause()

            assert bar.active_text_area() is not bottom
            assert bottom._file_completion_active is False
            with patch.object(
                bottom,
                "_refresh_file_completion_from_cursor",
            ) as refresh:
                bottom._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=alias_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()
