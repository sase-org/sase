"""Externally triggered screenshot export for the live TUI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import hashlib
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

_SCREENSHOT_DEBOUNCERS = (
    "_patch_detail_debouncer",
    "_agent_detail_debouncer",
    "_axe_detail_debouncer",
)
_SCREENSHOT_STABLE_FRAME_COUNT = 3
_SCREENSHOT_SETTLE_TIMEOUT_SECONDS = 3.0
_SCREENSHOT_SETTLING_TIMER_MAX_SECONDS = 0.5


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
        stage = "prepare"
        try:
            try:
                restore_cursor_blink = self._prepare_screenshot_frame()
            except (AssertionError, RuntimeError) as exc:
                if not _is_textual_refresh_context_error(exc):
                    raise
                restore_cursor_blink = []
            try:
                stage = "request refresh"
                self._request_screenshot_refresh_if_available()
                stage = "wait for settled frame"
                svg = await self._export_settled_screenshot_svg()
            finally:
                self._restore_screenshot_cursor_blink(restore_cursor_blink)
            stage = "complete export"
            await asyncio.to_thread(complete_export, paths, svg)
        except Exception as error:
            await asyncio.to_thread(
                fail_export,
                paths,
                f"{stage}: {type(error).__name__}: {error}",
            )
            raise
        return paths

    def _request_screenshot_refresh_if_available(self) -> None:
        """Request a final Textual refresh when the signal task context permits it."""
        refresh = getattr(self, "refresh", None)
        if not callable(refresh):
            return
        try:
            refresh(layout=True)
        except (AssertionError, RuntimeError) as exc:
            if not _is_textual_refresh_context_error(exc):
                raise

    async def _wait_for_screenshot_refresh_if_available(self) -> None:
        """Wait for Textual's next refresh when the signal task context permits it."""
        wait_for_refresh = getattr(self, "wait_for_refresh", None)
        if not callable(wait_for_refresh):
            await asyncio.sleep(0)
            return
        try:
            await wait_for_refresh()
        except (AssertionError, RuntimeError) as exc:
            if not _is_textual_refresh_context_error(exc):
                raise

    async def _export_settled_screenshot_svg(self) -> str:
        """Export a frame after finite visual work and SVG output settle."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _SCREENSHOT_SETTLE_TIMEOUT_SECONDS
        previous_svg: str | None = None
        stable_frames = 0
        frame_digests: list[str] = []
        pending: tuple[list[str], list[str], list[str], list[str]] = ([], [], [], [])

        while True:
            self._request_screenshot_refresh_if_available()
            await self._wait_for_screenshot_refresh_if_available()
            self._clear_screenshot_transient_state()
            pending = self._pending_screenshot_visual_work()

            if any(pending):
                previous_svg = None
                stable_frames = 0
            else:
                svg = self.export_screenshot(title="sase tui", simplify=True)  # type: ignore[attr-defined]
                digest = hashlib.sha256(svg.encode()).hexdigest()[:12]
                frame_digests.append(digest)
                frame_digests = frame_digests[-4:]
                if svg == previous_svg:
                    stable_frames += 1
                else:
                    stable_frames = 1
                previous_svg = svg
                if stable_frames >= _SCREENSHOT_STABLE_FRAME_COUNT:
                    return svg

            if loop.time() >= deadline:
                debouncers, workers, timers, animations = pending
                raise RuntimeError(
                    "timed out waiting for screenshot frame convergence; "
                    f"stable_frames={stable_frames}/"
                    f"{_SCREENSHOT_STABLE_FRAME_COUNT}; "
                    f"frame_digests={frame_digests}; "
                    f"pending_debouncers={debouncers}; "
                    f"pending_workers={workers}; "
                    f"pending_one_shot_timers={timers}; "
                    f"pending_animations={animations}"
                )
            await asyncio.sleep(min(0.02, max(0.0, deadline - loop.time())))

    def _clear_screenshot_transient_state(self) -> None:
        try:
            from textual.widgets import Button
        except Exception:
            return
        for screen in getattr(self, "screen_stack", ()):
            try:
                buttons = screen.query(Button)
            except Exception:
                continue
            for button in buttons:
                try:
                    button.remove_class("-active")
                except Exception:
                    pass

    def _pending_screenshot_visual_work(
        self,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        debouncers = [
            name
            for name in _SCREENSHOT_DEBOUNCERS
            if bool(getattr(getattr(self, name, None), "is_pending", False))
        ]
        # Live TUI captures run against the user's real host state, where broad
        # data refresh and update-check workers may be active for longer than a
        # bounded screenshot export. Frame convergence below proves compositor
        # progress; finite visual blockers are covered by debouncers, timers,
        # and animations.
        workers: list[str] = []

        animator = getattr(self, "animator", None)
        animations = [
            f"running:{key!r}" for key in getattr(animator, "_animations", {})
        ]
        animations.extend(
            f"scheduled:{key!r}" for key in getattr(animator, "_scheduled", {})
        )

        nodes: list[Any] = [self]
        for screen in getattr(self, "screen_stack", ()):
            nodes.append(screen)
            try:
                nodes.extend(screen.walk_children(with_self=True))
            except TypeError:
                nodes.extend(screen.walk_children())
            except Exception:
                pass

        timers: list[str] = []
        seen_nodes: set[int] = set()
        for node in nodes:
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            for timer in getattr(node, "_timers", ()):
                task = getattr(timer, "_task", None)
                try:
                    interval = float(getattr(timer, "_interval", float("inf")))
                except (TypeError, ValueError):
                    interval = float("inf")
                if (
                    getattr(timer, "_repeat", None) == 0
                    and interval <= _SCREENSHOT_SETTLING_TIMER_MAX_SECONDS
                    and task is not None
                    and not task.done()
                ):
                    timers.append(str(getattr(timer, "name", timer)))
        return debouncers, workers, timers, animations

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


def _is_textual_refresh_context_error(exc: BaseException) -> bool:
    return "Node must be running before calling wait_for_refresh" in str(exc)
