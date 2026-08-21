"""Prompt-pane finalizer inventory worker tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from textual.worker import Worker, WorkerState

from sase.ace.tui.widgets._file_completion_workers import (
    _FinalizerInventoryWorkerResult,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.finalizers.catalog import _FinalizerCatalogBuild, _FinalizerCatalogEntry

from .test_finalizer_completion import SAMPLE_FINALIZERS


def test_cold_finalizer_snapshot_schedules_one_threaded_worker() -> None:
    text_area = PromptTextArea()

    with patch.object(type(text_area), "run_worker") as run_worker:
        text_area._schedule_finalizer_inventory_load()
        text_area._schedule_finalizer_inventory_load()

    assert text_area._finalizer_inflight is True
    run_worker.assert_called_once()
    assert run_worker.call_args.kwargs["group"] == "prompt-finalizers"
    assert run_worker.call_args.kwargs["thread"] is True


async def test_mount_warms_finalizer_inventory_off_the_ui_thread() -> None:
    from ._completion_helpers import CompletionTestApp

    app = CompletionTestApp()
    with patch.object(PromptTextArea, "run_worker") as run_worker:
        async with app.run_test():
            groups = [call.kwargs.get("group") for call in run_worker.call_args_list]
            assert "prompt-finalizers" in groups


def test_app_override_skips_the_config_worker() -> None:
    text_area = PromptTextArea()
    fake_app = SimpleNamespace(finalizer_inventory=lambda: (SAMPLE_FINALIZERS, True))

    with (
        patch.object(PromptTextArea, "app", fake_app),
        patch.object(PromptTextArea, "run_worker") as run_worker,
    ):
        text_area._schedule_finalizer_inventory_load()
        state = text_area._finalizer_inventory_state()

    run_worker.assert_not_called()
    assert state[0] == "warm"


def test_stale_finalizer_result_does_not_refresh_a_non_final_menu() -> None:
    text_area = PromptTextArea()
    text_area._file_completion_active = True
    text_area._completion_kind = "directive_arg"
    text_area.load_text("%wait:coder")
    text_area.cursor_location = (0, len("%wait:coder"))

    with patch.object(text_area, "_refresh_file_completion_from_cursor") as refresh:
        text_area._apply_finalizer_inventory_result(
            _FinalizerInventoryWorkerResult(rows=SAMPLE_FINALIZERS, available=True)
        )

    refresh.assert_not_called()
    assert text_area._finalizer_available is True


def test_warm_result_refreshes_an_open_finalizer_menu() -> None:
    text_area = PromptTextArea()
    text_area._file_completion_active = True
    text_area._completion_kind = "directive_arg"
    text_area.load_text("%final:")
    text_area.cursor_location = (0, len("%final:"))

    with patch.object(text_area, "_refresh_file_completion_from_cursor") as refresh:
        text_area._apply_finalizer_inventory_result(
            _FinalizerInventoryWorkerResult(rows=SAMPLE_FINALIZERS, available=True)
        )

    refresh.assert_called_once()


def test_worker_error_marks_catalog_unavailable() -> None:
    text_area = PromptTextArea()
    text_area._finalizer_inflight = True
    worker = SimpleNamespace(
        name="prompt-finalizers",
        group="prompt-finalizers",
        result=None,
    )
    event = cast(
        Worker.StateChanged,
        SimpleNamespace(worker=worker, state=WorkerState.ERROR),
    )

    with patch.object(text_area, "_refresh_file_completion_from_cursor"):
        text_area.on_worker_state_changed(event)

    assert text_area._finalizer_inflight is False
    assert text_area._finalizer_available is False
    assert text_area._finalizer_inventory == ()


def test_worker_task_uses_the_cached_catalog_builder() -> None:
    text_area = PromptTextArea()
    captured: list[object] = []

    with patch.object(type(text_area), "run_worker") as run_worker:
        text_area._schedule_finalizer_inventory_load()
        captured.append(run_worker.call_args.args[0])

    task = captured[0]
    catalog = _FinalizerCatalogBuild(
        status="ok",
        entries=(
            _FinalizerCatalogEntry(value="commit", provider_ref="builtin@commit"),
        ),
    )
    with patch(
        "sase.finalizers.catalog.build_finalizer_completion_catalog",
        return_value=catalog,
    ) as builder:
        result = task()

    builder.assert_called_once()
    assert isinstance(result, _FinalizerInventoryWorkerResult)
    assert result.available is True
    assert result.rows[0]["value"] == "commit"
