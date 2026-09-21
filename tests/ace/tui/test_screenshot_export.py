"""Tests for live TUI screenshot export request files."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions import screenshot_export as screenshot_export_module
from sase.ace.tui.actions.screenshot_export import ScreenshotExportMixin
from sase.ace.tui.screenshot_export import (
    complete_export,
    fail_export,
    reserve_export_paths,
    screenshot_request_dir,
)


class _SettlingExportApp(ScreenshotExportMixin):
    """Minimal host for the screenshot export mixin's convergence loop."""

    screen_stack = ()
    workers = ()

    def __init__(self) -> None:
        self.refresh_count = 0
        self.export_count = 0
        self._frame = 0

    def refresh(
        self,
        *,
        repaint: bool = True,
        layout: bool = False,
        recompose: bool = False,
    ) -> None:
        del repaint, layout, recompose
        self.refresh_count += 1

    async def wait_for_refresh(self) -> None:
        self._frame += 1

    def export_screenshot(self, *, title: str, simplify: bool) -> str:
        del title, simplify
        self.export_count += 1
        label = "settled" if self._frame >= 2 else f"frame-{self._frame}"
        return f"<svg><text>{label}</text></svg>"


class _BackgroundWorkerExportApp(_SettlingExportApp):
    """Settling host with a non-visual worker that remains active."""

    def __init__(self) -> None:
        super().__init__()
        self.workers = (
            SimpleNamespace(name="automatic-update-check", is_running=True),
        )


class _StalledRefreshExportApp(_SettlingExportApp):
    """Settling host whose refresh await never completes."""

    async def wait_for_refresh(self) -> None:
        await asyncio.Event().wait()


class _AcknowledgedRefreshExportApp(ScreenshotExportMixin):
    """Settling host that acknowledges real post-refresh callbacks."""

    screen_stack = ()
    workers = ()

    def __init__(self) -> None:
        self.refresh_count = 0
        self.export_count = 0
        self._frame = 0
        self._after_refresh_callbacks: list[object] = []

    def call_after_refresh(self, callback: object) -> None:
        self._after_refresh_callbacks.append(callback)

    def refresh(
        self,
        *,
        repaint: bool = True,
        layout: bool = False,
        recompose: bool = False,
    ) -> None:
        del repaint, layout, recompose
        self.refresh_count += 1
        self._frame += 1
        callbacks = self._after_refresh_callbacks
        self._after_refresh_callbacks = []
        for callback in callbacks:
            assert callable(callback)
            callback()

    async def wait_for_refresh(self) -> None:
        raise AssertionError("Node must be running before calling wait_for_refresh")

    def export_screenshot(self, *, title: str, simplify: bool) -> str:
        del title, simplify
        self.export_count += 1
        label = "settled" if self._frame >= 2 else f"frame-{self._frame}"
        return f"<svg><text>{label}</text></svg>"


class _StalledAcknowledgementExportApp(_AcknowledgedRefreshExportApp):
    """Host that accepts callback scheduling but never runs the callback."""

    def refresh(
        self,
        *,
        repaint: bool = True,
        layout: bool = False,
        recompose: bool = False,
    ) -> None:
        del repaint, layout, recompose
        self.refresh_count += 1
        self._frame += 1


class _RejectedAcknowledgementExportApp(_AcknowledgedRefreshExportApp):
    """Host that rejects post-refresh callback scheduling."""

    def call_after_refresh(self, callback: object) -> None:
        del callback
        raise RuntimeError("callback rejected")


class _DelayedStartupVisibleApp(_AcknowledgedRefreshExportApp):
    """Host whose visible startup surface becomes ready after one attempt."""

    current_tab = "agents"
    _axe_first_load_done = False

    def __init__(self) -> None:
        super().__init__()
        self._agents_first_load_done = False

    def refresh(
        self,
        *,
        repaint: bool = True,
        layout: bool = False,
        recompose: bool = False,
    ) -> None:
        super().refresh(repaint=repaint, layout=layout, recompose=recompose)
        if self.refresh_count >= 2:
            self._agents_first_load_done = True

    def export_screenshot(self, *, title: str, simplify: bool) -> str:
        del title, simplify
        self.export_count += 1
        label = "AFTER_STARTUP_READY" if self._agents_first_load_done else "Loading..."
        return f"<svg><text>{label}</text></svg>"


class _DelayedVisualWorkerApp(ScreenshotExportMixin, App[None]):
    """Real Textual app with finite visual work that completes after export starts."""

    CSS = "#visual-label { width: auto; }"

    def __init__(self) -> None:
        super().__init__()
        self._visual_release: asyncio.Event | None = None
        self._visual_pending_seen: asyncio.Event | None = None

    def compose(self) -> ComposeResult:
        yield Static("BEFORE_DELAYED_VISUAL_WORK", id="visual-label")

    def start_delayed_visual_update(self) -> None:
        self._visual_release = asyncio.Event()
        self._visual_pending_seen = asyncio.Event()

        async def work() -> None:
            assert self._visual_release is not None
            await self._visual_release.wait()
            self.query_one("#visual-label", Static).update("AFTER_DELAYED_VISUAL_WORK")
            self.refresh(layout=True)

        self.run_worker(
            work(),
            name="delayed-update",
            group="screenshot-visual",
            exit_on_error=False,
        )

    async def release_after_pending_visual_work_seen(self) -> None:
        assert self._visual_pending_seen is not None
        assert self._visual_release is not None
        await self._visual_pending_seen.wait()
        self._visual_release.set()

    def _pending_screenshot_visual_worker_labels(self) -> list[str]:
        labels = super()._pending_screenshot_visual_worker_labels()
        if labels and self._visual_pending_seen is not None:
            self._visual_pending_seen.set()
        return labels


def test_screenshot_request_dir_sanitizes_tmux_names(tmp_path: Path) -> None:
    request_dir = screenshot_request_dir("agent/session", "sase tmux:1", root=tmp_path)

    assert request_dir.parent.parent == tmp_path
    assert "/" not in request_dir.relative_to(tmp_path).as_posix().split("/")[0]
    assert request_dir.name.startswith("sase_tmux_1-")


def test_export_protocol_writes_done_and_error_markers(tmp_path: Path) -> None:
    first = reserve_export_paths(tmp_path)

    assert first.sequence == 1
    assert first.pending.exists()
    complete_export(first, "<svg>ok</svg>")

    assert first.svg.read_text(encoding="utf-8") == "<svg>ok</svg>"
    assert first.done.read_text(encoding="utf-8") == "svg=screen_1.svg\n"
    assert not first.pending.exists()

    second = reserve_export_paths(tmp_path)
    fail_export(second, "boom")

    assert second.sequence == 2
    assert second.error.read_text(encoding="utf-8") == "boom\n"
    assert not second.pending.exists()


async def test_app_export_body_writes_svg_and_done(tmp_path: Path) -> None:
    async with AcePage() as page:
        paths = await page.app._run_screenshot_export(tmp_path)

    assert paths.sequence == 1
    assert paths.done.exists()
    assert not paths.error.exists()
    svg = paths.svg.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "rich-terminal" in svg


async def test_export_body_waits_for_stable_visual_frame(tmp_path: Path) -> None:
    app = _SettlingExportApp()

    paths = await app._run_screenshot_export(tmp_path)

    assert paths.done.exists()
    assert not paths.error.exists()
    assert paths.svg.read_text(encoding="utf-8") == ("<svg><text>settled</text></svg>")
    assert app.export_count >= 4
    assert app.refresh_count >= 4


async def test_export_body_uses_call_after_refresh_acknowledgement(
    tmp_path: Path,
) -> None:
    app = _AcknowledgedRefreshExportApp()

    paths = await app._run_screenshot_export(tmp_path)

    assert paths.done.exists()
    assert not paths.error.exists()
    assert paths.svg.read_text(encoding="utf-8") == ("<svg><text>settled</text></svg>")
    assert app.export_count >= 4
    assert app.refresh_count >= 4


async def test_export_body_ignores_running_background_workers(tmp_path: Path) -> None:
    app = _BackgroundWorkerExportApp()

    paths = await app._run_screenshot_export(tmp_path)

    assert paths.done.exists()
    assert not paths.error.exists()
    assert paths.svg.read_text(encoding="utf-8") == ("<svg><text>settled</text></svg>")
    assert app.export_count >= 4


async def test_export_body_waits_for_tagged_finite_visual_worker(
    tmp_path: Path,
) -> None:
    app = _DelayedVisualWorkerApp()

    async with app.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        app.start_delayed_visual_update()
        release_task = asyncio.create_task(app.release_after_pending_visual_work_seen())
        try:
            paths = await app._run_screenshot_export(tmp_path)
        finally:
            release_task.cancel()
            await asyncio.gather(release_task, return_exceptions=True)

    svg = paths.svg.read_text(encoding="utf-8")
    assert "AFTER_DELAYED_VISUAL_WORK" in svg
    assert "BEFORE_DELAYED_VISUAL_WORK" not in svg
    assert paths.done.exists()
    assert not paths.error.exists()


async def test_export_body_bounds_stalled_refresh_and_writes_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _StalledRefreshExportApp()
    monkeypatch.setattr(
        screenshot_export_module,
        "_SCREENSHOT_SETTLE_TIMEOUT_SECONDS",
        0.05,
    )

    with pytest.raises(RuntimeError, match="timed out waiting for screenshot refresh"):
        await app._run_screenshot_export(tmp_path)

    error = tmp_path / "screen_1.error"
    assert error.exists()
    assert "timed out waiting for screenshot refresh" in error.read_text(
        encoding="utf-8"
    )
    assert not (tmp_path / "screen_1.pending").exists()


async def test_export_body_bounds_stalled_refresh_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _StalledAcknowledgementExportApp()
    monkeypatch.setattr(
        screenshot_export_module,
        "_SCREENSHOT_SETTLE_TIMEOUT_SECONDS",
        0.05,
    )

    with pytest.raises(
        RuntimeError,
        match="timed out waiting for screenshot refresh acknowledgement",
    ):
        await app._run_screenshot_export(tmp_path)

    error = tmp_path / "screen_1.error"
    assert error.exists()
    assert "timed out waiting for screenshot refresh acknowledgement" in (
        error.read_text(encoding="utf-8")
    )
    callbacks = app._after_refresh_callbacks
    for callback in callbacks:
        assert callable(callback)
        callback()


async def test_export_body_reports_rejected_refresh_acknowledgement(
    tmp_path: Path,
) -> None:
    app = _RejectedAcknowledgementExportApp()

    with pytest.raises(
        RuntimeError,
        match="failed to schedule screenshot refresh acknowledgement",
    ):
        await app._run_screenshot_export(tmp_path)

    assert "failed to schedule screenshot refresh acknowledgement" in (
        tmp_path / "screen_1.error"
    ).read_text(encoding="utf-8")


async def test_export_body_waits_for_visible_startup_readiness(
    tmp_path: Path,
) -> None:
    app = _DelayedStartupVisibleApp()

    paths = await app._run_screenshot_export(tmp_path)

    svg = paths.svg.read_text(encoding="utf-8")
    assert "AFTER_STARTUP_READY" in svg
    assert "Loading..." not in svg


def test_hidden_startup_work_does_not_block_visible_surface() -> None:
    app = _DelayedStartupVisibleApp()
    app._agents_first_load_done = True
    app._axe_first_load_done = False

    _debouncers, workers, _timers, _animations = app._pending_screenshot_visual_work()

    assert "startup-visible:services" not in workers


def test_current_tab_controls_startup_readiness_after_navigation() -> None:
    app = _DelayedStartupVisibleApp()
    app.current_tab = "services"
    app._agents_first_load_done = True
    app._axe_first_load_done = False

    _debouncers, workers, _timers, _animations = app._pending_screenshot_visual_work()

    assert "startup-visible:services" in workers


async def test_projected_detail_hydration_counts_as_visual_work() -> None:
    app = _SettlingExportApp()
    never_finished = asyncio.Event()
    task = asyncio.create_task(never_finished.wait(), name="hydrate-selected-agent")
    app._projected_record_hydration_tasks = {task}
    try:
        _debouncers, workers, _timers, _animations = (
            app._pending_screenshot_visual_work()
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert workers == ["_projected_record_hydration_tasks:hydrate-selected-agent"]


async def test_app_export_body_tolerates_signal_task_refresh_wait_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:

        async def fail_wait_for_refresh() -> None:
            raise AssertionError("Node must be running before calling wait_for_refresh")

        monkeypatch.setattr(page.app, "wait_for_refresh", fail_wait_for_refresh)
        paths = await page.app._run_screenshot_export(tmp_path)

    assert paths.done.exists()
    assert not paths.error.exists()
    assert "<svg" in paths.svg.read_text(encoding="utf-8")


async def test_app_export_body_tolerates_signal_task_refresh_request_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:

        def fail_refresh(
            *,
            repaint: bool = True,
            layout: bool = False,
            recompose: bool = False,
        ) -> None:
            del repaint, layout, recompose
            raise RuntimeError("Node must be running before calling wait_for_refresh")

        monkeypatch.setattr(page.app, "refresh", fail_refresh)
        with pytest.raises(RuntimeError, match="Node must be running"):
            await page.app._run_screenshot_export(tmp_path)

    assert (tmp_path / "screen_1.error").exists()


async def test_app_export_body_tolerates_signal_task_prepare_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:

        def fail_prepare() -> list[tuple[object, bool]]:
            raise RuntimeError("Node must be running before calling wait_for_refresh")

        monkeypatch.setattr(page.app, "_prepare_screenshot_frame", fail_prepare)
        paths = await page.app._run_screenshot_export(tmp_path)

    assert paths.done.exists()
    assert not paths.error.exists()
    assert "<svg" in paths.svg.read_text(encoding="utf-8")


async def test_signal_schedule_spawns_export_task(tmp_path: Path) -> None:
    async with AcePage() as page:
        page.app._screenshot_export_request_dir = tmp_path
        page.app._schedule_screenshot_export_from_signal()
        await page.wait_for(lambda _state: (tmp_path / "screen_1.done").exists())

    assert (tmp_path / "screen_1.svg").exists()
