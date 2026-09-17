"""Externally triggered screenshot export for the live TUI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import os
from pathlib import Path
import signal
from types import FrameType
from typing import Any

from ..screenshot_export import (
    SASE_TUI_SCREENSHOT_DIR_ENV,
    ScreenshotExportPaths,
    complete_export,
    fail_export,
    reserve_export_paths,
)
from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)


class ScreenshotExportMixin:
    """Mixin installing SIGUSR2-triggered live SVG screenshot export."""

    _screenshot_export_previous_sigusr2_handler: (
        signal.Handlers | int | Callable[[int, FrameType | None], Any] | None
    )
    _screenshot_export_signal_loop: asyncio.AbstractEventLoop | None
    _screenshot_export_request_dir: Path | None
    _screenshot_export_async_tasks: set[asyncio.Task[Any]]

    def _install_screenshot_export_signal_handler(self) -> bool:
        """Install the SIGUSR2 handler when a request directory is configured."""
        raw_request_dir = os.environ.get(SASE_TUI_SCREENSHOT_DIR_ENV)
        if not raw_request_dir or not hasattr(signal, "SIGUSR2"):
            return False
        if (
            getattr(self, "_screenshot_export_previous_sigusr2_handler", None)
            is not None
        ):
            return True

        self._screenshot_export_request_dir = Path(raw_request_dir).expanduser()
        previous = signal.getsignal(signal.SIGUSR2)
        loop = asyncio.get_running_loop()

        def schedule() -> None:
            self._schedule_screenshot_export_from_signal()

        try:
            loop.add_signal_handler(signal.SIGUSR2, schedule)
        except (NotImplementedError, RuntimeError, ValueError):

            def handle_signal(_signum: int, _frame: FrameType | None) -> None:
                try:
                    loop.call_soon_threadsafe(schedule)
                except RuntimeError:
                    log.debug("screenshot export signal ignored after loop shutdown")

            try:
                signal.signal(signal.SIGUSR2, handle_signal)
            except (OSError, RuntimeError, ValueError):
                return False
            self._screenshot_export_signal_loop = None
        else:
            self._screenshot_export_signal_loop = loop

        self._screenshot_export_previous_sigusr2_handler = previous
        return True

    def _restore_screenshot_export_signal_handler(self) -> None:
        """Restore the SIGUSR2 handler active before Ace installed ours."""
        previous = getattr(self, "_screenshot_export_previous_sigusr2_handler", None)
        if previous is None or not hasattr(signal, "SIGUSR2"):
            return
        loop = getattr(self, "_screenshot_export_signal_loop", None)
        if loop is not None:
            try:
                loop.remove_signal_handler(signal.SIGUSR2)
            except (RuntimeError, ValueError):
                pass
        try:
            signal.signal(signal.SIGUSR2, previous)
        except (OSError, RuntimeError, ValueError):
            pass
        self._screenshot_export_previous_sigusr2_handler = None
        self._screenshot_export_signal_loop = None
        self._screenshot_export_request_dir = None

    def _schedule_screenshot_export_from_signal(self) -> None:
        """Spawn the screenshot export body outside Textual's message pump."""
        request_dir = getattr(self, "_screenshot_export_request_dir", None)
        if request_dir is None:
            return
        spawn_pump_free_task(
            self,
            self._run_screenshot_export(request_dir),
            name="sase-tui-screenshot-export",
            registry_attr="_screenshot_export_async_tasks",
        )

    async def _run_screenshot_export(
        self,
        request_dir: Path | str | None = None,
    ) -> ScreenshotExportPaths:
        """Export the current frame to *request_dir* using the request protocol."""
        directory = Path(
            request_dir
            if request_dir is not None
            else self._require_screenshot_export_request_dir()
        )
        paths = await asyncio.to_thread(reserve_export_paths, directory)
        try:
            restore_cursor_blink = self._prepare_screenshot_frame()
            try:
                refresh = getattr(self, "refresh", None)
                if callable(refresh):
                    refresh(layout=True)
                wait_for_refresh = getattr(self, "wait_for_refresh", None)
                if callable(wait_for_refresh):
                    await wait_for_refresh()
                svg = self.export_screenshot(title="sase tui", simplify=True)  # type: ignore[attr-defined]
            finally:
                self._restore_screenshot_cursor_blink(restore_cursor_blink)
            await asyncio.to_thread(complete_export, paths, svg)
        except Exception as error:
            await asyncio.to_thread(fail_export, paths, error)
            raise
        return paths

    def _require_screenshot_export_request_dir(self) -> Path:
        request_dir = getattr(self, "_screenshot_export_request_dir", None)
        if request_dir is None:
            raise RuntimeError(f"{SASE_TUI_SCREENSHOT_DIR_ENV} is not configured")
        return request_dir

    def _prepare_screenshot_frame(self) -> list[tuple[Any, bool]]:
        """Normalize focused cursor state before exporting a screenshot frame."""
        try:
            from textual.widgets import Input, TextArea
        except Exception:
            return []

        restore: list[tuple[Any, bool]] = []
        for screen in getattr(self, "screen_stack", ()):
            for widget in screen.walk_children():
                if not isinstance(widget, (Input, TextArea)):
                    continue
                restore.append((widget, bool(getattr(widget, "cursor_blink", False))))
                widget.cursor_blink = False
                pause_blink = getattr(widget, "_pause_blink", None)
                if callable(pause_blink):
                    pause_blink(visible=bool(getattr(widget, "has_focus", False)))
                line_cache = getattr(widget, "_line_cache", None)
                if line_cache is not None:
                    try:
                        line_cache.clear()
                    except Exception:
                        pass
                try:
                    widget.refresh()
                except Exception:
                    pass
        return restore

    def _restore_screenshot_cursor_blink(
        self,
        restore: list[tuple[Any, bool]],
    ) -> None:
        """Restore cursor blink settings changed for a screenshot export."""
        for widget, cursor_blink in restore:
            try:
                widget.cursor_blink = cursor_blink
            except Exception:
                pass
