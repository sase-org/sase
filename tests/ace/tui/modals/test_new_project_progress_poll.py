"""Progress log-version skip and terminal settlement without NDJSON."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals.new_project_progress import NewProjectProgress
from sase.ace.tui.proc_observer import ObservedProc
from sase.core.time import local_now


class _Row:
    def __init__(
        self,
        *,
        version: int,
        status: str = "running",
        message: str = "",
        error: str | None = None,
    ) -> None:
        self.proc_id = "add-1"
        self.durable_proc_id = None
        self.log = SimpleNamespace(version=version)
        self.output = "log"
        self.status = status
        self.message = message
        self.phase = ""
        self.log_path = ""
        self.exit_code = None
        self.error = error


class _ProgressApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.row = _Row(version=3)
        self._proc_generation = 1
        self.tails: list[bool] = []

    def compose(self) -> ComposeResult:
        yield NewProjectProgress()

    def _effective_proc_projection(self) -> Any:
        return SimpleNamespace(rows=[self.row])


async def test_authoritative_unchanged_version_skips_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _ProgressApp()

    async def fake_read(self: NewProjectProgress, *, settled: bool = False) -> None:
        app.tails.append(settled)
        self._tail_in_flight = False

    monkeypatch.setattr(NewProjectProgress, "_read_tail", fake_read)
    async with app.run_test(size=(80, 24)) as pilot:
        progress = app.query_one(NewProjectProgress)
        progress.attach_proc("add-1")
        await pilot.pause()
        assert app.tails == [False]
        progress._poll_log()
        progress._poll_log()
        assert app.tails == [False]


async def test_version_zero_keeps_fallback_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _ProgressApp()
    app.row = _Row(version=0)

    async def fake_read(self: NewProjectProgress, *, settled: bool = False) -> None:
        app.tails.append(settled)
        self._tail_in_flight = False

    monkeypatch.setattr(NewProjectProgress, "_read_tail", fake_read)
    async with app.run_test(size=(80, 24)) as pilot:
        progress = app.query_one(NewProjectProgress)
        progress.attach_proc("add-1")
        await pilot.pause()
        progress._poll_log()
        await pilot.pause()
        assert app.tails == [False, False]


async def test_late_tail_does_not_overwrite_initialized() -> None:
    app = _ProgressApp()
    async with app.run_test(size=(80, 24)):
        progress = app.query_one(NewProjectProgress)
        progress.attach_proc("add-1")
        progress._apply_text(
            '{"event":"result","status":"ok","project":{"key":"k","name":"n"}}'
        )
        progress.mark_initialized()
        assert progress.current_view().steps["sase-init"].state == "done"
        progress._apply_text("not-json old tail")
        assert progress.current_view().steps["sase-init"].state == "done"
        assert progress.current_view().result is not None
        assert progress.current_view().result.status == "ok"


async def test_unsuccessful_settlement_without_ndjson_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _ProgressApp()
    app.row = _Row(version=2, status="failed", message="exited 1", error="boom")

    async def fake_read(self: NewProjectProgress, *, settled: bool = False) -> None:
        self._tail_in_flight = False
        if settled:
            self._settlement_tail_done = True
            self._fail_without_result(self._proc_row())

    monkeypatch.setattr(NewProjectProgress, "_read_tail", fake_read)
    async with app.run_test(size=(80, 24)) as pilot:
        progress = app.query_one(NewProjectProgress)
        progress.attach_proc("add-1")
        await pilot.pause()
        result = progress.current_view().result
        assert result is not None
        assert result.status == "failed"
        assert result.message == "boom"
        assert result.project_key == ""


async def test_observe_completion_failure_without_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _ProgressApp()

    async def fake_read(self: NewProjectProgress, *, settled: bool = False) -> None:
        self._tail_in_flight = False

    monkeypatch.setattr(NewProjectProgress, "_read_tail", fake_read)
    async with app.run_test(size=(80, 24)) as pilot:
        progress = app.query_one(NewProjectProgress)
        progress.attach_proc("add-1")
        await pilot.pause()
        progress.observe_completion(
            TrackedProcCompletion(
                proc_info=ObservedProc(
                    proc_id="add-1",
                    proc_type="project.add",
                    cl_name="",
                    project_file="",
                    status="error",
                    message="submit failed",
                    started_at=local_now(),
                ),
                success=False,
                message="submit failed",
                output="",
                error="submit failed",
            )
        )
        result = progress.current_view().result
        assert result is not None
        assert result.status == "failed"
        assert result.message == "submit failed"
