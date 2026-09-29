"""Catalog loading tests for ``==model`` prompt model completion.

Split from ``test_model_explicit_completion``; shared helpers live in
``_model_explicit_completion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets._file_completion_workers import (
    ModelCompletionCatalogWorkerResult,
)
from sase.ace.tui.widgets.model_alias_completion import MODEL_ALIAS_COMPLETION_KIND
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_MODE_SUBTITLE,
    is_model_explicit_completion_placeholder,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._model_explicit_completion_shared import (
    ColdModelExplicitCompletionTestApp,
    ModelExplicitCompletionTestApp,
    explicit_entries,
)

__all__ = [
    "test_loading_model_rows_are_not_selectable",
    "test_model_catalog_failure_can_retry_explicit_unavailable_row",
    "test_model_catalog_worker_refreshes_only_matching_shortcut_kind",
    "test_model_catalog_worker_rejects_stale_explicit_prompt_state",
]


async def test_loading_model_rows_are_not_selectable() -> None:
    app = ModelExplicitCompletionTestApp(entries=None)
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("==")
        ta.cursor_location = (0, 2)

        with patch.object(type(ta), "_schedule_model_completion_catalog_load") as load:
            assert ta._try_model_explicit_completion() is True

        load.assert_called_once_with()
        assert is_model_explicit_completion_placeholder(
            ta._file_completion_candidates[0]
        )
        assert ta._file_completion_candidates[0].display == "Loading models…"
        assert bar._subtitle_base != MODEL_EXPLICIT_MODE_SUBTITLE

        await pilot.press("ctrl+f")

        assert ta.text == "=="
        assert app.submitted == []
        assert ta._file_completion_active is True
        assert ta._insert_g_prefix_pending is False

        await pilot.press("enter")

        assert ta.text == "=="
        assert app.submitted == ["=="]
        assert ta._file_completion_active is False


async def test_model_catalog_worker_refreshes_only_matching_shortcut_kind() -> None:
    app = ColdModelExplicitCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("==g")
            ta.cursor_location = (0, 3)

            assert ta._try_model_explicit_completion() is True

            ta._completion_kind = MODEL_ALIAS_COMPLETION_KIND
            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=explicit_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()
            assert ta._model_completion_catalog_loaded is True
            assert ta._model_completion_catalog_available is True


async def test_model_catalog_worker_rejects_stale_explicit_prompt_state() -> None:
    app = ColdModelExplicitCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("==g")
            ta.cursor_location = (0, 3)

            assert ta._try_model_explicit_completion() is True

            ta.load_text("==f")
            ta.cursor_location = (0, 3)
            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=explicit_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()
            assert ta._model_completion_catalog_loaded is True
            assert ta._model_completion_catalog_available is True


async def test_model_catalog_failure_can_retry_explicit_unavailable_row() -> None:
    app = ColdModelExplicitCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("==")
            ta.cursor_location = (0, 2)

            assert ta._try_model_explicit_completion() is True
            ta._apply_model_completion_catalog_result(
                ModelCompletionCatalogWorkerResult(rows=(), available=False)
            )

            assert ta._model_completion_catalog_available is False
            assert ta._file_completion_candidates[0].display == "Models unavailable"

            ta._model_completion_catalog_inflight = False
            with patch.object(
                type(ta),
                "_schedule_model_completion_catalog_load",
            ) as retry:
                assert ta._try_model_explicit_completion(force=True) is True

            retry.assert_called_once_with(force=True)
            assert ta._file_completion_candidates[0].display == "Loading models…"
